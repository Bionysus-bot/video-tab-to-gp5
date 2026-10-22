"""Music-symbol geometry and monotonic TAB alignment; no meter-based guesses."""
import cv2
import numpy as np


def attach_heads(gray, stems, staff, left, right, spacing, tab_centers=()):
    top=max(0,round(staff[0]-spacing*3));bottom=min(gray.shape[0],round(staff[-1]+spacing*3))
    ink=(gray[top:bottom,left:right]<145).astype(np.uint8)
    kernel=cv2.getStructuringElement(cv2.MORPH_ELLIPSE,(max(3,round(spacing*.65)),max(3,round(spacing*.25))))
    heads=cv2.morphologyEx(ink,cv2.MORPH_OPEN,kernel)
    _,_,stats,centers=cv2.connectedComponentsWithStats(heads)
    candidates=[]
    for (x,y,w,h,area),(cx,cy) in zip(stats[1:],centers[1:]):
        if spacing*.55<w<spacing*1.8 and spacing*.2<h<spacing*1.05 and area>spacing*spacing*.16:
            candidates.append((float(cx+left),float(cy+top)))
    events=[]
    for stem in stems:
        if not left+3<stem['x']<right-3:continue
        near=[(x,y) for x,y in candidates if abs(x-stem['x'])<spacing*.9
              and min(abs(y-stem['top']),abs(y-stem['bottom']))<spacing*.9]
        if near:
            x,y=min(near,key=lambda p:min(abs(p[1]-stem['top']),abs(p[1]-stem['bottom'])))
            events.append(dict(stem,head=[x,y],down=abs(y-stem['top'])<abs(y-stem['bottom']),head_detected=True))
        elif tab_centers:
            center=min(tab_centers,key=lambda x:min(abs(x-stem['x']-spacing*.55),abs(x-stem['x']+spacing*.55)))
            if abs(center-stem['x'])<spacing*1.1:
                down=center>=stem['x']
                events.append(dict(stem,head=[center,stem['top'] if down else stem['bottom']],down=down,head_detected=False))
    return sorted(events,key=lambda e:e['head'][0])


def align_events(centers,events,spacing):
    """One ordered head/stem event per TAB onset; a stem cannot be reused."""
    n,m=len(centers),len(events);cost=np.full((n+1,m+1),np.inf);cost[0,0]=0;back={}
    for i in range(n+1):
        for j in range(m+1):
            options=[]
            if i:options.append((cost[i-1,j]+1.8,(i-1,j),'skip-tab'))
            if j:options.append((cost[i,j-1]+1.8,(i,j-1),'skip-head'))
            if i and j:
                distance=abs(centers[i-1]-events[j-1]['head'][0])/spacing
                if distance<1.7:options.append((cost[i-1,j-1]+distance,(i-1,j-1),'match'))
            if options:
                value,prev,kind=min(options,key=lambda item:item[0]);cost[i,j]=value;back[i,j]=(prev,kind)
    matched={};i,j=n,m
    while (i,j)!=(0,0):
        (pi,pj),kind=back[i,j]
        if kind=='match':matched[i-1]=events[j-1]
        i,j=pi,pj
    return matched


def connect_beams(gray,events,spacing):
    """Confirm beam groups at several positions between consecutive stems."""
    for event in events:event['beam_group']=0
    for left,right in zip(events,events[1:]):
        distance=right['x']-left['x']
        if not spacing<distance<spacing*12 or left['down']!=right['down']:continue
        end='bottom' if left['down'] else 'top'
        if abs(left[end]-right[end])>spacing*2:continue
        observations=[]
        for t in (.2,.35,.5,.65,.8):
            x=round(left['x']+t*distance);y=round(left[end]*(1-t)+right[end]*t)
            y0,y1=(y-round(spacing*2.1),y+3) if left['down'] else (y-3,y+round(spacing*2.1))
            ys=np.flatnonzero(gray[max(0,y0):min(gray.shape[0],y1),x]<130)
            runs=np.split(ys,np.where(np.diff(ys)>1)[0]+1)
            observations.append(sum(spacing*.1<=len(run)<=spacing*.85 for run in runs))
        count=int(np.median(observations))
        if 1<=count<=4 and observations.count(count)>=3:
            left['beam_group']=max(left['beam_group'],count)
            right['beam_group']=max(right['beam_group'],count)


def template_refine(figures,image):
    """Corroborate weak OCR with multiple independent same-row glyph examples."""
    def shape(cell):
        x,y,w,h=(round(cell[k]) for k in ('x','y','w','h'))
        crop=cv2.cvtColor(image[y:y+h,x:x+w],cv2.COLOR_BGR2GRAY)
        return cv2.resize((crop<175).astype(np.float32),(24,32)).ravel()
    bank={}
    for cell in figures:
        if len(cell['text'])==1 and cell['text'].isdigit() and cell['confidence']>=.95 and not cell['parenthesized']:
            bank.setdefault(cell['text'],[]).append(shape(cell))
    for cell in figures:
        if not cell['text'].isdigit() or cell['confidence']>=.85 or cell['parenthesized']:continue
        sample=shape(cell);scores=[]
        for text,examples in bank.items():
            if len(examples)<2:continue
            similarities=sorted((float(np.dot(sample,e)/(np.linalg.norm(sample)*np.linalg.norm(e)+1e-8)) for e in examples),reverse=True)
            scores.append((min(similarities[:2]),text))
        scores.sort(reverse=True)
        if scores and scores[0][0]>.93 and (len(scores)==1 or scores[0][0]-scores[1][0]>.08) and scores[0][1]==cell['text']:
            cell['template_score']=scores[0][0]
            cell['confidence']=max(float(cell['confidence']),scores[0][0])
