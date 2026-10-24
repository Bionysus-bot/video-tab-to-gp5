"""Versioned local orchestration; only the coordinator publishes revisions."""
import multiprocessing
import threading
import time
import uuid
import shutil
import os
import subprocess
from pathlib import Path

from app.models.score import Score, RecognitionConfig, RecognitionResult
from app.services import project_guard
from app.services.revision_store import RevisionStore, read, write, digest, stamp, LOCK
from app.services.conversion_workers import invoke,serve
from app.storage import manager as storage

_live = {}
_live_lock = threading.RLock()
TERMINAL = {'completed','partial','failed','cancelled','interrupted'}


class Cancelled(Exception):
    pass


def stop_process(process):
    process.join(timeout=.2)
    if process.is_alive():
        if os.name=='nt':
            try:
                subprocess.run(['taskkill','/PID',str(process.pid),'/T','/F'],capture_output=True,
                    timeout=5,creationflags=subprocess.CREATE_NO_WINDOW)
            except (OSError,subprocess.TimeoutExpired):process.terminate()
        else:process.terminate()
    process.join(timeout=3)


class ReaderSession:
    def __init__(self):
        context=multiprocessing.get_context('spawn')
        self.connection,child=context.Pipe()
        self.process=context.Process(target=serve,args=(child,),daemon=True)
        self.process.start();child.close()

    def call(self,module,function,args,*,cancel,timeout=180):
        self.connection.send((module,function,args,{}))
        deadline=time.monotonic()+timeout
        while True:
            if cancel.is_set():raise Cancelled()
            if time.monotonic()>deadline:raise TimeoutError('谱行识别超时，已有数据保留。')
            if self.connection.poll(.2):
                try:ok,value=self.connection.recv()
                except EOFError as exc:raise ValueError('读取进程意外退出') from exc
                if not ok:raise ValueError(value)
                return value
            if not self.process.is_alive():raise ValueError('读取进程意外退出')

    def close(self):
        try:self.connection.send(None)
        except (OSError,BrokenPipeError):pass
        stop_process(self.process)
        self.connection.close()


def bounded(module, function, args, *, kwargs=None, cancel=None, timeout=180):
    """Spawn a killable unit of work, drain pipe before joining (large results)."""
    context = multiprocessing.get_context('spawn')
    receiver, sender = context.Pipe(duplex=False)
    process = context.Process(target=invoke,args=(sender,module,function,args,kwargs or {}),daemon=True)
    process.start()
    sender.close()
    deadline = time.monotonic()+timeout
    try:
        while True:
            if cancel and cancel.is_set():
                raise Cancelled()
            if time.monotonic() > deadline:
                raise TimeoutError('阶段超时；已有草稿和检查点已保留。')
            if receiver.poll(.2):
                try:
                    ok, value = receiver.recv()
                except EOFError as exc:
                    raise RuntimeError('识谱进程意外退出') from exc
                if not ok:
                    raise ValueError(value)
                return value
            if not process.is_alive():
                raise RuntimeError('识谱进程未返回结果')
    finally:
        stop_process(process)
        receiver.close()


def job_path(store, job_id):
    from app.services.revision_store import checked_id
    return store.root/'jobs'/checked_id(job_id)/'state.json'


def get_job(store, job_id):
    path = job_path(store,job_id)
    with _live_lock:
        value = read(path)
        if value is None:
            raise FileNotFoundError('任务不存在')
        if value['status'] not in TERMINAL and job_id not in _live:
            value.update(status='interrupted',message='服务已重启，可从检查点继续。')
            write(path,value)
        return value


def start(store, config, project_id, *, resume=None):
    with _live_lock, LOCK:
        store.import_legacy()
        current = store.state()
        resumed = get_job(store,resume) if resume else None
        allowed = (resumed['base_revision'],resumed.get('revision')) if resumed else (config.base_revision,)
        if current['active_revision'] not in allowed:
            raise ValueError('活动版本已更新，请刷新后开始，避免覆盖人工修改。')
        project = storage.read_config(project_id)
        if config.source == 'video' and (not project.source_video or not config.roi):
            raise ValueError('请先导入视频并选择谱面区域。')
        if config.source == 'pdf':
            from app.services.revision_store import checked_id
            pdf = store.root/'inputs'/checked_id(config.input_id or '')/'source.pdf'
            if not pdf.exists():
                raise ValueError('请先导入 PDF。')
        if config.source == 'existing' and not read(store.directory/'manifest.json',{}).get('rows'):
            raise ValueError('没有旧谱行；请导入视频或 PDF。')
        payload = config.model_dump(mode='json')
        # Include material/config fingerprint, not only UI values.
        from app.services.recognition_cache import file_hash
        material = file_hash(Path(project.source_video)) if config.source == 'video' else (
            file_hash(pdf) if config.source == 'pdf' else digest([
                read(store.directory/'manifest.json',{}),
                [(r['id'],file_hash(store.directory/'rows'/r['id']))
                 for r in read(store.directory/'manifest.json',{}).get('rows',[])]]))
        key = digest([payload,material,project.processing.model_dump(mode='json')])
        input_key = digest([material,config.source,config.roi.model_dump() if config.roi else None,
                            config.layout,project.processing.model_dump(mode='json'),config.tuning])
        latest = get_job(store,current['latest_job']) if current.get('latest_job') else None
        if latest and latest['status'] not in TERMINAL and latest['key']==key:
            return latest
        if not project_guard.acquire(project_id,'conversion'):
            raise ValueError('本项目已有处理任务，请等待或取消后重试。')
        job_id = uuid.uuid4().hex
        cancel = threading.Event()
        job = dict(id=job_id,key=key,material_key=input_key,config=payload,project_config=project.model_dump(mode='json'),
            status='queued',stage='prepare',current=0,total=0,created_at=stamp(),
            message='任务已排队',log=[],elapsed_seconds=0,cache_hits=0,artifact=None,
            revision=None,base_revision=config.base_revision,activation_expected=current['active_revision'],resume_from=resume)
        if resume:
            old = get_job(store,resume)
            if old['key'] != key:
                project_guard.release(project_id)
                raise ValueError('输入或参数已改变，请开始新任务。')
            job['resume_from'] = resume
        write(job_path(store,job_id),job)
        store.update(latest_job=job_id)
        _live[job_id]=cancel
        thread=threading.Thread(target=run,args=(store,project_id,job,cancel),daemon=True)
        thread.start()
        return job


def cancel_job(store, job_id):
    with _live_lock:
        job=get_job(store,job_id)
        if job['status'] not in TERMINAL:
            _live[job_id].set()
            job.update(status='cancelling',message='正在停止当前工作；已有草稿保留。')
            write(job_path(store,job_id),job)
        return job


def publish(store, job, score, manifest, origin):
    """CAS active pointer; a manual save during a run always wins."""
    with LOCK:
        revision=store.create(score,origin=origin,parent=job['base_revision'],
            input_id=job.get('input_key'),manifest=manifest)
        base = store.get(job['base_revision']) if job['base_revision'] else None
        separate = base and base['protected'] and base.get('input_id') != job.get('input_key')
        if not separate and store.state()['active_revision'] in (job.get('activation_expected',job['base_revision']),job.get('revision')):
            store.update(active_revision=revision['id'])
        job['revision']=revision['id']
        return revision


def make_artifact(store, revision):
    from app.services.draft_artifact import export_partial
    identifier=uuid.uuid4().hex
    directory=store.root/'artifacts'/identifier
    directory.mkdir(parents=True)
    report=export_partial(Score.model_validate(revision['score']),directory/'draft.gp5')
    value=dict(id=identifier,revision=revision['id'],created_at=stamp(),report=report,
        url=f'/artifacts/{identifier}/download',issues_url=f'/artifacts/{identifier}/issues')
    write(directory/'manifest.json',value)
    return value


def run(store, project_id, job, cancel):
    from app.services.recognition_cache import reader_signature, file_hash, cache_key, load_result, store_result
    from app.services.score_exporter import validate_score
    started=time.monotonic()
    stage_started=started
    reader=None
    work=job_path(store,job['id']).parent
    def update(stage=None,message=None,**values):
        nonlocal stage_started
        if cancel.is_set():
            raise Cancelled()
        if stage and stage!=job['stage']:
            job.setdefault('stage_seconds',{})[job['stage']]=round(time.monotonic()-stage_started,2)
            stage_started=time.monotonic()
            job['stage']=stage
        if message:
            job['message']=message
            job['log'].append(message)
        job.update(values,elapsed_seconds=round(time.monotonic()-started,2),status='running')
        write(job_path(store,job['id']),job)
    def call(module,function,args,timeout=180,kwargs=None):
        return bounded(module,function,args,kwargs=kwargs,cancel=cancel,timeout=timeout)
    def artifact(score,manifest,origin):
        if score.measures:
            revision=publish(store,job,score,manifest,origin)
            job['artifact']=make_artifact(store,revision)
            write(job_path(store,job['id']),job)
    config=job['config']
    base=store.get(job['base_revision']) if job['base_revision'] else None
    score=Score.model_validate(base['score']) if base else Score(tempo=config['tempo'],tuning=config['tuning'])
    if score.tempo!=config['tempo'] or score.tuning!=config['tuning']:
        score.settings_confirmed=False
    score.tempo=config['tempo'];score.tuning=config['tuning']
    # Every prior manual or imported measure is protected conservatively.
    protected={(m['source'],m['number']) for m in (base or {}).get('entities',[])
               if m['id'] in (base or {}).get('protected',[])}
    try:
        update('prepare','正在准备谱面与来源快照')
        input_key=digest([job['material_key'],reader_signature()])
        job['input_key']=input_key
        prepared=store.root/'prepared'/input_key
        manifest=read(prepared/'manifest.json')
        if manifest and not config['force']:
            job['cache_hits']+=1
        else:
            if config['source']=='pdf':
                paths=call('app.services.conversion_workers','prepare_pdf',
                    (store.root/'inputs'/config['input_id']/'source.pdf',prepared/'pages',config['roi']))
            elif config['source']=='video':
                project=job['project_config']
                paths=call('app.services.conversion_workers','video_crops',
                    (project['source_video'],project['processing'],config['roi'],prepared),timeout=600)
            else:
                manifest=read(store.directory/'manifest.json')
                if any(r.get('layout','tab')!=config['layout'] for r in manifest['rows']):
                    raise ValueError('旧谱行类型不同，请重新导入素材以避免误用。')
                (prepared/'rows').mkdir(parents=True,exist_ok=True)
                for row in manifest['rows']:
                    shutil.copy2(store.directory/'rows'/row['id'],prepared/'rows'/row['id'])
                paths=None
            if paths is not None:
                manifest=call('app.services.conversion_workers','prepare_rows',
                    (paths,prepared/'rows',config['layout'],config['source']=='video')
                    + ((5,) if len(config['tuning']) == 5 else ()))
                if config['source']=='video':
                    sources=read(prepared/'video-sources.json',{})
                    for row in manifest['rows']:
                        reference=sources.get(row['source'])
                        if reference:
                            row['video_source']=reference
                            row['source']=f"视频约 {reference['time_estimate']:.1f} 秒 · {reference['frame']}"
            write(prepared/'manifest.json',manifest)
        manifest={**manifest,'input_key':input_key}
        rows=[r for r in manifest['rows'] if not r.get('excluded')]
        if not rows:raise ValueError('没有检测到谱行，请检查区域和谱面类型。')
        # New input is an independent result; retain only matching protected data.
        old_score=score.model_copy(deep=True)
        score.measures=[]
        checkpoint=read(work/'checkpoint.json')
        if not checkpoint and job.get('resume_from'):
            checkpoint=read(job_path(store,job['resume_from']).parent/'checkpoint.json')
        completed=set(checkpoint.get('completed',[])) if checkpoint else set()
        if checkpoint:
            score=Score.model_validate(checkpoint['score'])
            manifest['unread_rows']=checkpoint.get('unread_rows',[])
            manifest['fragments']=checkpoint.get('fragments',[])
        next_number=score.measures[-1].number+1 if score.measures else 1
        previous=[n.model_dump() for n in score.measures[-1].beats[-1].notes] if score.measures and score.measures[-1].beats else []
        reading=RecognitionConfig(layout=config['layout'],max_rows=200,force=config['force'],model='',strategy='hybrid')
        for index,row in enumerate(rows):
            update('read',f'读取谱行 {index+1}/{len(rows)}',current=index,total=len(rows))
            if row['id'] in completed:continue
            existing=[m for m in old_score.measures if m.source==row['id'] and (m.source,m.number) in protected]
            printed=row.get('measure_numbers',[])
            start_number=printed[0] if config['source']=='video' and printed else next_number
            previous_measure=next((m for m in reversed(score.measures) if m.number==start_number-1),None)
            previous=[n.model_dump() for n in previous_measure.beats[-1].notes] if previous_measure and previous_measure.beats else []
            context={**row,'start_number':start_number,'previous_notes':previous}
            key=cache_key(prepared/'rows'/row['id'],context,score.tuning)
            result=load_result(store.root/'cache',key) if key and not config['force'] else None
            if result:
                job['cache_hits']+=1
            else:
                try:
                    if reader is None:reader=ReaderSession()
                    result=reader.call('app.services.tab_recognizer','recognize_row',
                        (prepared/'rows'/row['id'],context,reading,score.tuning),cancel=cancel,timeout=180)
                    if key:store_result(store.root/'cache',key,result)
                except (ValueError,TimeoutError) as exc:
                    if reader:reader.close();reader=None
                    result=RecognitionResult(measures=[],warnings=[str(exc)])
            # A changed input cannot prove correspondence to protected old rows.
            # Keep prior manual versions independent instead of merging by row name alone.
            same_input=base and base.get('input_id')==input_key
            if existing and same_input:
                result.measures=[m for m in result.measures if (row['id'],m.number) not in protected]
                result.measures.extend(existing)
                result.measures.sort(key=lambda m:m.number)
            for measure in result.measures:
                measure.source=row['id']
                if config['source']=='video' and not printed:
                    measure.issues.append('视频画面缺少可靠印刷编号；顺序仅为候选，请核对重复或遗漏。')
            for fragment in result.fragments:
                manifest.setdefault('fragments',[]).append(dict(row=row['id'],**fragment.model_dump()))
            if not result.measures:
                manifest.setdefault('unread_rows',[]).append(dict(id=row['id'],source=row.get('source'),
                    message='此谱行未读出小节，可能包含曲尾缺失内容；请查看来源。'))
            for measure in result.measures:
                def music(value):
                    return [(b.duration,b.dotted,b.triplet,[(n.string,n.fret,n.kind) for n in b.notes]) for b in value.beats]
                repeated=next((m for m in score.measures if m.number==measure.number and music(m)==music(measure)),None)
                if repeated:
                    manifest.setdefault('duplicate_sources',[]).append(dict(number=measure.number,
                        kept=repeated.source,alternate=measure.source))
                else:
                    score.measures.append(measure)
            score.measures.sort(key=lambda m:m.number)
            if result.measures:
                next_number=max(m.number for m in score.measures)+1
                previous=[n.model_dump() for n in result.measures[-1].beats[-1].notes] if result.measures[-1].beats else []
            job['log'].extend(result.warnings)
            completed.add(row['id'])
            write(work/'checkpoint.json',dict(score=score.model_dump(),completed=sorted(completed),
                unread_rows=manifest.get('unread_rows',[]),fragments=manifest.get('fragments',[])))
        # Keep visible edge candidates without claiming a complete bar.
        from app.models.score import TabMeasure
        complete_numbers={m.number for m in score.measures}
        candidates={}
        for fragment in manifest.get('fragments',[]):
            value=fragment['measure']
            if value['number'] not in complete_numbers and any(b['notes'] for b in value['beats']):
                candidates.setdefault(value['number'],[]).append(fragment)
        for number,parts in candidates.items():
            selected=max(parts,key=lambda f:sum(len(b['notes']) for b in f['measure']['beats']))
            measure=TabMeasure.model_validate(selected['measure'])
            measure.source=selected['row']
            measure.issues.append('边缘片段候选：覆盖范围未确认；其他片段保存在版本记录。')
            measure.beats[0].unresolved=sorted(set(measure.beats[0].unresolved+['duration']))
            score.measures.append(measure)
        score.measures.sort(key=lambda m:m.number)
        update('validate','本地识别完成，正在准备基础草稿',current=len(rows))
        artifact(score,manifest,'local-read')
        update('recover','正在检查需要补读的小节')
        protected_numbers={n for _,n in protected} if base and base.get('input_id')==input_key else set()
        targets={i['measure'] for i in validate_score(score,require_review=False) if i['severity']=='error' and i['measure']}
        if score.measures:
            targets.update(set(range(1,max(m.number for m in score.measures)+1))-{m.number for m in score.measures})
        targets-=protected_numbers
        if config['recover'] and config['source']=='video' and targets and config['layout']=='standard-tab':
            frames=sorted((prepared/'frames').glob('*.jpg'))
            if frames:
                try:
                    recovered,evidence=call('app.services.conversion_workers','recover',
                        (score,sorted(targets),frames,config['roi'],work/'recovery'),timeout=300)
                    write(work/'recovery-log.json',evidence)
                    if evidence:
                        score=recovered
                        artifact(score,manifest,'video-recovery')
                except (ValueError,TimeoutError) as exc:
                    job['log'].append(f'补读未完成：{exc}')
        update('review','正在复核剩余疑点' if config['review'] and config['model'] else '未启用模型复核，保留本地结果')
        review_config=RecognitionConfig(layout=config['layout'],model=config['model'],provider=config['provider'],base_url=config['base_url'])
        deadline=time.monotonic()+config['budget_seconds']
        patches=[]
        if config['review'] and config['model'] and config['layout']=='standard-tab':
            from app.services.local_review import targets_for
            for i,measure in enumerate(score.measures):
                if measure.number in protected_numbers or not targets_for(measure):continue
                if time.monotonic()>=deadline:
                    job['log'].append('复核预算已用完，疑点保留。');break
                row=next((r for r in rows if r['id']==measure.source),None)
                if not row:continue
                update(message=f'局部复核第 {measure.number} 小节')
                prior=[n.model_dump() for n in score.measures[i-1].beats[-1].notes] if i and score.measures[i-1].beats else []
                try:
                    review_key=digest([input_key,row,measure.model_dump(),review_config.model_dump(),prior])
                    cached=read(store.root/'review-cache'/f'{review_key}.json') if not config['force'] else None
                    if cached:
                        from app.models.score import TabMeasure
                        candidate=TabMeasure.model_validate(cached['measure']);logs=cached['log'];job['cache_hits']+=1
                    else:
                        candidate,logs=call('app.services.conversion_workers','review_one',
                            (prepared/'rows'/row['id'],row,measure,review_config,score.tuning,prior,work/f'review-{i}.png'),
                            timeout=min(90,max(1,deadline-time.monotonic())))
                        write(store.root/'review-cache'/f'{review_key}.json',dict(measure=candidate.model_dump(),log=logs))
                    if candidate.model_dump()!=measure.model_dump():
                        patches.append(dict(number=measure.number,before=measure.model_dump(),after=candidate.model_dump(),evidence=logs))
                        score.measures[i]=candidate
                    job['log'].extend(logs)
                except (ValueError,TimeoutError) as exc:
                    job['log'].append(f'第 {measure.number} 小节未接受修改：{exc}')
        if patches:
            write(work/'patches.json',patches)
            artifact(score,manifest,'local-review')
        update('export','草稿与疑点报告已生成')
        if not job['artifact']:raise ValueError('没有可用音符，无法生成 GP5；请检查来源与区域。')
        job.update(status='completed',message='草稿已就绪；疑点不影响下载。')
    except Cancelled:
        job.update(status='cancelled',message='已取消；已生成的草稿和检查点保留。')
    except Exception as exc:
        job.update(status='partial' if job['artifact'] else 'failed',message=str(exc)[:600])
        job['log'].append(job['message'])
    finally:
        if reader:reader.close()
        job.setdefault('stage_seconds',{})[job['stage']]=round(time.monotonic()-stage_started,2)
        job['elapsed_seconds']=round(time.monotonic()-started,2)
        write(job_path(store,job['id']),job)
        project_guard.release(project_id)
        with _live_lock:
            _live.pop(job['id'],None)
