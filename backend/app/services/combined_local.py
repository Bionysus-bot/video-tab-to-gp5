"""Local reader for aligned standard notation above TAB, independent of TAB rhythm rules."""
import re

import cv2
import numpy as np

from app.models.score import RecognitionResult, TabBeat, TabMeasure, TabNote
from app.services.combined_tab import check_vision_measure, measure_regions
from app.services.image_io import imread
from app.services.local_tab_reader import UnsupportedTabImage, _glyphs, read_text, spans


def standard_stems(gray, staff, tab_top):
    spacing = float(np.median(np.diff(staff)))
    bottom = min(gray.shape[0], round(tab_top - spacing * 1.8))
    ink = (gray[:bottom] < 225).astype(np.uint8)
    vertical = cv2.morphologyEx(ink, cv2.MORPH_CLOSE, np.ones((3, 1), np.uint8))
    vertical = cv2.morphologyEx(vertical, cv2.MORPH_OPEN, np.ones((max(8, round(spacing * 1.6)), 1), np.uint8))
    stems = []
    for left, right in spans(np.flatnonzero(vertical.sum(0) > spacing * 1.5), 2):
        x = left + int(np.argmax(vertical[:, left:right + 1].sum(0)))
        ys = np.flatnonzero(vertical[:, x])
        if len(ys):
            stems.append(dict(x=x, top=int(ys[0]), bottom=int(ys[-1])))
    return stems


def stem_duration(gray, stem, center, spacing):
    # Down-stem heads lie to the right of the stem; up-stem heads lie to its left.
    down = center >= stem['x']
    end = stem['bottom'] if down else stem['top']
    y0, y1 = (end - round(spacing * 2.1), end + 5) if down else (end - 5, end + round(spacing * 2.1))
    counts = []
    for offset in (-.9, -.7, -.5, .5, .7, .9):
        x = stem['x'] + round(spacing * offset)
        if not 0 <= x < gray.shape[1]:
            continue
        trace = gray[max(0, y0):min(gray.shape[0], y1), x] < 130
        runs = [(a, b) for a, b in spans(np.flatnonzero(trace), 1)
                if spacing * .1 <= b - a <= spacing * .85]
        counts.append(len(runs))
    beams = max(counts, default=0)
    if beams:
        return 4 * 2 ** min(beams, 4), []
    # Only accept an unbeamed quarter when there is a visibly filled head.
    head = stem['top'] if down else stem['bottom']
    x0, x1 = max(0, round(center - spacing * .4)), min(gray.shape[1], round(center + spacing * .4))
    y0, y1 = max(0, head - 2), min(gray.shape[0], head + round(spacing * .7))
    if x1 > x0 and y1 > y0 and np.mean(gray[y0:y1, x0:x1] < 160) > .32:
        return 4, []
    return 4, ['duration']


def _printed_number(image, staff, left, right, spacing):
    top = max(0, round(staff[0] - spacing * 2.1))
    bottom = max(top + 1, round(staff[0] - spacing * .15))
    crop = image[top:bottom, max(0, left - round(spacing * 1.8)):min(right, left + round(spacing * 2.5))]
    if not crop.size:
        return None
    padded = cv2.copyMakeBorder(crop, 5, 5, 5, 5, cv2.BORDER_CONSTANT, value=(255, 255, 255))
    padded = cv2.resize(padded, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
    text, confidence = read_text([padded])[0]
    return int(text) if re.fullmatch(r'[1-9]\d{0,2}', text) and confidence >= .8 else None


def bracketed_figures(figures, image, spacing):
    removed = set()
    for index, cell in enumerate(figures):
        if not cell['text'].isdigit():
            continue
        before = [(i, other) for i, other in enumerate(figures) if not other['text']
                  and other['string'] == cell['string'] and other['w'] < spacing * .5
                  and other['h'] > cell['h'] * 1.1
                  and 0 <= cell['x'] - other['x'] - other['w'] < spacing * .4]
        after = [(i, other) for i, other in enumerate(figures) if not other['text']
                 and other['string'] == cell['string'] and other['w'] < spacing * .5
                 and other['h'] > cell['h'] * 1.1
                 and 0 <= other['x'] - cell['x'] - cell['w'] < spacing * .4]
        if before and after:
            removed.update([before[-1][0], after[0][0]])
            cell['parenthesized'] = True
    for index, cell in enumerate(figures):
        if cell['text'] or index in removed or cell['w'] < spacing * .8:
            continue
        x, y, w, h = (cell[k] for k in ('x', 'y', 'w', 'h'))
        crop = cv2.copyMakeBorder(image[max(0,y-3):y+h+3,max(0,x-3):x+w+3],
                                 5,5,5,5,cv2.BORDER_CONSTANT,value=(255,255,255))
        text, confidence = read_text([crop])[0]
        match = re.fullmatch(r'\((\d{1,2})\)', text)
        if match and int(match[1]) <= 36 and confidence >= .5:
            cell.update(text=match[1], confidence=float(confidence), parenthesized=True)
    return [cell for index, cell in enumerate(figures) if index not in removed]


def _whole_rest(gray, staff, left, right, spacing):
    # A whole-rest rectangle hangs below the second line. Half rests sit above
    # the middle line; they must not be stretched to fill the measure.
    top, bottom = max(0, staff[1] - 2), min(gray.shape[0], round(staff[1] + spacing * .85))
    region = (gray[top:bottom, left + round(spacing):right - round(spacing)] < 150).astype(np.uint8)
    if not region.size:
        return False
    _, _, stats, _ = cv2.connectedComponentsWithStats(region)
    return any(spacing * .8 < w < spacing * 2.5 and spacing * .2 < h < spacing * .8
               and area > w * h * .65 and y < spacing * .4 for _, y, w, h, area in stats[1:])


def read_combined_local(path, row, tuning):
    if len(row['lines']) != len(tuning) or len(row.get('notation_lines', [])) != 5:
        raise UnsupportedTabImage('联合谱的五线谱或弦数不完整')
    original = imread(path)
    if original is None:
        raise UnsupportedTabImage('无法读取联合谱图片')
    factor = max(1, min(4, 30 / float(np.median(np.diff(row['lines'])))))
    image = cv2.resize(original, None, fx=factor, fy=factor, interpolation=cv2.INTER_CUBIC)
    lines = [round(y * factor) for y in row['lines']]
    staff = [round(y * factor) for y in row['notation_lines']]
    tab_spacing = round(float(np.median(np.diff(lines))))
    spacing = float(np.median(np.diff(staff)))
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY).astype(np.float32)
    # This layout uses lighter digits than the original pure-TAB fixtures.
    # Its normalization is private to this reader, never to the old reader.
    normalized = np.clip((gray - 170) * 1.6 + 80, 0, 255).astype(np.uint8)
    figures, _, _ = _glyphs(cv2.cvtColor(normalized, cv2.COLOR_GRAY2BGR), normalized.astype(np.float32),
                          lines, dict(left=0, right=image.shape[1] - 1, spacing=tab_spacing))
    figures = bracketed_figures(figures, cv2.cvtColor(normalized, cv2.COLOR_GRAY2BGR), tab_spacing)
    stems = standard_stems(gray, staff, lines[0])
    result = RecognitionResult(measures=[], warnings=[
        '使用独立联合谱本地流程：TAB 数字对应上方符干和符尾；拍号暂按 4/4，需核对。两侧残缺小节未自动补齐。'])
    previous = [TabNote.model_validate(note) for note in row.get('previous_notes', [])]
    number = int(row.get('start_number', 1))
    for bounds in measure_regions(row):
        left, right = [round(x * factor) for x in bounds]
        selected = sorted((cell for cell in figures if left + 3 < cell['x_center'] < right - 3), key=lambda c: c['x_center'])
        groups = []
        for cell in selected:
            if groups and abs(cell['x_center'] - groups[-1][0]['x_center']) < tab_spacing * .3:
                groups[-1].append(cell)
            else:
                groups.append([cell])
        beats, confidences = [], []
        for group in groups:
            center = float(np.mean([cell['x_center'] for cell in group]))
            candidates = [stem for stem in stems if left + 3 < stem['x'] < right - 3
                          and abs(stem['x'] - center) < spacing * 1.1]
            unresolved = []
            if not candidates:
                duration = 4
                unresolved.append('duration')
            else:
                stem = min(candidates, key=lambda s: min(abs(s['x'] - center + spacing * .55),
                                                        abs(s['x'] - center - spacing * .55)))
                duration, unknown = stem_duration(gray, stem, center, spacing)
                unresolved.extend(unknown)
            notes = []
            for cell in group:
                if cell['text'].isdigit() and int(cell['text']) <= 36:
                    note = TabNote(string=cell['string'], fret=int(cell['text']))
                    if cell['parenthesized']:
                        if any(n.string == note.string and n.fret == note.fret for n in previous):
                            note.kind = 'tie'
                        else:
                            unresolved.append('pitch')
                    notes.append(note)
                elif cell['text'].lower() in ('x', '×'):
                    notes.append(TabNote(string=cell['string'], fret=0, kind='dead'))
                else:
                    unresolved.append('pitch')
                confidences.append(cell['confidence'])
            beats.append(TabBeat(duration=duration, notes=notes, unresolved=sorted(set(unresolved))))
            previous = notes
        if not beats:
            if _whole_rest(gray, staff, left, right, spacing):
                beats = [TabBeat(duration=1)]
                confidences = [.9]
            else:
                beats = [TabBeat(duration=4, unresolved=['pitch', 'duration'])]
                confidences = [0]
        printed = _printed_number(image, staff, left, right, spacing)
        if printed is not None and printed < number:
            printed = None
        issues = ['拍号暂按 4/4；请核对演奏法、附点、休止与反复，未通过校验时不自动补拍。']
        if printed is None:
            issues.append('小节编号暂按上下文顺序，请核对原图。')
        if confidences == [0]:
            issues.append('本小节休止或无符干音符尚未识别，占位数据不代表休止或四分时值，需修正。')
        measure = TabMeasure(number=printed or number, beats=beats, source=row['id'],
                             confidence=float(min(confidences, default=0)), issues=issues)
        # The same structural check is used for local and vision results.
        check_vision_measure(measure, '联合谱本地读取')
        result.measures.append(measure)
        number = measure.number + 1
    if not result.measures:
        raise UnsupportedTabImage('联合谱没有可读的完整小节')
    return result
