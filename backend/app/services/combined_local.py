"""Local reader for aligned standard notation above TAB, independent of TAB rhythm rules."""
import re
from collections import Counter
from fractions import Fraction

import cv2
import numpy as np

from app.models.score import RecognitionResult, TabBeat, TabMeasure, TabNote,TabFragment
from app.services.combined_tab import check_vision_measure, measure_regions
from app.services.image_io import imread
from app.services.local_tab_reader import UnsupportedTabImage, _glyphs, _text_crop, read_text, spans


def standard_stems(gray, staff, tab_top):
    spacing = float(np.median(np.diff(staff)))
    bottom = min(gray.shape[0], round(tab_top - spacing * 1.8))
    ink = (gray[:bottom] < 225).astype(np.uint8)
    ink[:max(0,round(staff[0]-spacing*3))]=0
    vertical = cv2.morphologyEx(ink, cv2.MORPH_CLOSE, np.ones((3, 1), np.uint8))
    vertical = cv2.morphologyEx(vertical, cv2.MORPH_OPEN, np.ones((max(8, round(spacing * 1.6)), 1), np.uint8))
    # Double beams can bridge neighbouring stems in the short-line mask.
    # Split those wide spans at independently visible long vertical strokes,
    # retaining the short mask for genuine short stems and clipped fragments.
    long_vertical = cv2.morphologyEx(vertical, cv2.MORPH_OPEN,
                                   np.ones((max(8, round(spacing * 2.5)), 1), np.uint8))
    stems = []
    for left, right in spans(np.flatnonzero(vertical.sum(0) > spacing * 1.5), 2):
        strong = np.flatnonzero(long_vertical[:, left:right+1].sum(0) > spacing*2.4)+left
        parts = spans(strong,2) if right-left > spacing and len(strong) else [(left,right)]
        for a,b in parts:
            x = a + int(np.argmax(vertical[:, a:b + 1].sum(0)))
            ys = np.flatnonzero(vertical[:, x])
            if len(ys):
                stems.append(dict(x=x, top=int(ys[0]), bottom=int(ys[-1])))
    return stems


def stem_duration(gray, stem, center, spacing):
    # Down-stem heads lie to the right of the stem; up-stem heads lie to its left.
    down = stem.get('down',center >= stem['x'])
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
    grouped=stem.get('beam_group',0)
    if grouped:
        beams=min(max(beams,grouped),grouped+1)
    if not beams:
        # A compact standalone flag may end before the half-space samples.
        # Require the same visible count on two nearby columns; do not count
        # the stem itself or change the duration just to satisfy the meter.
        narrow=[]
        for offset in (-.4,-.3,.3,.4):
            x=stem['x']+round(spacing*offset)
            if not 0<=x<gray.shape[1]:continue
            trace=gray[max(0,y0):min(gray.shape[0],y1),x]<130
            narrow.append(sum(spacing*.1<=b-a<=spacing*.85 for a,b in spans(np.flatnonzero(trace),1)))
        beams=1 if narrow.count(1)>=2 else 0
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
    gray = cv2.cvtColor(padded,cv2.COLOR_BGR2GRAY)
    enhanced = np.clip((gray.astype(np.float32)-180)*3.5,0,255).astype(np.uint8)
    variants = read_text([padded,cv2.cvtColor(enhanced,cv2.COLOR_GRAY2BGR)])
    valid = [(text,float(confidence)) for text,confidence in variants
             if re.fullmatch(r'[1-9]\d{0,2}',text) and confidence >= .65]
    # Faint leading/trailing digits disappear in the untreated crop. Prefer a
    # complete multi-digit reading when one variant is just its substring.
    if len(valid) == 2 and valid[0][0] != valid[1][0]:
        a,b = valid[0][0],valid[1][0]
        return int(a if len(a)>len(b) else b) if a in b or b in a else None
    return int(max(valid,key=lambda item:item[1])[0]) if valid else None


def bracketed_figures(figures, image, spacing, normalized=None):
    removed = set()
    for index, cell in enumerate(figures):
        bracket = re.fullmatch(r'[\(\[](\d{1,2})[\)\]]',cell.get('alternative',''))
        if bracket and bracket[1] == cell['text']:
            cell['parenthesized'] = True
        if not cell['text'].isdigit():
            continue
        before = [(i, other) for i, other in enumerate(figures) if (not other['text'] or other.get('alternative')=='(')
                  and other['string'] == cell['string'] and other['w'] < spacing * .5
                  and other['h'] > cell['h'] * 1.1
                  and -spacing*.12 <= cell['x'] - other['x'] - other['w'] < spacing * .4]
        after = [(i, other) for i, other in enumerate(figures) if (not other['text'] or other.get('alternative')==')')
                 and other['string'] == cell['string'] and other['w'] < spacing * .5
                 and other['h'] > cell['h'] * 1.1
                 and 0 <= other['x'] - cell['x'] - cell['w'] < spacing * .4]
        if before and after:
            removed.update([before[-1][0], after[0][0]])
            cell['parenthesized'] = True
    for index, cell in enumerate(figures):
        if (cell['text'] and cell['w'] < spacing) or index in removed or cell['w'] < spacing * .8:
            continue
        x, y, w, h = (cell[k] for k in ('x', 'y', 'w', 'h'))
        crop = cv2.copyMakeBorder(image[max(0,y-3):y+h+3,max(0,x-3):x+w+3],
                                 5,5,5,5,cv2.BORDER_CONSTANT,value=(255,255,255))
        crops = [crop,_text_crop(image,(x,y,w,h))]
        # Threshold the source pixels as well: normalization can join the two
        # parentheses into an "m" while the original still contains "(7)".
        source_gray=cv2.cvtColor(image[max(0,y-3):y+h+3,max(0,x):x+w],cv2.COLOR_BGR2GRAY)
        for threshold in (180,190):
            binary=np.where(source_gray<threshold,0,255).astype(np.uint8)
            crops.append(cv2.copyMakeBorder(cv2.cvtColor(binary,cv2.COLOR_GRAY2BGR),8,8,8,8,
                                           cv2.BORDER_CONSTANT,value=(255,255,255)))
        if normalized is not None:
            crops.append(_text_crop(normalized,(x,y,w,h)))
            binary = np.where(cv2.cvtColor(normalized,cv2.COLOR_BGR2GRAY)<115,0,255).astype(np.uint8)
            region=binary[max(0,y-2):y+h+2,max(0,x-3):x+w+3]
            crops.append(cv2.copyMakeBorder(cv2.cvtColor(region,cv2.COLOR_GRAY2BGR),7,7,7,7,
                                           cv2.BORDER_CONSTANT,value=(255,255,255)))
        readings = read_text(crops)
        bracketed = [(text,confidence) for text,confidence in readings
                     if re.fullmatch(r'[\(\[]\d{1,2}[\)\]]',text)]
        text, confidence = max(bracketed,key=lambda item:item[1]) if bracketed else readings[0]
        match = re.fullmatch(r'[\(\[](\d{1,2})[\)\]]', text)
        if match and int(match[1]) <= 36 and confidence >= .5:
            cell.update(text=match[1], confidence=float(confidence), parenthesized=True)
            removed.update(i for i, other in enumerate(figures) if i != index and not other['text']
                           and other['string'] == cell['string'] and other['w'] < spacing * .5
                           and 0 <= cell['x'] - other['x'] - other['w'] < spacing * .4)
        elif not cell['text']:
            # A separate left parenthesis may touch neither the digit nor the
            # closing parenthesis, while OCR merges the latter two into "7)".
            opening = [(i, other) for i, other in enumerate(figures) if i != index and not other['text']
                       and other['string'] == cell['string'] and other['w'] < spacing * .5
                       and -spacing*.12 <= x - other['x'] - other['w'] < spacing * .4]
            if opening and re.fullmatch(r'[\[\(]?\d{1,2}[\)\]]', cell.get('alternative', '')):
                if re.fullmatch(r'\d{1,2}',text) and int(text) <= 36 and confidence >= .5:
                    cell.update(text=text,confidence=float(confidence),parenthesized=True)
                    removed.add(opening[-1][0])
                    continue
                inner = image[max(0,y-3):y+h+3, x:x+w]
                digit, score = read_text([cv2.copyMakeBorder(inner,6,6,6,6,cv2.BORDER_CONSTANT,value=(255,255,255))])[0]
                if re.fullmatch(r'\d{1,2}',digit) and int(digit) <= 36 and score >= .5:
                    cell.update(text=digit,confidence=float(score),parenthesized=True)
                    removed.add(opening[-1][0])
            elif re.fullmatch(r'[\[\(]?\d{1,2}[\)\]]', cell.get('alternative','')) and w > spacing:
                # Both curves can be merged with the digit into one component.
                # Re-read its interior; require agreement with the visible digit
                # in the bracketed OCR result instead of copying the prior fret.
                crops=[]
                for a,b in ((.22,.8),(.26,.76),(.26,1.)):
                    inner=image[max(0,y-2):y+h+2,x+round(w*a):x+round(w*b)]
                    crops.append(cv2.copyMakeBorder(inner,6,6,6,6,cv2.BORDER_CONSTANT,value=(255,255,255)))
                expected=re.search(r'\d{1,2}',cell['alternative'])[0]
                readings=read_text(crops)
                if any(digit == expected and score >= .5 for digit,score in readings):
                    cell.update(text=expected,confidence=float(max(score for digit,score in readings if digit==expected)),parenthesized=True)
    return [cell for index, cell in enumerate(figures) if index not in removed]


def number_sequence(image, row):
    """Use agreement between printed anchors rather than propagate one bad OCR digit."""
    regions = measure_regions(row)
    spacing = float(np.median(np.diff(row['notation_lines'])))
    factor = max(1, min(4, 30 / float(np.median(np.diff(row['lines'])))))
    scaled = cv2.resize(image, None, fx=factor, fy=factor, interpolation=cv2.INTER_LINEAR)
    staff = [round(y * factor) for y in row['notation_lines']]
    anchors = [_printed_number(scaled, staff, round(a*factor), round(b*factor), spacing*factor)
               for a,b in regions]
    floor = row.get('number_floor',row.get('start_number'))
    votes = Counter(n-i for i,n in enumerate(anchors) if n is not None and n > i
                    and (floor is None or n-i >= floor))
    base = None
    if votes:
        ranked = votes.most_common()
        if (len(ranked) == 1 or ranked[0][1] > ranked[1][1]) and (ranked[0][1] >= 2 or ranked[0][0] == row.get('start_number',1)
                or (floor is not None and floor <= ranked[0][0] <= floor+3)):
            base = ranked[0][0]
    return [base+i for i in range(len(regions))] if base else [], anchors


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


def standard_rests(gray, staff, left, right, spacing, note_centers):
    top = max(0, round(staff[0]-spacing*.3))
    bottom = min(gray.shape[0], round(staff[-1]+spacing*.8))
    ink = (gray[top:bottom,left:right] < 145).astype(np.uint8)
    horizontal = cv2.morphologyEx(ink,cv2.MORPH_OPEN,np.ones((1,max(10,round(spacing*5))),np.uint8))
    ink = ink-horizontal
    ink = cv2.morphologyEx(ink,cv2.MORPH_CLOSE,np.ones((max(2,round(spacing*.2)),2),np.uint8))
    _,_,stats,_ = cv2.connectedComponentsWithStats(ink)
    rests = []
    for x,y,w,h,area in stats[1:]:
        center = left+x+w/2
        if x < spacing*.4 or x+w > right-left-spacing*.4 or any(abs(center-n) < spacing*1.2 for n in note_centers):
            continue
        duration = None
        if spacing*.7 < w < spacing*1.7 and spacing*.2 < h < spacing*.85 and area/(w*h) > .65:
            if abs(top+y+h-staff[2]) < spacing*.35:
                duration = 2
            elif abs(top+y-staff[1]) < spacing*.35:
                duration = 1
        elif spacing*.45 < w < spacing*1.4 and spacing*2.05 < h < spacing*3.1:
            if staff[0]+spacing*.35 < top+y < staff[0]+spacing*1.4:
                duration = 4
        elif spacing*.4 < w < spacing*1.3 and spacing*1.05 < h < spacing*2.05:
            if staff[0]+spacing*.6 < top+y < staff[0]+spacing*1.65:
                duration = 8
        if duration:
            rests.append((center,TabBeat(duration=duration)))
    return rests


def read_combined_local(path, row, tuning, diagnostics=None):
    from app.services.notation_graph import attach_heads,align_events,template_refine,connect_beams,refine_fret_crops,corroborate_pitches,seam_digit_fragments
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
    weak = [cell for cell in figures if cell['text'].isdigit() and cell['confidence'] < .35]
    readings = read_text([_text_crop(image,tuple(cell[k] for k in ('x','y','w','h'))) for cell in weak])
    for cell,(text,confidence) in zip(weak,readings):
        if re.fullmatch(r'\d{1,2}',text) and int(text) <= 36 and confidence >= .8:
            cell.update(text=text,confidence=float(confidence))
    figures = bracketed_figures(figures, image, tab_spacing,cv2.cvtColor(normalized,cv2.COLOR_GRAY2BGR))
    stems = standard_stems(gray, staff, lines[0])
    seams=[x*factor for x in row.get('join_seams',[])]
    figures=seam_digit_fragments(figures,normalized,lines,seams,tab_spacing)
    figures=refine_fret_crops(figures,image,tab_spacing,
        attach_heads(gray,stems,staff,0,image.shape[1],spacing,seams=seams),read_text)
    template_refine(figures,image)
    result = RecognitionResult(measures=[], warnings=[
        '使用独立联合谱本地流程：TAB 数字对应上方符干、符尾及休止；拍号暂按 4/4，需核对。未能确认连续的边缘片段不自动补齐。'])
    previous = [TabNote.model_validate(note) for note in row.get('previous_notes', [])]
    number = int(row.get('start_number', 1))
    row_events=[]
    numbers = row.get('measure_numbers') or number_sequence(original,row)[0]
    if diagnostics is not None:
        diagnostics.update(width=original.shape[1],height=original.shape[0],events=[],measures=[])
    full_regions=measure_regions(row)
    work=[(bounds,'') for bounds in full_regions]
    if full_regions:
        for side,bounds in [('left',(0,full_regions[0][0])),('right',(full_regions[-1][1],original.shape[1]))]:
            if bounds[1]-bounds[0]>tab_spacing/factor*3:
                work.append((bounds,side))
    for measure_index, (bounds,side) in enumerate(work):
        if side:
            fragment_number=result.measures[0].number-1 if side=='left' else result.measures[-1].number+1
            if fragment_number<1:continue
            previous=[TabNote.model_validate(n) for n in row.get('previous_notes',[])] if side=='left' else result.measures[-1].beats[-1].notes
        left, right = [round(x * factor) for x in bounds]
        selected = sorted((cell for cell in figures if left + 3 < cell['x_center'] < right - 3), key=lambda c: c['x_center'])
        groups = []
        for cell in selected:
            if groups and abs(cell['x_center'] - groups[-1][0]['x_center']) < tab_spacing * .3:
                groups[-1].append(cell)
            else:
                groups.append([cell])
        beats, confidences, centers = [], [], []
        graph=attach_heads(gray,stems,staff,left,right,spacing,[float(np.mean([c['x_center'] for c in group])) for group in groups],seams=seams)
        connect_beams(gray,graph,spacing)
        matched=align_events([float(np.mean([c['x_center'] for c in group])) for group in groups],graph,spacing)
        event_traces=[]
        for group_index,group in enumerate(groups):
            center = float(np.mean([cell['x_center'] for cell in group]))
            candidates = [matched[group_index]] if group_index in matched else []
            unresolved = []
            if not candidates:
                duration = 4
                unresolved.append('duration')
            else:
                stem = candidates[0]
                duration, unknown = stem_duration(gray, stem, stem['head'][0], spacing)
                unresolved.extend(unknown)
            baseline=[s for s in stems if left+3<s['x']<right-3 and abs(s['x']-center)<spacing*1.1]
            old_stem=min(baseline,key=lambda s:min(abs(s['x']-center+spacing*.55),abs(s['x']-center-spacing*.55))) if baseline else None
            old_rhythm=stem_duration(gray,old_stem,center,spacing) if old_stem else (4,['duration'])
            notes = []
            for cell in group:
                if cell['text'].isdigit() and int(cell['text']) <= 36:
                    note = TabNote(string=cell['string'], fret=int(cell['text']))
                    if cell['confidence'] < .35:
                        unresolved.append('pitch')
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
            beats.append(TabBeat(duration=duration, notes=notes, unresolved=sorted(set(unresolved)),
                ocr_confidence=float(min(c['confidence'] for c in group)),pitch_evidence='ocr',
                rhythm_evidence='notation' if candidates and candidates[0].get('head_detected') else 'fallback'))
            event_traces.append(dict(beat=beats[-1],x=center/factor,
                boxes=[[c['x']/factor,c['y']/factor,c['w']/factor,c['h']/factor] for c in group],
                head=[v/factor for v in candidates[0]['head']] if candidates else None,
                stem=[candidates[0]['x']/factor,candidates[0]['top']/factor,candidates[0]['bottom']/factor] if candidates else None,
                confidence=min(c['confidence'] for c in group),
                template=any(c.get('template_score') for c in group)))
            event_traces[-1]['baseline']=(old_rhythm,old_stem)
            event_traces[-1]['tab_strings']=sorted(set(c['string'] for c in group))
            event_traces[-1].update(head_detected=candidates[0].get('head_detected',False) if candidates else False,
                                   head_partial=candidates[0].get('head_partial',False) if candidates else False,
                                   stem_inferred=candidates[0].get('stem_inferred',False) if candidates else False,
                                   beam_group=candidates[0].get('beam_group',0) if candidates else 0)
            centers.append(center)
            previous = notes
        whole_rest = not beats and _whole_rest(gray,staff,left,right,spacing)
        rests = [(float(left+right)/2,TabBeat(duration=1))] if whole_rest else standard_rests(gray,staff,left,right,spacing,centers)
        if rests:
            events = sorted(list(zip(centers,beats))+rests,key=lambda item:item[0])
            beats = [beat for _,beat in events]
            confidences.extend([.9]*len(rests))
            # A rest ends the preceding note; do not permit ties across it.
            previous = beats[-1].notes
        # A new association must not replace a complete, visually supported old
        # reading with an incomplete rhythm. Both candidates come from pixels;
        # no durations are invented or searched solely to make the meter fit.
        def length(items):
            return sum((Fraction(1,b.duration)*(Fraction(3,2) if b.dotted else 1)*(Fraction(2,3) if b.triplet else 1) for b in items),Fraction(0))
        expected=Fraction(1)
        alternate=[]
        for beat in beats:
            event=next((e for e in event_traces if e['beat'] is beat),None)
            copy=beat.model_copy(deep=True)
            if event:
                (copy.duration,flags),_=event['baseline']
                copy.unresolved=[v for v in copy.unresolved if v!='duration']+list(flags)
            alternate.append(copy)
        if length(alternate)==expected and not any('duration' in b.unresolved for b in alternate) and (
                length(beats)!=expected or any('duration' in b.unresolved for b in beats)):
            for beat,alternative in zip(beats,alternate):
                event=next((e for e in event_traces if e['beat'] is beat),None)
                beat.duration=alternative.duration;beat.unresolved=alternative.unresolved
                beat.rhythm_evidence='fallback'
                if event:
                    old=event['baseline'][1]
                    event.update(head_detected=False,beam_group=0)
                    if old:event.update(stem=[old['x']/factor,old['top']/factor,old['bottom']/factor],
                        head=[event['x'],(old['top'] if event['x']*factor>=old['x'] else old['bottom'])/factor])
        if not beats:
            if _whole_rest(gray, staff, left, right, spacing):
                beats = [TabBeat(duration=1)]
                confidences = [.9]
            else:
                beats = [TabBeat(duration=4, unresolved=['pitch', 'duration'])]
                confidences = [0]
        printed = fragment_number if side else numbers[measure_index] if len(numbers) == len(full_regions) else _printed_number(image, staff, left, right, spacing)
        if not side and not numbers and printed is not None and ('number_floor' in row or 'start_number' in row) and not number <= printed <= number+2:
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
        for e in event_traces:
            e['measure']=measure.number;e['beat_index']=next(i+1 for i,b in enumerate(measure.beats) if b is e['beat'])
        row_events.extend(event_traces)
        if side:
            measure.issues.append('边缘片段：未确认整小节覆盖，不自动计入完整曲谱。')
            total=sum((Fraction(1,b.duration)*(Fraction(3,2) if b.dotted else 1)*(Fraction(2,3) if b.triplet else 1) for b in measure.beats),Fraction(0))
            cov=np.mean(cv2.cvtColor(original,cv2.COLOR_BGR2GRAY)[row['lines']]<240,axis=0)
            ends=np.flatnonzero(cov>=.75)
            end=int(ends[-1])+1 if len(ends) else original.shape[1]
            begin=int(ends[0]) if len(ends) else 0
            clear_edge=bool(selected) and (max(c['x']+c['w'] for c in selected)/factor < end-tab_spacing/factor*.5
                if side=='right' else min(c['x'] for c in selected)/factor > begin+tab_spacing/factor*.5)
            complete=bool(len(numbers)==len(full_regions) and clear_edge
                          and len(matched)==len(groups) and groups and not any(b.unresolved for b in measure.beats)
                          and total==Fraction(measure.numerator,measure.denominator))
            if complete:
                measure.issues[-1]=('行末右侧' if side=='right' else '行首左侧')+'边界未检出；逐音匹配、完整拍数与边缘检查通过，作为候选保留，请核对原图。'
                if side=='left':result.measures.insert(0,measure)
                else:result.measures.append(measure)
            result.fragments.append(TabFragment(side=side,bounds=list(bounds),measure=measure,complete=complete))
        else:result.measures.append(measure)
        if diagnostics is not None:
            if not side or complete:diagnostics['measures'].append(dict(number=measure.number,bounds=list(bounds),issues=measure.issues))
            for bi,beat in enumerate(measure.beats):
                entry=next((e for e in event_traces if e['beat'] is beat),None)
                if entry:
                    diagnostics['events'].append(dict({k:v for k,v in entry.items() if k not in ('beat','baseline')},
                        measure=measure.number,beat_index=bi+1,duration=beat.duration,unresolved=beat.unresolved,
                        notes=[n.model_dump() for n in beat.notes],fragment=bool(side)))
        if not side:number = measure.number + 1
    if not result.measures:
        raise UnsupportedTabImage('联合谱没有可读的完整小节')
    corroborate_pitches(row_events,staff[0]/factor,spacing/factor,tuning)
    if diagnostics is not None:
        for entry in diagnostics['events']:
            event=next((e for e in row_events if e['measure']==entry['measure'] and e['beat_index']==entry['beat_index']),None)
            if event and event.get('pitch_evidence'):
                entry.update(unresolved=event['beat'].unresolved,notes=[n.model_dump() for n in event['beat'].notes],
                             pitch_evidence=event['pitch_evidence'])
    return result
