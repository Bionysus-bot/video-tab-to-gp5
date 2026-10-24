"""Read complete numbered bars from alternate video views, never fill beats."""
from pathlib import Path
import json

import cv2
import numpy as np

from app.models.score import Score
from app.services.combined_local import number_sequence, read_combined_local
from app.services.combined_tab import measure_regions
from app.services.image_io import imread, imwrite
from app.services.score_exporter import validate_score
from app.services.score_images import _line_peaks, _group_lines, notation_staves, bar_positions


def frame_row(image, name):
    """Dense digits interrupt long line masks; percentile contrast survives."""
    gray=cv2.cvtColor(image,cv2.COLOR_BGR2GRAY)
    margin=max(1,image.shape[1]//30)
    profile=np.percentile(gray[:,margin:-margin],75,axis=1).astype(np.float32).reshape(-1,1)
    contrast=(cv2.morphologyEx(profile,cv2.MORPH_CLOSE,np.ones((15,1),np.uint8))-profile)[:,0]
    groups=_group_lines(_line_peaks(contrast,3))
    uppers=notation_staves(image,groups)
    paired=[(lines,upper) for lines,upper in zip(groups,uppers) if upper]
    if len(paired)!=1:return None
    lines,upper=paired[0]
    return dict(id=name,source=name,source_row=1,strings=len(lines),layout='standard-tab',
                lines=lines,notation_lines=upper,bars=bar_positions(image,lines),
                width=image.shape[1],height=image.shape[0])


def index_frame_views(frames, roi, output, on_progress=None, max_views=70):
    """Index actual printed anchors; timestamps do not imply bar numbers."""
    output=Path(output);output.mkdir(parents=True,exist_ok=True)
    frames=sorted(Path(p) for p in frames)
    stride=max(1,int(np.ceil(len(frames)/max_views)))
    views=[]
    x,y,w,h=(int(roi[k]) for k in ('x','y','width','height'))
    if min(x,y)<0 or min(w,h)<1:raise ValueError('视频谱面选区无效')
    for index,path in enumerate(frames[::stride]):
        image=imread(path)
        if image is None or x+w>image.shape[1] or y+h>image.shape[0]:continue
        # Preserve a few pixels beside the selection: a clipped digit at the
        # viewport edge can otherwise disappear when two views are joined.
        padding=min(24,max(4,round(h*.06)))
        image=image[y:y+h,max(0,x-padding):min(image.shape[1],x+w+padding)]
        name=f'view-{path.stem}.png';row=frame_row(image,name)
        if row is None:continue
        numbers,anchors=number_sequence(image,row)
        # Two independent printed anchors are required for a video/PDF match.
        if not numbers or sum(a==n for a,n in zip(anchors,numbers))<2:continue
        row.update(measure_numbers=numbers,number_anchors=anchors)
        imwrite(output/name,image)
        views.append(dict(path=str(output/name),frame=path.name,row=row))
        if on_progress:on_progress(f'原视频帧索引 {index+1}/{len(frames[::stride])}：第 {numbers[0]}～{numbers[-1]} 小节')
    (output/'index.json').write_text(json.dumps(views,ensure_ascii=False,indent=2),encoding='utf-8')
    return views


def stitch_frame_views(views,output):
    """Keep separate full views and add only anchor-proven adjacent joins."""
    from app.services.score_continuity import join_fragments
    output=Path(output);output.mkdir(parents=True,exist_ok=True)
    groups={}
    for view in views:groups.setdefault(tuple(view['row']['measure_numbers']),[]).append(view)
    ordered=sorted(groups.values(),key=lambda group:group[0]['row']['measure_numbers'][0])
    joined=[]
    for a_group,b_group in zip(ordered,ordered[1:]):
        # The first sampled frame may contain a transition or playhead over a
        # digit. Try middle, early and late views; never copy another bar's notes.
        pairs=[]
        for index in (.5,0,1):
            left=a_group[round((len(a_group)-1)*index)];right=b_group[round((len(b_group)-1)*index)]
            if (left['path'],right['path']) in pairs:continue
            pairs.append((left['path'],right['path']))
            a,b=imread(Path(left['path'])),imread(Path(right['path']))
            result,_=join_fragments(a,left['row'],b,right['row'])
            if result is None:continue
            image,row=result;name=f'joined-{Path(left["path"]).stem}-{Path(right["path"]).stem}.png'
            row['id']=name;imwrite(output/name,image)
            joined.append(dict(path=str(output/name),frame=left['frame']+' + '+right['frame'],row=row))
    return views+joined


def recover_measures(score, targets, views, output, on_progress=None):
    """Return a new score and provenance. Only requested invalid bars change."""
    output=Path(output);output.mkdir(parents=True,exist_ok=True)
    candidate=score.model_copy(deep=True);evidence=[];readings={}
    targets=set(targets)
    def signature(measure):
        return [(b.duration,b.dotted,b.triplet,[(n.string,n.fret,n.kind=='dead') for n in b.notes]) for b in measure.beats]
    for number in sorted(targets):
        current=next((m for m in candidate.measures if m.number==number),None)
        if current:
            preceding=next((m for m in reversed(candidate.measures) if m.number<number),None)
            context=Score(settings_confirmed=True,tuning=score.tuning,measures=([preceding] if preceding else [])+[current])
            if not any(e['severity']=='error' and e['measure']==number for e in validate_score(context,require_review=False)):
                continue
        possible=[]
        for view in views:
            row=view['row'];numbers=row['measure_numbers']
            if len(row['lines'])!=len(score.tuning):continue
            regions=measure_regions(row)
            if number in numbers:bounds=regions[numbers.index(number)]
            elif number==numbers[0]-1:bounds=(0,regions[0][0])
            elif number==numbers[-1]+1:bounds=(regions[-1][1],row['width'])
            else:continue
            margin=min(bounds[0],row['width']-bounds[1])
            possible.append((margin,view,bounds))
        for _,view,bounds in sorted(possible,key=lambda item:item[0],reverse=True)[:3]:
            row=view['row'];key=view['path']
            if key not in readings:
                first=row['measure_numbers'][0]
                preceding=next((m for m in reversed(candidate.measures) if m.number<first),None)
                readings[key]=read_combined_local(Path(key),dict(row,start_number=first,
                    previous_notes=[n.model_dump() for n in preceding.beats[-1].notes] if preceding else []),score.tuning)
                (output/(Path(key).stem+'.json')).write_text(readings[key].model_dump_json(indent=2),encoding='utf-8')
            agreements=0
            for other in readings[key].measures:
                if other.number==number or any(b.unresolved for b in other.beats):continue
                original=next((m for m in score.measures if m.number==other.number),None)
                if original and not any(b.unresolved for b in original.beats) and signature(original)==signature(other):agreements+=1
            # A PDF imported into a video project may be a different song.
            # Printed numbers alone are insufficient evidence of provenance.
            if agreements<2:continue
            measure=next((m for m in readings[key].measures if m.number==number),None)
            if measure is None:continue
            measure=measure.model_copy(deep=True)
            # Validate in musical context, including the preceding real pitch.
            preceding=next((m for m in reversed(candidate.measures) if m.number<number),None)
            check=Score(settings_confirmed=True,tuning=score.tuning,measures=([preceding] if preceding else [])+[measure])
            errors=[e for e in validate_score(check,require_review=False) if e['severity']=='error' and e['measure']==number]
            if errors:continue
            if current:measure.source=current.source
            else:measure.source=next((m.source for m in candidate.measures if m.number>number),'')
            measure.issues.append(f'原视频完整画面复读：{view["frame"]}；至少两个印刷小节号支持编号对应。')
            measure.reviewed=False
            candidate.measures=[m for m in candidate.measures if m.number!=number]+[measure]
            candidate.measures.sort(key=lambda m:m.number)
            image=imread(Path(key));left,right=bounds
            name=f'bar-{number}-{Path(view["frame"]).stem}.png'
            imwrite(output/name,image[:,max(0,left-5):min(image.shape[1],right+6)])
            evidence.append(dict(number=number,frame=view['frame'],image=name,bounds=list(bounds),
                                 anchors=row['number_anchors'],numbers=row['measure_numbers']))
            if on_progress:on_progress(f'第 {number} 小节：原视频完整画面补读通过（{len(measure.beats)} 个拍位）')
            break
        else:
            if on_progress:on_progress(f'第 {number} 小节：原视频候选尚未通过校验，保留原值')
    (output/'evidence.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2),encoding='utf-8')
    return candidate,evidence
