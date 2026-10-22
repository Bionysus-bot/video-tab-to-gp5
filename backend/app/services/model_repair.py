"""Bounded model correction of existing combined measures; never invent missing bars."""
from pathlib import Path
import tempfile

import httpx
import cv2
import numpy as np

from app.models.score import RecognitionResult, Score
from app.services.combined_tab import measure_image, measure_regions
from app.services.image_io import imread, imwrite
from app.services.recognition_cache import cache_key, load_result, store_result
from app.services.score_exporter import validate_score


def measure_errors(measure, tuning, previous):
    sample = measure.model_copy(deep=True)
    # Validate ties against the actual preceding beat, including the row boundary.
    errors = []
    for beat in sample.beats:
        for note in beat.notes:
            if note.kind == 'tie':
                if not any(n['string'] == note.string and n['fret'] == note.fret for n in previous):
                    errors.append('延音音符与上一拍不对应')
                note.kind = 'normal'
        previous = [n.model_dump() for n in beat.notes if n.kind != 'dead']
    errors.extend(i['message'] for i in validate_score(
        Score(settings_confirmed=True, tuning=tuning, measures=[sample]), require_review=False)
        if i['severity'] == 'error')
    return errors


def repair_combined(path, row, config, tuning, existing, recognize, *, on_progress=None,
                    cache_directory=None):
    result = RecognitionResult(measures=[m.model_copy(deep=True) for m in existing])
    image=imread(path)
    if image is None:raise ValueError('无法读取联合谱图片')
    regions = measure_regions(row)
    if existing and len(existing)==len(regions)+1 and any('行末右侧边界未检出' in text for text in existing[-1].issues):
        regions.append((regions[-1][1],image.shape[1]))
    if not row.get('notation_lines') or len(regions) != len(existing):
        result.warnings.append('模型修复未执行：现有小节与完整裁图数量不对应；请先更新谱行并重新识别。')
        return result
    previous = row.get('previous_notes', [])
    evidence={}
    if config.local_review:
        from app.services.combined_local import read_combined_local
        read_combined_local(path,row,tuning,evidence)
    previous_number = int(row.get('start_number', 1)) - 1
    with tempfile.TemporaryDirectory(prefix='.repair-', dir=Path(path).parent) as temporary:
        for index, (measure, bounds) in enumerate(zip(result.measures, regions)):
            errors = measure_errors(measure, tuning, previous)
            if measure.number != previous_number + 1:
                errors.append('小节编号与前一小节不连续，请从图片读取实际编号，不可随意补号')
            if errors:
                crop, metadata = measure_image(image, row, bounds)
                metadata.update(start_number=measure.number, previous_notes=previous,
                                repair_candidate=measure.model_dump(exclude={'source', 'reviewed'}),
                                repair_errors=errors)
                target = Path(temporary) / f'repair-{index}.png'
                imwrite(target, crop)
                if config.local_review:
                    from app.services.local_review import review_measure
                    from app.services.local_review import targets_for
                    try:
                        focus_path=None
                        positions=[e['x'] for e in evidence.get('events',[]) if e['measure']==measure.number
                                   and e['beat_index'] in targets_for(measure)]
                        if positions:
                            margin=float(np.median(np.diff(row['lines'])))*2
                            strip=image[:,max(0,round(min(positions)-margin)):min(image.shape[1],round(max(positions)+margin))]
                            if strip.size:
                                focus_path=Path(temporary)/f'focus-{index}.png'
                                imwrite(focus_path,cv2.resize(strip,None,fx=3,fy=3,interpolation=cv2.INTER_CUBIC))
                        candidate,logs=review_measure(target,Path(path),measure,config,tuning,previous,focus_path=focus_path)
                        if logs:
                            candidate.source=row['id'];result.measures[index]=measure=candidate
                            result.warnings.extend(logs)
                        else:result.warnings.append(f'第{measure.number}小节：局部模型没有提供可接受的修改，保留原数据。')
                    except (ValueError,httpx.HTTPError) as exc:
                        result.warnings.append(f'第{measure.number}小节局部复核失败，原数据保留：{str(exc)[:180]}')
                    previous=[n.model_dump() for n in measure.beats[-1].notes] if measure.beats else []
                    previous_number=measure.number
                    continue
                accepted = False
                for attempt in range(2):
                    context = {**metadata, 'engine': 'model-repair-v1', 'model': config.model,
                               'provider': config.provider, 'base_url': config.base_url}
                    key = cache_key(target, context, tuning) if cache_directory else None
                    try:
                        part = load_result(cache_directory, key) if key and not config.force else None
                        if part is None:
                            part = recognize(target, metadata, config.model_copy(update={'strategy': 'vision', 'layout': 'tab'}),
                                             tuning, on_progress=on_progress)
                        if len(part.measures) != 1:
                            raise ValueError('模型没有返回恰好一个小节')
                        candidate = part.measures[0]
                        remaining = measure_errors(candidate, tuning, previous)
                        if candidate.number != measure.number:
                            remaining.append('模型改变了小节编号，保留原编号以免破坏顺序；跨行残缺另行处理')
                        if remaining:
                            metadata.update(repair_candidate=candidate.model_dump(exclude={'source', 'reviewed'}),
                                            repair_errors=remaining)
                            raise ValueError('；'.join(remaining))
                        candidate.source = row['id']
                        candidate.reviewed = False
                        candidate.issues.append('已由视觉模型复读并通过结构校验；音符准确性仍需在 Guitar Pro 核对。')
                        if key:
                            store_result(cache_directory, key, RecognitionResult(measures=[candidate]))
                        result.measures[index] = measure = candidate
                        result.warnings.append(f'第 {measure.number} 小节：模型修复通过（第 {attempt + 1} 次）。')
                        accepted = True
                        break
                    except (ValueError, httpx.HTTPError) as exc:
                        result.warnings.append(f'第 {measure.number} 小节模型复核第 {attempt + 1} 次未通过：{str(exc)[:180]}')
                if not accepted:
                    result.warnings.append(f'第 {measure.number} 小节：保留修复前数据，未自动放行导出。')
            previous = [n.model_dump() for n in measure.beats[-1].notes] if measure.beats else []
            previous_number = measure.number
    return result
