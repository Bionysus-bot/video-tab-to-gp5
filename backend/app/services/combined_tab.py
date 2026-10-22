"""Separate vision path for notation above TAB; the original TAB reader is unchanged."""
from fractions import Fraction
from pathlib import Path
import tempfile

import cv2
import numpy as np

from app.models.score import RecognitionResult
from app.services.image_io import imread, imwrite


def measure_regions(row: dict) -> list[tuple[int, int]]:
    spacing = float(np.median(np.diff(row['lines'])))
    clusters = []
    for x in sorted(set(row['bars'])):
        if clusters and x - clusters[-1][-1] <= spacing * .9:
            clusters[-1].append(x)
        else:
            clusters.append([x])
    bars = [round(float(np.mean(cluster))) for cluster in clusters]
    # Do not use the image edge as an invented barline. Narrow clef strokes
    # and double end-bar strokes do not define extra measures.
    return [(left, right) for left, right in zip(bars, bars[1:]) if right - left >= spacing * 5]


def measure_image(image, row, bounds):
    left, right = bounds
    margin = max(3, round(float(np.median(np.diff(row['lines']))) * .6))
    x0, x1 = max(0, left - margin), min(image.shape[1], right + margin + 1)
    scale = max(1, min(4, 28 / float(np.median(np.diff(row['lines'])))))
    crop = cv2.resize(image[:, x0:x1], None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    metadata = {**row, 'layout': 'standard-tab-measure', 'complete_measure': True,
                'lines': [round(y * scale) for y in row['lines']],
                'notation_lines': [round(y * scale) for y in row['notation_lines']],
                'bars': [round((x - x0) * scale) for x in bounds],
                'width': crop.shape[1], 'height': crop.shape[0]}
    return crop, metadata


def check_vision_measure(measure):
    total = sum((Fraction(1, beat.duration) * (Fraction(3, 2) if beat.dotted else 1)
                 * (Fraction(2, 3) if beat.triplet else 1) for beat in measure.beats), Fraction(0))
    expected = Fraction(measure.numerator, measure.denominator)
    if total != expected:
        for beat in measure.beats:
            if 'duration' not in beat.unresolved:
                beat.unresolved.append('duration')
        measure.issues.append('视觉模型返回的拍数与拍号不符，保留原结果供修正；未自动补拍。')
    if 'confidence' not in measure.model_fields_set:
        measure.issues.append('视觉模型未提供识别置信度，请对照原图核对。')
    measure.reviewed = False


def recognize_combined(path, row, config, tuning, recognize, client=None, on_progress=None):
    if not row.get('notation_lines'):
        raise ValueError('五线谱＋TAB 需要完整上方五线谱，请先点击“更新谱行图片”并选择正确谱面类型。')
    if not config.model.strip():
        raise ValueError('五线谱＋TAB 使用独立的逐小节视觉识别，请选择支持图片的视觉模型。')
    image = imread(path)
    if image is None:
        raise ValueError('无法读取五线谱＋TAB 图片')
    regions = measure_regions(row)
    if not regions:
        raise ValueError('未找到由两条小节线围成的完整小节，请检查原图。')
    result = RecognitionResult(measures=[], warnings=['使用五线谱＋TAB 专用流程：上方读取节奏，下方读取弦号和品位，逐小节识别；两侧残缺小节不补拍。'])
    number = int(row.get('start_number', 1))
    offset = 0
    with tempfile.TemporaryDirectory(prefix='.vision-', dir=Path(path).parent) as temporary:
        for index, bounds in enumerate(regions):
            crop, metadata = measure_image(image, row, bounds)
            metadata.update(start_number=number, previous_notes=row.get('previous_notes', []) if not result.measures
                            else [note.model_dump() for note in result.measures[-1].beats[-1].notes])
            target = Path(temporary) / f'measure-{index + 1}.png'
            imwrite(target, crop)
            size = 0
            def progress(current, part):
                nonlocal size
                size = current
                if on_progress:
                    on_progress(offset + current, part)
            part = recognize(target, metadata, config.model_copy(update={'layout': 'tab', 'strategy': 'vision'}),
                             tuning, client=client, on_progress=progress)
            offset += size
            if len(part.measures) != 1:
                result.warnings.append(f'本行第 {index + 1} 个完整小节：模型返回 {len(part.measures)} 小节，未接受，请核对原图。')
                number += 1
                result.warnings.extend(part.warnings)
                continue
            measure = part.measures[0]
            check_vision_measure(measure)
            measure.source = row['id']
            result.measures.append(measure)
            number = measure.number + 1
            result.warnings.extend(part.warnings)
    return result
