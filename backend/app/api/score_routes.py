import json
import hashlib
import re
import shutil
import tempfile
import threading
import time
import uuid
from pathlib import Path

import httpx
from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import FileResponse

from app.models.score import ImagePreparationConfig, RecognitionConfig, RecognitionResult, RowExclusion, Score
from app.services.score_exporter import export_gp5, validate_score
from app.services.score_images import prepare_images
from app.services.tab_recognizer import ollama_models, recognize_row
from app.storage import manager as storage

router = APIRouter()
_guard = threading.Lock()
_json_lock = threading.RLock()
_busy = set()


def root(project_id: str) -> Path:
    if not re.fullmatch(r"[a-f0-9]{12}", project_id) or storage.read_config(project_id) is None:
        raise HTTPException(404, "项目不存在")
    directory = storage.output_path(project_id, "score")
    directory.mkdir(exist_ok=True)
    return directory


def write_json(path: Path, data):
    temporary = path.with_suffix(".tmp")
    encoded = json.dumps(data, ensure_ascii=False, indent=2)
    # Windows readers can briefly deny replacement of an open file. Keep our
    # readers and writers synchronized, with bounded retries for other readers.
    with _json_lock:
        try:
            temporary.write_text(encoded, encoding="utf-8")
            for attempt in range(6):
                try:
                    temporary.replace(path)
                    break
                except PermissionError:
                    if attempt == 5:
                        raise
                    time.sleep(.01 * 2 ** attempt)
        finally:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass


def read_json(path: Path, default=None):
    with _json_lock:
        encoded = path.read_text(encoding="utf-8") if path.exists() else None
    return json.loads(encoded) if encoded is not None else default


def acquire(project_id):
    with _guard:
        if project_id in _busy:
            raise HTTPException(409, "识谱任务进行中，请等待完成")
        _busy.add(project_id)


def release(project_id):
    with _guard:
        _busy.discard(project_id)


@router.get("/score/models")
def models():
    try:
        return {"models": ollama_models(), "error": ""}
    except (httpx.HTTPError, ValueError, KeyError):
        return {"models": [], "error": "无法读取 Ollama 模型，请打开 Ollama 并确认本机 11434 端口可用"}


def prepare(project_id, directory, inputs, layout='auto'):
    # A new source invalidates the old transcription immediately.
    write_json(directory / "score.json", Score().model_dump())
    write_json(directory / "task.json", {"status": "preparing", "log": []})
    try:
        manifest = prepare_images(inputs, directory / "rows", layout=layout)
        write_json(directory / "manifest.json", manifest)
        write_json(directory / "task.json", {"status": "idle", "log": []})
        return manifest
    except Exception:
        write_json(directory / "manifest.json", {"rows": [], "rejected": []})
        write_json(directory / "task.json", {"status": "failed", "log": ["图片准备失败，请检查输入文件"]})
        raise


@router.post("/projects/{project_id}/score/pdf")
def upload_pdf(project_id: str, file: UploadFile = File(...), layout: str = 'auto'):
    layout = ImagePreparationConfig(layout=layout).layout
    directory = root(project_id)
    acquire(project_id)
    try:
        content = file.file.read(50 * 1024 * 1024 + 1)
        if len(content) > 50 * 1024 * 1024 or not content.startswith(b"%PDF-"):
            raise HTTPException(400, "请上传不超过 50MB 的有效 PDF")
        path = directory / "input.pdf"
        path.write_bytes(content)
        return prepare(project_id, directory, [path], layout)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    finally:
        release(project_id)


@router.post("/projects/{project_id}/score/prepare")
def prepare_crops(project_id: str, layout: str = 'auto'):
    layout = ImagePreparationConfig(layout=layout).layout
    directory = root(project_id)
    acquire(project_id)
    try:
        inputs = sorted(path for path in storage.crops_dir(project_id).iterdir()
                        if path.suffix.lower() in (".png", ".jpg", ".jpeg"))
        if not inputs:
            raise HTTPException(400, "没有视频截图，请先处理视频或导入 PDF")
        return prepare(project_id, directory, inputs, layout)
    finally:
        release(project_id)


@router.post('/projects/{project_id}/score/refresh-images')
def refresh_images(project_id: str, config: ImagePreparationConfig):
    """Re-crop the same input while preserving transcription and review state."""
    directory = root(project_id)
    acquire(project_id)
    try:
        old = read_json(directory / 'manifest.json', {'rows': [], 'rejected': []})
        score = Score.model_validate(read_json(directory / 'score.json', Score().model_dump()))
        if any('source_row' not in row for row in old['rows']) and score.measures:
            raise HTTPException(409, '旧谱行缺少原始位置，无法安全对应已校对内容；请备份后在另一项目重新导入。')
        is_pdf = old['rows'] and all(row['source'].startswith('PDF 第 ') for row in old['rows'])
        inputs = [directory / 'input.pdf'] if is_pdf else sorted(
            path for path in storage.crops_dir(project_id).iterdir() if path.suffix.lower() in ('.png', '.jpg', '.jpeg'))
        if not inputs or any(not path.is_file() for path in inputs):
            raise HTTPException(400, '原始输入不存在，请重新导入 PDF 或读取视频截图。')
        old_keys = {(row['source'], row.get('source_row')): row for row in old['rows']}
        with tempfile.TemporaryDirectory(prefix='.refresh-', dir=directory) as temporary:
            staged = Path(temporary)
            manifest = prepare_images(inputs, staged, layout=config.layout)
            mapping = {}
            pending = []
            for row in manifest['rows']:
                original = old_keys.get((row['source'], row['source_row']))
                image = staged / row['id']
                suffix = hashlib.sha256(image.read_bytes()).hexdigest()[:12]
                row['id'] = f"{image.stem}_{suffix}.png"
                pending.append((image, directory / 'rows' / row['id']))
                if original:
                    mapping[original['id']] = row['id']
                    for field in ('excluded', 'exclude_reason'):
                        if field in original:
                            row[field] = original[field]
            if any(measure.source not in mapping for measure in score.measures):
                raise HTTPException(409, '新裁图无法对应部分已有小节，原数据保持不变；请检查谱面类型或在另一项目导入。')
            snapshot = directory / 'backups' / ('images-' + uuid.uuid4().hex)
            snapshot.mkdir(parents=True)
            write_json(snapshot / 'manifest.json', old)
            write_json(snapshot / 'score.json', score.model_dump())
            # Keep old images in place so each snapshot remains recoverable.
            for image, target in pending:
                if not target.exists():
                    shutil.copy2(image, target)
            for measure in score.measures:
                measure.source = mapping[measure.source]
            task = read_json(directory / 'task.json', {'status': 'idle', 'log': []})
            task['log'].append(f'已更新完整谱行图片；保留 {len(score.measures)} 个已有小节及其核对标记。错误的已核对内容需先取消核对再重新识别。')
            with _json_lock:
                write_json(directory / 'score.json', score.model_dump())
                write_json(directory / 'manifest.json', manifest)
                write_json(directory / 'task.json', task)
            return manifest
    finally:
        release(project_id)


@router.get("/projects/{project_id}/score")
def get_score(project_id: str):
    directory = root(project_id)
    score = Score.model_validate(read_json(directory / "score.json", Score().model_dump()))
    with _guard:
        task = read_json(directory / "task.json", {"status": "idle", "log": []})
        if project_id not in _busy and task["status"] in ("recognizing", "preparing"):
            task["status"] = "failed"
            task["log"].append("服务曾重启，任务已中断。已完成的数据保留，请重试。")
            write_json(directory / "task.json", task)
    return {"score": score, "validation": validate_score(score),
            "draft_validation": validate_score(score,require_review=False),
            "manifest": read_json(directory / "manifest.json", {"rows": [], "rejected": []}),
            "task": task}


@router.put("/projects/{project_id}/score")
def save_score(project_id: str, score: Score):
    directory = root(project_id)
    acquire(project_id)
    try:
        write_json(directory / "score.json", score.model_dump())
        return {"validation": validate_score(score)}
    finally:
        release(project_id)


def run_recognition(project_id, directory, config, manifest, score):
    started = time.perf_counter()
    task = {"status": "recognizing", "current": 0, "total": min(config.max_rows, len(manifest["rows"])),
            "cache_hits": 0, "elapsed_seconds": 0, "log": []}
    recognized_count = 0
    next_number = 1
    previous_notes = []
    processed_sources = set()
    try:
        rows = manifest["rows"][:config.max_rows]
        # Checkpoints are row-scoped. A retry replaces only that row's measures.
        for index, row in enumerate(rows):
            row_started = time.perf_counter()
            cache_hit = False
            task["current"] = index + 1
            write_json(directory / "task.json", task)
            if row.get('excluded'):
                if any(m.reviewed for m in score.measures if m.source==row['id']):
                    raise ValueError('被跳过的谱行仍有已核对小节，请先恢复该行或取消核对标记。')
                score.measures=[m for m in score.measures if m.source!=row['id']]
                write_json(directory/'score.json',score.model_dump())
                task['log'].append(f"{row['id']}：已跳过（{row.get('exclude_reason','手动排除')}）；原图保留")
                continue
            def progress(size, _part):
                if size // 250 != task.get("generated_chars", 0) // 250:
                    task["generated_chars"] = size
                    write_json(directory / "task.json", task)
            task["generated_chars"] = 0
            context_row = {**row, 'start_number': next_number, 'previous_notes': previous_notes}
            existing = sorted([m for m in score.measures if m.source == row['id']], key=lambda m:m.number)
            if any(m.reviewed for m in existing):
                # Preserve human corrections, including a partly reviewed row.
                # Unchecking that row's reviews explicitly allows a fresh read.
                result = RecognitionResult(measures=[m.model_copy(deep=True) for m in existing],
                                           warnings=['此行已有人工核对内容，整行已保留；如需重识别，请先取消该行的核对标记。'])
            else:
                def mark_cache_hit():
                    nonlocal cache_hit
                    cache_hit = True
                result = recognize_row(directory / "rows" / row["id"], context_row, config, score.tuning,
                                       on_progress=progress, cache_directory=directory / 'cache/local-tab',
                                       on_cache_hit=mark_cache_hit)
                if cache_hit:
                    task['cache_hits'] += 1
            if result.measures:
                next_number = result.measures[-1].number + 1
                previous_notes = [note.model_dump() for note in result.measures[-1].beats[-1].notes] if result.measures[-1].beats else []
            recognized_count += len(result.measures)
            write_json(directory / f"{row['id']}.json", result.model_dump())
            score.measures = [m for m in score.measures if m.source != row["id"]]
            for measure in result.measures:
                overlaps = [m for m in score.measures if m.number == measure.number and m.source in processed_sources]
                if overlaps:
                    # Keep both conflicting interpretations for manual correction.
                    old = overlaps[0].model_dump(exclude={"source", "reviewed", "confidence", "issues"})
                    new = measure.model_dump(exclude={"source", "reviewed", "confidence", "issues"})
                    if old == new:
                        continue
                    measure.issues.append("与另一张截图中的同号小节冲突，请核对并删除错误版本")
                score.measures.append(measure)
            processed_sources.add(row['id'])
            score.measures.sort(key=lambda m: m.number)
            write_json(directory / "score.json", score.model_dump())
            reused = '（复用缓存）' if cache_hit else ''
            task["log"].append(f"{row['id']}：识别 {len(result.measures)} 小节{reused}，耗时 {time.perf_counter()-row_started:.2f} 秒")
            task["log"].extend(result.warnings)
            write_json(directory / "task.json", task)
        if recognized_count:
            task["status"] = "review"
            task["log"].append(f"本次处理前 {len(rows)}/{len(manifest['rows'])} 行；请校对，增大行数可处理后续内容")
        elif all(row.get('excluded') for row in rows):
            task['status']='review' if score.measures else 'idle'
            task['log'].append('本次所选谱行均已跳过；原图保留，可恢复后重新识谱。')
        else:
            task["status"] = "failed"
            task["log"].append("模型已正常返回，但本次没有识别出可用小节，不能生成 GP5。请对照原图检查清晰度和裁切范围，或更换识谱模型。")
    except Exception as exc:
        task["status"] = "failed"
        if isinstance(exc, httpx.HTTPError):
            task["log"].append("模型请求失败，请检查 Ollama 服务、模型名称或兼容接口配置。已完成行已保存。")
        else:
            task["log"].append(str(exc)[:700])
    finally:
        task['elapsed_seconds'] = round(time.perf_counter() - started, 3)
        task['log'].append(f"本次用时 {task['elapsed_seconds']:.2f} 秒，复用缓存 {task['cache_hits']} 行。")
        try:
            write_json(directory / "task.json", task)
        finally:
            release(project_id)


@router.post("/projects/{project_id}/score/recognize")
def recognize(project_id: str, config: RecognitionConfig):
    directory = root(project_id)
    if config.strategy == 'vision' and not config.model.strip():
        raise HTTPException(400, "请选择模型")
    acquire(project_id)
    try:
        manifest = read_json(directory / "manifest.json", {"rows": []})
        if not manifest["rows"]:
            raise HTTPException(400, "请先整理截图或导入 PDF")
        score = Score.model_validate(read_json(directory / "score.json", Score().model_dump()))
        write_json(directory / "task.json", {"status": "recognizing", "current": 0, "total": min(config.max_rows, len(manifest["rows"])), "log": []})
        threading.Thread(target=run_recognition, args=(project_id, directory, config, manifest, score), daemon=True).start()
        return {"status": "recognizing"}
    except Exception:
        release(project_id)
        raise


@router.get("/projects/{project_id}/score/rows/{filename}")
def row_image(project_id: str, filename: str):
    directory = root(project_id)
    manifest = read_json(directory / "manifest.json", {"rows": []})
    if filename not in {row["id"] for row in manifest["rows"]}:
        raise HTTPException(404, "谱面行不存在")
    return FileResponse(directory / "rows" / filename)


@router.put('/projects/{project_id}/score/rows/{filename}/exclude')
def exclude_row(project_id: str, filename: str, change: RowExclusion):
    directory=root(project_id)
    acquire(project_id)
    try:
        manifest=read_json(directory/'manifest.json',{'rows':[]})
        row=next((r for r in manifest['rows'] if r['id']==filename),None)
        if row is None:
            raise HTTPException(404,'谱面行不存在')
        score=Score.model_validate(read_json(directory/'score.json',Score().model_dump()))
        if change.excluded and any(m.reviewed for m in score.measures if m.source==filename):
            raise HTTPException(409,'此行已有核对内容，请先取消该行所有小节的核对标记。')
        row['excluded']=change.excluded
        row['exclude_reason']=change.reason.strip() or '手动标记为重复或无有效谱面'
        if change.excluded:
            score.measures=[m for m in score.measures if m.source!=filename]
        write_json(directory/'manifest.json',manifest)
        write_json(directory/'score.json',score.model_dump())
        return {'excluded':change.excluded}
    finally:
        release(project_id)


@router.post("/projects/{project_id}/score/export")
def export(project_id: str):
    directory = root(project_id)
    acquire(project_id)
    try:
        score = Score.model_validate(read_json(directory / "score.json", Score().model_dump()))
        export_gp5(score, directory / "score.gp5")
        return {"url": f"/api/projects/{project_id}/score/download"}
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    finally:
        release(project_id)


@router.get("/projects/{project_id}/score/download")
def download(project_id: str):
    # Regenerate from current data so an obsolete GP5 cannot survive a correction.
    export(project_id)
    return FileResponse(root(project_id) / "score.gp5", filename="score.gp5", media_type="application/octet-stream")


@router.post('/projects/{project_id}/score/export-draft')
def export_draft(project_id: str):
    directory=root(project_id)
    acquire(project_id)
    try:
        score=Score.model_validate(read_json(directory/'score.json',Score().model_dump()))
        draft=score.model_copy(deep=True)
        draft.title=draft.title[:92]+' - draft'
        export_gp5(draft,directory/'score-draft.gp5',require_review=False)
        return {'url':f'/api/projects/{project_id}/score/download-draft'}
    except ValueError as exc:
        raise HTTPException(422,str(exc)) from exc
    finally:
        release(project_id)


@router.get('/projects/{project_id}/score/download-draft')
def download_draft(project_id: str):
    export_draft(project_id)
    return FileResponse(root(project_id)/'score-draft.gp5',filename='score-draft.gp5',media_type='application/octet-stream')
