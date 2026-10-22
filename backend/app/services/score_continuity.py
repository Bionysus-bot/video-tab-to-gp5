"""Join only fragments identified as the same bar by printed-number anchors."""
from pathlib import Path

import cv2
import numpy as np

from app.services.combined_local import number_sequence
from app.services.combined_tab import measure_regions
from app.services.image_io import imread, imwrite


def staff_extent(image, row):
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    coverage = np.mean(gray[row['lines']] < 240, axis=0)
    xs = np.flatnonzero(coverage >= .75)
    return (int(xs[0]), int(xs[-1])+1) if len(xs) else (0, image.shape[1])


def join_fragments(left_image, left_row, right_image, right_row):
    """Return extended image/metadata, or a reason why the join is unproven."""
    left_regions, right_regions = measure_regions(left_row), measure_regions(right_row)
    ln, rn = left_row.get('measure_numbers', []), right_row.get('measure_numbers', [])
    if ln and rn and ln[-1]+1 >= rn[0]:
        return None, '后行已覆盖尾部小节，保留完整版本，不拼接重复片段。'
    if not left_regions or not right_regions or not ln or not rn or ln[-1]+1 != rn[0]-1:
        return None, '相邻边缘的小节编号不能对应，未拼接；可能缺少截图。'
    spacing = float(np.median(np.diff(left_row['lines'])))
    ratio = spacing / float(np.median(np.diff(right_row['lines'])))
    shift = left_row['lines'][0] - right_row['lines'][0] * ratio
    pairs = zip(left_row['notation_lines']+left_row['lines'], right_row['notation_lines']+right_row['lines'])
    if not .9 < ratio < 1.1 or any(abs(a-(b*ratio+shift)) > max(2,spacing*.2) for a,b in pairs):
        return None, '相邻谱行的上下谱位置不匹配，未拼接。'
    _, end = staff_extent(left_image,left_row)
    begin, _ = staff_extent(right_image,right_row)
    edge = right_regions[0][0]
    if end-left_regions[-1][1] < spacing*2 or edge-begin < spacing*2:
        return None, '边缘缺少足够的谱面片段，未拼接。'
    prefix = right_image[:,begin:edge+2]
    prefix = cv2.warpAffine(prefix,np.array([[ratio,0,0],[0,ratio,shift]],np.float32),
                            (round(prefix.shape[1]*ratio),left_image.shape[0]),borderValue=(255,255,255))
    joined = np.concatenate([left_image[:,:end],prefix],axis=1)
    closing = end+round((edge-begin)*ratio)
    metadata = {**left_row, 'width': joined.shape[1],
                'bars': left_row['bars']+[closing],
                'measure_bounds': left_regions+[(left_regions[-1][1],closing)],
                'measure_numbers': ln+[ln[-1]+1],
                'joined_from': [left_row['id'],right_row['id']]}
    return (joined,metadata), ''


def stitch_rows(directory: Path, rows: list[dict]):
    warnings = []
    originals = {r['id']: imread(directory/r['id']) for r in rows if r.get('layout') == 'standard-tab'}
    floor = None
    for row in rows:
        if row['id'] in originals:
            if floor is not None:
                row['number_floor'] = floor
            numbers, anchors = number_sequence(originals[row['id']],row)
            row.update(measure_numbers=numbers,number_anchors=anchors)
            if numbers:
                floor = numbers[-1]+1
    for index in range(len(rows)-1):
        row, following = rows[index:index+2]
        if row.get('excluded') or following.get('excluded') or row['id'] not in originals or following['id'] not in originals:
            continue
        joined, reason = join_fragments(originals[row['id']],row,originals[following['id']],following)
        if joined is None:
            row['continuity_issue'] = reason
            warnings.append(f"{row['id']} → {following['id']}：{reason}")
            continue
        image, metadata = joined
        old_id = row['id']
        name = f"{Path(old_id).stem}_joined.png"
        imwrite(directory/name,image)
        metadata['id'] = name
        row.update(metadata)
        warnings.append(f"{old_id}：已拼回第 {row['measure_numbers'][-1]} 小节（后半来自 {following['id']} 行首）。")
    return warnings
