"""Read the geometry of TAB with rhythm stems below the staff.

This is deliberately a draft reader. Unknown glyphs/continuations are retained
as unresolved beats, not silently changed to rests or repaired to fit a meter.
"""
import os
import re
import threading
from pathlib import Path

import cv2
import numpy as np

from app.models.score import GraceNote, RecognitionResult, TabBeat, TabMeasure, TabNote
from app.services.image_io import imread

_ocr = None
_ocr_lock = threading.Lock()
OCR_THREADS = min(4, os.cpu_count() or 1)


class UnsupportedTabImage(ValueError):
    pass


def spans(indices, gap=3):
    indices = np.asarray(indices)
    if not len(indices):
        return []
    groups = np.split(indices, np.flatnonzero(np.diff(indices) > gap) + 1)
    return [(int(group[0]), int(group[-1])) for group in groups if len(group)]


def quarter_rest_boxes(gray: np.ndarray, lines: list[int], spacing: int):
    ink=(gray<145).astype(np.uint8)
    ink[:max(0,lines[0]-spacing//3)]=0
    ink[lines[-1]+round(spacing*.6):]=0
    ink=cv2.morphologyEx(ink,cv2.MORPH_CLOSE,np.ones((3,1),np.uint8))
    _,_,stats,_=cv2.connectedComponentsWithStats(ink)
    return [(int(x),int(y),int(w),int(h)) for x,y,w,h,area in stats[1:]
            if spacing*1.6<h<spacing*3 and spacing*.25<w<spacing*1.2 and area>spacing*2]


def eighth_rest_boxes(gray, lines, spacing):
    _,_,stats,_ = cv2.connectedComponentsWithStats((gray < 115).astype(np.uint8))
    return [(int(x),int(y),int(w),int(h)) for x,y,w,h,area in stats[1:]
            if area >= 25 and spacing*.25 <= h < spacing*.48
            and spacing*.25 <= w <= spacing*.8 and .65 < w/h < 1.5
            and lines[0] <= y <= lines[-2]]


def staff_geometry(image: np.ndarray, lines: list[int]) -> dict:
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY).astype(np.float32)
    spacing = int(np.median(np.diff(lines)))
    if spacing < 6 or min(lines) < 8 or max(lines) + 8 >= gray.shape[0]:
        raise UnsupportedTabImage("弦线区域不完整")
    support = np.zeros(gray.shape[1], dtype=int)
    for y in lines:
        background = (gray[y-7:y-4].mean(0) + gray[y+5:y+8].mean(0)) / 2
        support += background - gray[y-2:y+3].min(0) > 6
    segments = spans(np.flatnonzero(support >= max(2,len(lines)-1)), spacing)
    if not segments:
        raise UnsupportedTabImage("未定位到连续的弦线")
    left, right = max(segments, key=lambda pair: pair[1] - pair[0])
    if right - left < spacing * 6:
        raise UnsupportedTabImage("弦线过短")
    # Vertical page borders have no horizontal staff-line contrast and therefore
    # cannot become the staff's left/right edge. Requiring a continuous stroke
    # across most of the staff also excludes eighth-rest flags.
    staff = gray[lines[0]+4:lines[-1]-3]
    contrast = cv2.blur(staff, (15, 1)) - staff
    mask = cv2.dilate((contrast > 2).astype(np.uint8), np.ones((1, 5), np.uint8))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((5, 1), np.uint8))
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((max(3, int(staff.shape[0]*.8)), 1), np.uint8))
    xs = np.flatnonzero(mask.sum(0) > staff.shape[0] * .7)
    bars = [round((a+b)/2) for a, b in spans(xs, 8)
            if b-a >= 2 and left+spacing < (a+b)/2 < right-spacing]
    # A playback cursor extends above and below the staff. A barline ends at
    # the outer string lines. Inspect the same column outside the staff before
    # accepting a vertical edge as a barline.
    def cursor_edge(x):
        outside = []
        radius = max(4,round(spacing*.4))
        for a,b in [(max(0,lines[0]-spacing),lines[0]-spacing//5),
                    (lines[-1]+spacing//5,min(gray.shape[0],lines[-1]+spacing))]:
            region = gray[a:b]
            edge = cv2.blur(region,(15,1))-region
            outside.append(float((edge[:,max(0,x-radius):x+radius+1]>3).sum(0).max())/max(1,b-a))
        return outside[0] >= .65 and outside[1] > .25
    bars = [x for x in bars if not cursor_edge(x)]
    blue, green, red = cv2.split(image.astype(np.float32))
    yellow = ((np.minimum(green,red)-blue > 18) & (abs(green-red) < 45)
              & (np.minimum(green,red) > 120))
    cursor_columns = yellow[max(0,lines[0]-spacing):min(gray.shape[0],lines[-1]+spacing*2)].mean(0) > .35
    color_edges = [edge for a,b in spans(np.flatnonzero(cursor_columns),8)
                   if b-a > spacing*.5 for edge in (a,b)]
    bars = [x for x in bars if not any(abs(x-edge) <= spacing*.35 for edge in color_edges)]
    rests=quarter_rest_boxes(gray,lines,spacing)+eighth_rest_boxes(gray,lines,spacing)
    bars=[x for x in bars if not any(a-spacing*.15<x<a+w+spacing*.15 for a,_,w,_ in rests)]
    return dict(left=left, right=right, bars=[left, *bars, right], spacing=spacing, cursor_edges=color_edges)


def read_text(images):
    global _ocr
    if not images:
        return []
    with _ocr_lock:
        if _ocr is None:
            from rapidocr_onnxruntime import RapidOCR
            _ocr = RapidOCR(intra_op_num_threads=OCR_THREADS, inter_op_num_threads=2)
        return _ocr.text_rec(images)[0]


def _text_crop(image, box, padding=4):
    x, y, w, h = box
    crop = image[max(0,y-padding):y+h+padding, max(0,x-padding):x+w+padding]
    return cv2.copyMakeBorder(crop, 6, 6, 6, 6, cv2.BORDER_CONSTANT, value=(255,255,255))


def separate_parentheses(cells, ink, spacing):
    removed = set()
    pairs = []
    for index, cell in enumerate(cells):
        x,y,w,h = (cell[k] for k in ('x','y','w','h'))
        if not (w <= spacing*.23 and h >= spacing*.45):
            continue
        mask = ink[y:y+h,x:x+w] > 0
        centers = [np.flatnonzero(row).mean() for row in mask if row.any()]
        if len(centers) < 8:
            continue
        k = max(2,len(centers)//5)
        middle = np.mean(centers[len(centers)//3:len(centers)*2//3])
        if not (np.mean(centers[:k])-middle < -w*.12 and np.mean(centers[-k:])-middle < -w*.12):
            continue
        # A narrow closing curve and an opening component enclose the actual
        # fret digits. Neither parenthesis is a fret 1 or a separate note.
        openings = [(j,c) for j,c in enumerate(cells) if c['string']==cell['string']
                    and x-spacing*1.4 < c['x'] < x-spacing*.3
                    and c['w'] <= spacing*.23 and c['h'] >= spacing*.45]
        if openings:
            j, opening = min(openings,key=lambda item:item[1]['x'])
            body = [c for c in cells if c['string']==cell['string']
                    and opening['x']+opening['w'] <= c['x'] and c['x']+c['w'] <= x]
            if body and min(c['x'] for c in body)-opening['x']-opening['w'] <= spacing*.25:
                removed.update([index,j])
                pairs.append((cell['string'],opening['x']+opening['w'],x))
    remaining = [c for i,c in enumerate(cells) if i not in removed]
    return remaining,pairs


def _glyphs(image, gray, lines, geometry):
    spacing = geometry['spacing']
    _, ink = cv2.threshold(gray.astype(np.uint8), 115, 255, cv2.THRESH_BINARY_INV)
    note_mask = ink.copy()
    note_mask[:max(0,lines[0]-spacing//2)] = 0
    note_mask[lines[-1]+spacing//2:] = 0
    _, _, stats, _ = cv2.connectedComponentsWithStats(note_mask)
    cells = []
    for x, y, w, h, area in stats[1:]:
        if not geometry['left']+5 < x < geometry['right']-5 or area < 10 or w < 3:
            continue
        if not spacing*.48 <= h <= spacing*1.15:
            continue
        string = int(np.argmin(abs(np.asarray(lines) - (y+h/2)))) + 1
        if abs(lines[string-1]-(y+h/2)) <= spacing*.24:
            cells.append(dict(x=int(x), y=int(y), w=int(w), h=int(h), string=string))
    cells, parentheses = separate_parentheses(cells,note_mask,spacing)
    # Two digit fret numbers are a single glyph. Small grace-note figures must
    # not be concatenated to a full-size fret number (e.g. grace 9 followed by 10).
    groups = []
    for cell in sorted(cells, key=lambda item: (item['string'], item['x'])):
        if groups:
            prev = groups[-1]
            same_height = min(prev['h'],cell['h']) / max(prev['h'],cell['h']) > .8
            if prev['string'] == cell['string'] and same_height and 0 <= cell['x']-prev['x']-prev['w'] <= spacing*.22:
                bottom = max(prev['y']+prev['h'],cell['y']+cell['h'])
                prev['w'] = cell['x']+cell['w']-prev['x']
                prev['y'] = min(prev['y'],cell['y'])
                prev['h'] = bottom-prev['y']
                continue
        groups.append(cell.copy())
    for cell in groups:
        cell['parenthesized'] = any(string==cell['string'] and left <= cell['x']
                                     and cell['x']+cell['w'] <= right for string,left,right in parentheses)
    original = [_text_crop(image, (c['x'],c['y'],c['w'],c['h'])) for c in groups]
    binary = []
    for cell in groups:
        x,y,w,h = (cell[k] for k in ('x','y','w','h'))
        crop = 255 - note_mask[max(0,y-2):y+h+2,max(0,x-3):x+w+3]
        binary.append(cv2.copyMakeBorder(cv2.cvtColor(crop,cv2.COLOR_GRAY2BGR),7,7,7,7,cv2.BORDER_CONSTANT,value=(255,255,255)))
    texts = read_text(original + binary)
    def valid(text):
        return text.lower() in ('x','×') or bool(re.fullmatch(r'\d{1,2}',text) and int(text) <= 36)
    for i, cell in enumerate(groups):
        text, confidence = texts[i]
        second, second_confidence = texts[i+len(groups)]
        # Thresholding can remove the faint top of an italic 7 and turn it into
        # a high-confidence 1. Prefer the grayscale reading, retaining evidence.
        if not valid(text) or confidence < .35:
            if second.lower() in ('x','×') and second_confidence >= .45:
                text, confidence = second, second_confidence
            elif not valid(text) and valid(second) and second != '1' and second_confidence >= .8:
                text, confidence = second, second_confidence
            elif not valid(text):
                text, confidence = '', 0
        cell.update(text=text, confidence=float(confidence), alternative=second,
                    x_center=cell['x']+cell['w']/2)
    # Grace figures and faint digits lose their shape in the padded input.
    # Two larger grayscale readings must agree before accepting a fret here.
    small = [cell for cell in groups if not cell['text'] or
             (cell['confidence'] < .7 and valid(cell['alternative'])
              and cell['alternative'] != '1' and cell['alternative'] != cell['text'])]
    enlarged = []
    for cell in small:
        x,y,w,h = (cell[k] for k in ('x','y','w','h'))
        crop = image[max(0,y-4):y+h+4, max(0,x-3):x+w+3]
        for scale in (3,4):
            enlarged.append(cv2.copyMakeBorder(cv2.resize(crop,None,fx=scale,fy=scale,interpolation=cv2.INTER_CUBIC),
                                               2,2,2,2,cv2.BORDER_CONSTANT,value=(255,255,255)))
    readings = read_text(enlarged)
    for index, cell in enumerate(small):
        first, second = readings[index*2:index*2+2]
        agrees = first[0] == second[0] and first[0].isdigit() and int(first[0]) <= 36
        confident = min(first[1],second[1]) >= .8
        corroborated = (first[0] == cell['alternative'] and first[0] != '1'
                        and min(first[1],second[1]) >= .5)
        if agrees and (confident or corroborated):
            cell.update(text=first[0], confidence=float(min(first[1],second[1])))
    fields = [cell for cell in groups if not cell['text'] or cell['text']=='1']
    images = []
    for cell in fields:
        line = lines[cell['string']-1]
        crop = image[max(0,line-spacing//2):line+spacing//2+1,max(0,cell['x']-3):cell['x']+cell['w']+3]
        gray_crop = cv2.cvtColor(crop,cv2.COLOR_BGR2GRAY).astype(np.float32)
        low,high = np.percentile(gray_crop,[5,90])
        normalized = cv2.cvtColor(np.clip((gray_crop-low)*255/max(1,high-low),0,255).astype(np.uint8),cv2.COLOR_GRAY2BGR)
        images.extend(cv2.resize(c,None,fx=4,fy=4,interpolation=cv2.INTER_CUBIC) for c in [crop,normalized])
    readings = read_text(images)
    for index, cell in enumerate(fields):
        first,second = readings[index*2:index*2+2]
        if first[0]==second[0] and first[0].isdigit() and int(first[0])<=36 and min(first[1],second[1])>=.7:
            cell.update(text=first[0],confidence=float(min(first[1],second[1])))
    return groups, ink, stats


def rhythm_stems(gray: np.ndarray, lines: list[int], geometry: dict):
    spacing=geometry['spacing']
    y0=lines[-1]+round(spacing*.8)
    y1=min(gray.shape[0],lines[-1]+round(spacing*2.8))
    rhythm=gray[y0:y1]
    if not rhythm.size:
        return []
    contrast=cv2.blur(rhythm,(15,1))-rhythm
    vertical=(contrast>4).astype(np.uint8)
    vertical=cv2.morphologyEx(vertical,cv2.MORPH_CLOSE,np.ones((3,1),np.uint8))
    vertical=cv2.morphologyEx(vertical,cv2.MORPH_OPEN,np.ones((max(5,round(spacing*.4)),1),np.uint8))
    groups=spans(np.flatnonzero(vertical.sum(0)>=spacing*.4))
    candidates=[]
    for a,b in groups:
        x=round((a+b)/2)
        if not geometry['left']<x<geometry['right']:
            continue
        ys=np.flatnonzero(vertical[:,a:b+1].any(1))
        if len(ys):
            top, bottom = int(ys[0]), int(ys[-1])
            trace = contrast[top:bottom+1,max(0,x-1):x+2].max(1)
            if (any(abs(x-edge) < spacing*.35 for edge in geometry.get('cursor_edges',[]))
                    and np.median(trace[trace > 4]) < 15):
                continue
            if bottom-top >= spacing*.65 and (trace > 6).sum() >= len(trace)*.65:
                candidates.append(dict(x=x,top=y0+top,bottom=y0+bottom))
    if not candidates:
        return []
    baseline = float(np.median([item['bottom'] for item in candidates]))
    candidates = [item for item in candidates
                  if abs(item['bottom']-baseline) <= spacing*.25]
    # A flag's outer edge can also contain a short vertical stroke. Keep the
    # longer stem when both strokes belong to the same symbol. Cursor borders
    # usually end above the rhythm baseline and are filtered above.
    selected = []
    for item in sorted(candidates, key=lambda item: item['bottom']-item['top'], reverse=True):
        if not any(abs(item['x']-other['x']) < spacing*.8 for other in selected):
            selected.append(item)
    return sorted(selected, key=lambda item: item['x'])


def nearby_dot(ink, x0, y0, width, height, spacing):
    x0=max(0,int(x0)); y0=max(0,int(y0))
    region=ink[y0:y0+int(height),x0:x0+int(width)]
    if not region.size:
        return False
    _,_,stats,_=cv2.connectedComponentsWithStats(region)
    return any(4<=area<spacing*spacing*.1 and 1<=w<spacing*.3 and 1<=h<spacing*.3
               and .45<w/h<2.2 and a>0 and b>0 and a+w<region.shape[1] and b+h<region.shape[0]
               for a,b,w,h,area in stats[1:])


def visible_tie(gray, line, x, spacing):
    under = (gray[line+round(spacing*.2):line+round(spacing*.85)] < 190).astype(np.uint8)
    _,_,curves,_ = cv2.connectedComponentsWithStats(under)
    return any(w > spacing*.7 and a < x-spacing*.5 and abs(a+w-x) < spacing*.45
               for a,_,w,_,area in curves[1:] if area > spacing)


def visible_slide(gray, line, x_left, x_right, spacing, staff_bottom=None, staff_top=None, end_depth=.35):
    """Require both a straight diagonal and a small annotation below it."""
    x0 = round(x_left+spacing*.44)
    x1 = round(x_right-spacing*.38)
    y0 = round(line-spacing*.5)
    y1 = round(line+spacing)
    if x1-x0 < spacing*.5:
        return False
    ink = (gray[y0:y1,x0:x1] < 190).astype(np.uint8)
    segments = cv2.HoughLinesP(ink,1,np.pi/360,threshold=max(10,round(spacing*.4)),
                              minLineLength=max(spacing*.45,(x1-x0)*.65),maxLineGap=5)
    if segments is None:
        return False
    diagonal = [(int(a),int(b),int(c),int(d)) for a,b,c,d in segments[:,0]
                if a<c and .06 < abs((d-b)/(c-a)) < 1
                and max(b,d)+y0 <= line+spacing*end_depth]
    if not diagonal:
        return False
    a,b,c,d=max(diagonal,key=lambda item:item[2]-item[0])
    staff_bottom = line if staff_bottom is None else staff_bottom
    regions = [(round(staff_bottom+spacing*.16),round(staff_bottom+spacing*1.4))]
    if staff_top is not None:
        regions.append((max(0,staff_top-spacing),staff_top-2))
    for top,bottom in regions:
        labels = (gray[top:bottom,round(x_left+spacing*.2):round(x_right-spacing*.1)] < 180).astype(np.uint8)
        if end_depth>.35:
            # In a short slide-out the slanted stroke may touch the "sl"
            # letters. Remove that measured stroke before finding the label.
            left=round(x_left+spacing*.2)
            slope=(d-b)/(c-a)
            y_left=y0+b+(left-x0-a)*slope-top
            y_right=y_left+(labels.shape[1]-1)*slope
            cv2.line(labels,(0,round(y_left)),(labels.shape[1]-1,round(y_right)),0,max(3,round(spacing*.13)))
        labels = cv2.morphologyEx(labels,cv2.MORPH_CLOSE,np.ones((1,4),np.uint8))
        _,_,stats,_ = cv2.connectedComponentsWithStats(labels)
        if any(spacing*.25 <= h < spacing*.85 and spacing*.28 <= w < spacing*1.25
               and .55 < w/h < 1.5 and area > 15 and y > 0 and y+h < labels.shape[0]
               for _,y,w,h,area in stats[1:]):
            return 'down' if d>b else 'up'
    return False


def visible_hammer(gray, line, x_left, x_right, spacing, staff_bottom):
    x0 = round(x_left+spacing*.25)
    x1 = round(x_right-spacing*.25)
    if x1-x0 < spacing*.35:
        return False
    # The H/P annotation is between the stems and above their connecting beam.
    y0 = round(staff_bottom+spacing*.9)
    y1 = round(staff_bottom+spacing*2.05)
    crop = gray[y0:y1,x0:x1].astype(np.uint8)
    _,_,stats,_ = cv2.connectedComponentsWithStats((crop < 170).astype(np.uint8))
    boxes = [(int(x),int(y),int(w),int(h)) for x,y,w,h,area in stats[1:]
             if spacing*.3 < h < spacing*.85 and spacing*.15 < w < spacing*.65
             and area > spacing and x > 0 and y > 0 and x+w < crop.shape[1] and y+h < crop.shape[0]]
    if not boxes:
        return False
    under = (gray[round(line+spacing*.2):round(line+spacing*1.15),round(x_left):round(x_right)+1] < 190).astype(np.uint8)
    _,_,curves,_ = cv2.connectedComponentsWithStats(under)
    if not any(w > (x_right-x_left)*.6 for _,_,w,_,area in curves[1:] if area > spacing):
        return False
    images = []
    for x,y,w,h in boxes:
        cell = crop[max(0,y-3):y+h+3,max(0,x-3):x+w+3]
        cell = cv2.resize(cell,None,fx=3,fy=3,interpolation=cv2.INTER_CUBIC)
        images.append(cv2.cvtColor(cv2.copyMakeBorder(cell,2,2,2,2,cv2.BORDER_CONSTANT,value=255),cv2.COLOR_GRAY2BGR))
    return any(text.upper() in ('H','P') and confidence >= .8 for text,confidence in read_text(images))


def slide_has_curve(gray, line, x_left, x_right, spacing):
    x0=round(x_left+spacing*.15);x1=round(x_right-spacing*.1)
    y0=round(line+spacing*.35);y1=round(line+spacing*1.15)
    if x1-x0 < spacing*.5:
        return False
    ink=(gray[y0:y1,x0:x1] < 200).astype(np.uint8)
    # A curve may touch the next string line. Its top edge still sags in the
    # middle; a straight slide or a horizontal string line has no such sag.
    profile=[np.flatnonzero(ink[:,col])[0] for col in range(ink.shape[1]) if ink[:,col].any()]
    if len(profile)<max(8,ink.shape[1]*.7):
        return False
    k=max(2,len(profile)//4)
    middle=np.mean(profile[len(profile)//3:len(profile)*2//3])
    return bool(middle-max(np.mean(profile[:k]),np.mean(profile[-k:])) > spacing*.1)


def read_local_tab(path: Path, row: dict, tuning: list[int]) -> RecognitionResult:
    image = imread(path)
    if image is None:
        raise UnsupportedTabImage("无法读取谱行图片")
    lines = row['lines']
    if len(lines) != len(tuning):
        raise UnsupportedTabImage("检测到的弦数与调弦配置不同，请先确认乐器")
    geometry = staff_geometry(image, lines)
    gray = cv2.cvtColor(image,cv2.COLOR_BGR2GRAY).astype(np.float32)
    spacing = geometry['spacing']
    glyphs, ink, stats = _glyphs(image, gray, lines, geometry)
    stems=rhythm_stems(gray,lines,geometry)
    events = []
    previous = [TabNote.model_validate(note) for note in row.get('previous_notes', [])]
    used = set()
    for stem in stems:
        x=stem['x']
        unresolved = []
        matching = [(i,c) for i,c in enumerate(glyphs) if abs(c['x_center']-x) <= spacing*.42]
        notes = []
        confidence = 1.0
        for i, cell in matching:
            used.add(i)
            confidence = min(confidence,cell['confidence'])
            if cell['text'].lower() in ('x','×'):
                notes.append(TabNote(string=cell['string'],fret=0,kind='dead'))
            elif cell['text'].isdigit() and int(cell['text']) <= 36:
                note = TabNote(string=cell['string'],fret=int(cell['text']))
                if (cell['parenthesized'] and any(n.string==note.string and n.fret==note.fret for n in previous)
                        and visible_tie(gray,lines[note.string-1],x,spacing)):
                    note.kind = 'tie'
                grace = [(j,c) for j,c in enumerate(glyphs) if j not in used
                         and c['string'] == cell['string'] and c['h'] < cell['h']*.8
                         and 0 < cell['x']-c['x']-c['w'] < spacing*.4]
                if len(grace) == 1:
                    j, figure = grace[0]
                    used.add(j)
                    if figure['text'].isdigit():
                        note.grace = GraceNote(fret=int(figure['text']))
                    else:
                        unresolved.append('pitch')
                notes.append(note)
            else:
                unresolved.append('pitch')
        if not matching:
            # A blank continuation stem is a tie only with a visible curve.
            for note in previous:
                if note.kind == 'dead':
                    continue
                if visible_tie(gray,lines[note.string-1],x,spacing):
                    notes.append(note.model_copy(update={'kind':'tie','slide':False,'legato_slide':False,'slide_out':None,'hammer':False,'staccato':False,'grace':None}))
            if not notes:
                unresolved.append('pitch')
        beam_start=stem['bottom']-round(spacing*.6)
        beam_stop=min(gray.shape[0],stem['bottom']+4)
        patch=gray[beam_start:beam_stop,max(0,x-12):x+13]
        beams=spans(np.flatnonzero((patch<150).sum(1)>9),2)
        duration=4 * (2 ** min(len(beams),4)) if beams else (2 if stem['bottom']-stem['top']<spacing*.95 else 4)
        dotted=nearby_dot(ink,x+spacing*.06,stem['bottom']-spacing*.5,spacing*.70,spacing*.8,spacing)
        dot_region=ink[max(0,lines[0]-round(spacing*.9)):lines[0]-round(spacing*.3),max(0,x-round(spacing*.22)):x+round(spacing*.22)]
        _,_,dots,_=cv2.connectedComponentsWithStats(dot_region)
        if any(4<=area<spacing*spacing*.1 and 1<=w<spacing*.3 and 1<=h<spacing*.3 and .45<w/h<2.2 for _,_,w,h,area in dots[1:]):
            for note in notes:
                if note.kind=='normal':
                    note.staccato=True
        events.append(dict(x=x, beat=TabBeat(duration=duration,dotted=dotted, notes=notes, unresolved=sorted(set(unresolved))), confidence=confidence))
        previous=notes
    # Eighth rests have a small flag followed by a descending stroke in the
    # staff. They have no stem below the staff and are not fret digits.
    for x,y,w,h in quarter_rest_boxes(gray,lines,spacing):
        cx=x+w/2
        if geometry['left']<cx<geometry['right']:
            dotted=nearby_dot(ink,x+w+1,y+h*.3,spacing*.6,spacing*.6,spacing)
            events.append(dict(x=cx,beat=TabBeat(duration=4,dotted=dotted),confidence=.8))
    for x,y,w,h,area in stats[1:]:
        if not stems:
            break
        cx=x+w/2
        if not geometry['left']+5 < cx < geometry['right']-5 or area < 25:
            continue
        if spacing*.25 <= h < spacing*.48 and spacing*.25 <= w <= spacing*.8 and w/h < 1.5:
            if any(abs(cx-e['x'])<spacing*.4 for e in events):
                continue
            if lines[0] <= y <= lines[-2] and w > h*.65:
                events.append(dict(x=cx,beat=TabBeat(duration=8),confidence=.8))
    events.sort(key=lambda event:event['x'])
    for first, second in zip(events,events[1:]):
        for note in first['beat'].notes:
            if note.kind == 'normal' and any(target.string == note.string and target.kind == 'normal'
                                             and target.fret != note.fret for target in second['beat'].notes):
                if visible_slide(gray,lines[note.string-1],first['x'],second['x'],spacing,lines[-1],lines[0]):
                    note.slide = True
                    note.legato_slide = slide_has_curve(gray,lines[note.string-1],first['x'],second['x'],spacing)
                elif visible_hammer(gray,lines[note.string-1],first['x'],second['x'],spacing,lines[-1]):
                    note.hammer = True
        for note in first['beat'].notes:
            if note.kind=='dead' or note.slide or note.hammer:
                continue
            if any(target.string==note.string and target.kind in ('normal','tie') for target in second['beat'].notes):
                continue
            bar_end=next((x for x in geometry['bars'] if x>first['x']),geometry['right'])
            end=min(second['x'],bar_end+spacing*.3,first['x']+spacing*2.2)
            direction=visible_slide(gray,lines[note.string-1],first['x'],end,spacing,lines[-1],lines[0],end_depth=.85)
            if direction:
                note.slide_out=direction
    if events:
        last = events[-1]
        if geometry['right']-last['x'] < spacing*4:
            for note in last['beat'].notes:
                if note.kind == 'normal' and visible_slide(gray,lines[note.string-1],last['x'],
                                                          geometry['right']+spacing*.3,spacing,lines[-1],lines[0]):
                    note.slide = True
    number=int(row.get('start_number',1))
    measures=[]
    for left,right in zip(geometry['bars'],geometry['bars'][1:]):
        if right-left < spacing*2:
            continue
        selected=[event for event in events if left<event['x']<right]
        issues=['小节编号按谱行顺序暂定，请对照原图核对是否有跳段。','拍号暂按 4/4，需人工确认；未自动补音凑拍。']
        rests=[(x,y,w,h) for x,y,w,h,area in stats[1:] if left<x+w/2<right
               and lines[0]<=y<=lines[-1] and spacing*.55<w<spacing*1.6
               and spacing*.2<h<spacing*.65 and 1.4<w/h<4 and area>w*h*.65]
        # Cursor edges may create rhythm-like marks in an otherwise empty bar.
        # A filled whole-rest block with no fret figures is stronger evidence.
        if rests and not any(left<c['x_center']<right for c in glyphs):
            selected=[dict(x=left+(right-left)/2,beat=TabBeat(duration=1),confidence=.8)]
        elif not selected:
            if not rests:
                figures = [c for c in glyphs if left<c['x_center']<right]
                if len(figures)==1 and figures[0]['text'].lower() in ('x','×'):
                    figure = figures[0]
                    selected=[dict(x=figure['x_center'],beat=TabBeat(duration=1,
                                   notes=[TabNote(string=figure['string'],fret=0,kind='dead')]),confidence=figure['confidence'])]
                    used.add(glyphs.index(figure))
                    issues.append('此小节为无符干的全音符闷音 X，请核对。')
                else:
                    continue
            else:
                selected=[dict(x=left+(right-left)/2,beat=TabBeat(duration=1),confidence=.8)]
        rest_boxes = quarter_rest_boxes(gray,lines,spacing)
        unused=[c for i,c in enumerate(glyphs) if i not in used and left<c['x_center']<right
                and not any(x <= c['x_center'] <= x+w and y <= c['y'] < y+h for x,y,w,h in rest_boxes)]
        if unused:
            issues.append('存在未归入节拍的小符号，可能是倚音或滑音标记，请核对。')
        if any(c['confidence']<.85 for c in glyphs if left<c['x_center']<right):
            issues.append('部分品位数字的 OCR 置信度偏低，请逐个校对。')
        beats=[event['beat'] for event in selected]
        if any(note.grace for beat in beats for note in beat.notes):
            issues.append('已识别小字倚音；演奏时长暂设为不占主拍的 32 分音符，请核对或调整。')
        measures.append(TabMeasure(number=number,beats=beats,source=row['id'],
                                   confidence=min(event['confidence'] for event in selected),issues=issues))
        number+=1
    if not measures:
        raise UnsupportedTabImage("未定位到可读取的小节与节拍")
    return RecognitionResult(measures=measures,warnings=['已使用本地弦线、数字 OCR 和符尾识别生成草稿，需人工核对；暂不完整支持反复、推弦和复杂连音。'])
