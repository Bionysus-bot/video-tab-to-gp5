import json
import re
import uuid
from pathlib import Path
from fastapi import APIRouter, File, UploadFile, HTTPException
from fastapi.responses import FileResponse
from app.models.conversion import ConversionRequest, ScoreEdit, Activation
from app.services.revision_store import RevisionStore, read, write, checked_id
from app.services import conversion_pipeline as pipeline
from app.storage import manager as storage

router=APIRouter()


def repository(project):
    if not re.fullmatch(r'[a-f0-9]{12}',project) or storage.read_config(project) is None:
        raise HTTPException(404,'项目不存在')
    return RevisionStore(storage.output_path(project,'score'))


def safe(operation):
    try:return operation()
    except FileNotFoundError as exc:raise HTTPException(404,str(exc)) from exc
    except ValueError as exc:raise HTTPException(409,str(exc)) from exc


def summary(revision):
    return {k:v for k,v in revision.items() if k not in ('score','manifest','entities','protected','issues')} | dict(
        measures=len(revision['score']['measures']),issues=len(revision['issues']),
        manual=bool(revision['protected']))


@router.get('/projects/{project}/workspace')
def workspace(project:str):
    store=repository(project)
    store.import_legacy()
    state=store.state()
    revision=store.get(state['active_revision']) if state['active_revision'] else None
    artifacts=sorted([read(p) for p in (store.root/'artifacts').glob('*/manifest.json')],
                     key=lambda a:a['created_at'],reverse=True)
    job=safe(lambda:pipeline.get_job(store,state['latest_job'])) if state.get('latest_job') else None
    pdf=read(store.root/'inputs'/state['input_id']/'manifest.json') if state.get('input_id') else None
    return dict(state=state,revision=revision,revisions=[summary(r) for r in store.list()],
                artifacts=artifacts,job=job,pdf=pdf)


@router.post('/projects/{project}/inputs/pdf')
def upload_pdf(project:str,file:UploadFile=File(...)):
    store=repository(project)
    content=file.file.read(50*1024*1024+1)
    if len(content)>50*1024*1024 or not content.startswith(b'%PDF-'):
        raise HTTPException(422,'请上传不超过 50MB 的有效 PDF')
    identifier=uuid.uuid4().hex
    directory=store.root/'inputs'/identifier
    directory.mkdir(parents=True)
    (directory/'source.pdf').write_bytes(content)
    try:
        details=pipeline.bounded('app.services.conversion_workers','preview_pdf',
            (directory/'source.pdf',directory/'preview.png'),timeout=30)
    except (ValueError,TimeoutError) as exc:
        raise HTTPException(422,'PDF 无法打开：'+str(exc)) from exc
    value=dict(id=identifier,name=Path(file.filename or 'score.pdf').name,**details)
    write(directory/'manifest.json',value)
    store.update(input_id=identifier)
    return value


@router.get('/projects/{project}/inputs/{input_id}/preview')
def pdf_preview(project:str,input_id:str):
    store=repository(project)
    path=safe(lambda:store.root/'inputs'/checked_id(input_id)/'preview.png')
    if not path.exists():raise HTTPException(404,'预览不存在')
    return FileResponse(path,media_type='image/png')


@router.post('/projects/{project}/conversion-jobs',status_code=202)
def conversion(project:str,config:ConversionRequest):
    return safe(lambda:pipeline.start(repository(project),config,project))


@router.get('/projects/{project}/conversion-jobs/{job_id}')
def job_state(project:str,job_id:str):
    return safe(lambda:pipeline.get_job(repository(project),job_id))


@router.post('/projects/{project}/conversion-jobs/{job_id}/cancel')
def cancel(project:str,job_id:str):
    return safe(lambda:pipeline.cancel_job(repository(project),job_id))


@router.post('/projects/{project}/conversion-jobs/{job_id}/resume',status_code=202)
def resume(project:str,job_id:str):
    store=repository(project)
    old=safe(lambda:pipeline.get_job(store,job_id))
    if old['status'] not in pipeline.TERMINAL:raise HTTPException(409,'任务尚未停止')
    config=ConversionRequest.model_validate(old['config'])
    return safe(lambda:pipeline.start(store,config,project,resume=job_id))


@router.get('/projects/{project}/revisions/{revision_id}')
def get_revision(project:str,revision_id:str):
    return safe(lambda:repository(project).get(revision_id))


@router.get('/projects/{project}/revisions')
def list_revisions(project:str):
    return [summary(r) for r in repository(project).list()]


@router.get('/projects/{project}/revisions/{revision_id}/issues')
def list_issues(project:str,revision_id:str,kind:str|None=None):
    revision=safe(lambda:repository(project).get(revision_id))
    return [i for i in revision['issues'] if kind is None or i['kind']==kind]


@router.post('/projects/{project}/revisions/{revision_id}/edits')
def edit(project:str,revision_id:str,change:ScoreEdit):
    return safe(lambda:repository(project).save_edit(revision_id,change.score,change.expected_revision))


@router.post('/projects/{project}/revisions/{revision_id}/measures/{measure_id}/confirm')
def confirm_measure(project:str,revision_id:str,measure_id:str,change:ScoreEdit):
    return safe(lambda:repository(project).confirm_measure(
        revision_id,measure_id,change.score,change.expected_revision))


@router.post('/projects/{project}/revisions/{revision_id}/activate')
def activate(project:str,revision_id:str,change:Activation):
    safe(lambda:repository(project).activate(revision_id,change.expected_revision))
    return dict(status='ok')


@router.get('/projects/{project}/revisions/{revision_id}/rows/{filename}')
def row_image(project:str,revision_id:str,filename:str):
    store=repository(project)
    revision=safe(lambda:store.get(revision_id))
    if filename not in [r['id'] for r in revision['manifest'].get('rows',[])]:
        raise HTTPException(404,'谱行不属于当前版本')
    if not re.fullmatch(r'[a-zA-Z0-9_.-]+\.png',filename):raise HTTPException(404,'无效图片')
    key=revision['manifest'].get('input_key')
    path=store.root/'prepared'/key/'rows'/filename if key else store.directory/'rows'/filename
    if not path.exists():raise HTTPException(404,'来源图片不存在')
    return FileResponse(path,media_type='image/png')


@router.post('/projects/{project}/revisions/{revision_id}/artifacts')
def artifact(project:str,revision_id:str):
    store=repository(project)
    revision=safe(lambda:store.get(revision_id))
    try:return pipeline.make_artifact(store,revision)
    except (ValueError,OSError) as exc:raise HTTPException(422,str(exc)) from exc


@router.post('/projects/{project}/revisions/{revision_id}/rows/{filename}/analysis')
def analysis(project:str,revision_id:str,filename:str):
    store=repository(project)
    revision=safe(lambda:store.get(revision_id))
    row=next((r for r in revision['manifest'].get('rows',[]) if r['id']==filename),None)
    if not row or row.get('layout')!='standard-tab':raise HTTPException(422,'此来源不支持联合谱关联分析')
    key=revision['manifest'].get('input_key')
    path=store.root/'prepared'/key/'rows'/filename if key else store.directory/'rows'/filename
    directory=store.root/'analysis'/revision_id
    directory.mkdir(parents=True,exist_ok=True)
    output=directory/filename
    try:
        result=pipeline.bounded('app.services.score_analysis','analyze_row',
            (path,row,revision['score']['tuning'],output),timeout=120)
    except (ValueError,TimeoutError) as exc:raise HTTPException(422,str(exc)) from exc
    return dict(events=result.get('events',[]),url=f'/api/projects/{project}/revisions/{revision_id}/analysis-images/{filename}')


@router.get('/projects/{project}/revisions/{revision_id}/analysis-images/{filename}')
def analysis_image(project:str,revision_id:str,filename:str):
    store=repository(project);revision=safe(lambda:store.get(revision_id))
    if filename not in [r['id'] for r in revision['manifest'].get('rows',[])]:raise HTTPException(404,'图片不存在')
    path=store.root/'analysis'/revision_id/filename
    if not path.exists():raise HTTPException(404,'请先生成关联图')
    return FileResponse(path,media_type='image/png')


def artifact_dir(project,artifact_id):
    store=repository(project)
    directory=safe(lambda:store.root/'artifacts'/checked_id(artifact_id))
    if not (directory/'manifest.json').exists():raise HTTPException(404,'草稿尚未生成')
    return directory


@router.get('/projects/{project}/artifacts/{artifact_id}')
def get_artifact(project:str,artifact_id:str):
    return read(artifact_dir(project,artifact_id)/'manifest.json')


@router.get('/projects/{project}/artifacts/{artifact_id}/download')
def download(project:str,artifact_id:str):
    return FileResponse(artifact_dir(project,artifact_id)/'draft.gp5',filename='score-draft.gp5')


@router.get('/projects/{project}/artifacts/{artifact_id}/issues')
def download_issues(project:str,artifact_id:str):
    directory=artifact_dir(project,artifact_id)
    return FileResponse(directory/'draft.json',filename='score-issues.json',media_type='application/json')
