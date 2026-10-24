"""Music-symbol geometry and monotonic TAB alignment; no meter-based guesses."""
import cv2
import numpy as np


def visible_tie_curve(gray, first, second, spacing):
    """Require a curved ink component between two level, independently found heads."""
    x1,y1=first;x2,y2=second
    if x2-x1<spacing*2 or abs(y2-y1)>spacing*.35:return False
    left=max(0,round(x1+spacing*.45));right=min(gray.shape[1],round(x2-spacing*.45))
    top=max(0,round(y1-spacing*2));bottom=min(gray.shape[0],round(y1+spacing*2))
    ink=(gray[top:bottom,left:right]<160).astype(np.uint8)
    if ink.size==0:return False
    lines=cv2.morphologyEx(ink,cv2.MORPH_OPEN,np.ones((1,max(8,round(spacing*3))),np.uint8))
    stems=cv2.morphologyEx(ink,cv2.MORPH_OPEN,np.ones((max(8,round(spacing*1.5)),1),np.uint8))
    ink=ink & (1-lines) & (1-stems)
    count,components,stats,_=cv2.connectedComponentsWithStats(ink)
    for label in range(1,count):
        x,y,w,h,area=stats[label]
        if w<(right-left)*.55 or not spacing*.12<h<spacing*1.4 or area/w>spacing*.4:continue
        ys,xs=np.where(components==label)
        unique=np.unique(xs)
        if len(unique)<w*.65:continue
        medians=np.array([np.median(ys[xs==px]) for px in unique])
        t=(unique-unique.min())/max(1,np.ptp(unique))
        coefficients=np.polyfit(t,medians,2)
        fit=np.polyval(coefficients,t)
        ends=np.polyval(coefficients,[0,1]);middle=np.polyval(coefficients,.5)
        sag=middle-float(np.mean(ends))
        absolute=medians+top
        above=np.max(absolute)<y1-spacing*.15
        below=np.min(absolute)>y1+spacing*.15
        if abs(ends[1]-ends[0])<spacing*.35 and spacing*.12<abs(sag)<spacing and np.sqrt(np.mean((medians-fit)**2))<spacing*.15 and ((below and sag>0) or (above and sag<0)):
            return True
    return False


def link_row_ties(measures,events,gray,spacing):
    traces={id(e['beat']):e for e in events}
    previous=None;last_number=None
    for measure in measures:
        if last_number is not None and measure.number!=last_number+1:previous=None
        for beat in measure.beats:
            event=traces.get(id(beat))
            signature=sorted((n.string,n.fret) for n in beat.notes if n.kind!='dead')
            if previous and signature and signature==previous[0] and not beat.unresolved and event and event.get('head_detected') and visible_tie_curve(gray,previous[1],event['head'],spacing):
                for note in beat.notes:
                    if note.kind=='normal':note.kind='tie'
                event['tie_evidence']='visible_curve'
            previous=(signature,event['head']) if signature and event and event.get('head_detected') and not beat.unresolved else None
        last_number=measure.number


def attach_heads(gray, stems, staff, left, right, spacing, tab_centers=(), seams=()):
    top=max(0,round(staff[0]-spacing*3));bottom=min(gray.shape[0],round(staff[-1]+spacing*3))
    ink=(gray[top:bottom,left:right]<145).astype(np.uint8)
    kernel=cv2.getStructuringElement(cv2.MORPH_ELLIPSE,(max(3,round(spacing*.65)),max(3,round(spacing*.25))))
    heads=cv2.morphologyEx(ink,cv2.MORPH_OPEN,kernel)
    _,_,stats,centers=cv2.connectedComponentsWithStats(heads)
    candidates=[]
    for (x,y,w,h,area),(cx,cy) in zip(stats[1:],centers[1:]):
        if spacing*.55<w<spacing*1.8 and spacing*.2<h<spacing*1.05 and area>spacing*spacing*.16:
            candidates.append((float(cx+left),float(cy+top)))
    partial=[]
    if seams:
        small=cv2.morphologyEx(ink,cv2.MORPH_OPEN,cv2.getStructuringElement(cv2.MORPH_ELLIPSE,
            (max(3,round(spacing*.3)),max(3,round(spacing*.25)))))
        _,_,stats,centers=cv2.connectedComponentsWithStats(small)
        for (x,y,w,h,area),(cx,cy) in zip(stats[1:],centers[1:]):
            if (spacing*.28<w<spacing*.9 and spacing*.3<h<spacing*1.15 and area>spacing*spacing*.08
                    and any(abs(cx+left-s)<spacing for s in seams)):
                partial.append((float(cx+left),float(cy+top)))
    events=[]
    for stem in stems:
        if not left+3<stem['x']<right-3:continue
        partial_match=False
        near=[(x,y) for x,y in candidates if abs(x-stem['x'])<spacing*.9
              and min(abs(y-stem['top']),abs(y-stem['bottom']))<spacing*.9]
        if not near:
            near=[(x,y) for x,y in partial if abs(x-stem['x'])<spacing*.7
                  and min(abs(y-stem['top']),abs(y-stem['bottom']))<spacing*.9]
            partial_match=bool(near)
        if near:
            x,y=min(near,key=lambda p:min(abs(p[1]-stem['top']),abs(p[1]-stem['bottom'])))
            events.append(dict(stem,head=[x,y],down=abs(y-stem['top'])<abs(y-stem['bottom']),head_detected=True,head_partial=partial_match))
        elif tab_centers:
            center=min(tab_centers,key=lambda x:min(abs(x-stem['x']-spacing*.55),abs(x-stem['x']+spacing*.55)))
            if abs(center-stem['x'])<spacing*1.1:
                down=center>=stem['x']
                events.append(dict(stem,head=[center,stem['top'] if down else stem['bottom']],down=down,head_detected=False))
    # A viewport seam may remove the thin stem while leaving its head and
    # connected beams. Accept that onset only with a detected head, a visible
    # TAB figure and repeated beam evidence at the neighbouring beam endpoint.
    for x,y in candidates+partial:
        if not any(abs(x-s)<spacing for s in seams):continue
        if not tab_centers or min(abs(x-c) for c in tab_centers)>spacing*.8:continue
        if any(abs(x-e['head'][0])<spacing*.65 for e in events):continue
        neighbours=[e for e in events if abs(e['head'][1]-y)<spacing*2.2 and abs(e['head'][0]-x)<spacing*5]
        if not neighbours:continue
        neighbour=min(neighbours,key=lambda e:abs(e['head'][0]-x));down=neighbour['down']
        end=neighbour['bottom' if down else 'top']
        if abs(neighbour['head'][1]-y)>spacing*.7:
            end+=y-neighbour['head'][1]
        if not spacing*2<abs(end-y)<spacing*5:continue
        stem_x=round(x+(-.55 if down else .55)*spacing)
        counts=[]
        for offset in (-.9,-.7,-.5,.5,.7,.9):
            xx=stem_x+round(offset*spacing)
            if not 0<=xx<gray.shape[1]:continue
            y0,y1=(round(end-spacing*2.1),round(end+4)) if down else (round(end-4),round(end+spacing*2.1))
            ys=np.flatnonzero(gray[max(0,y0):min(gray.shape[0],y1),xx]<130)
            runs=np.split(ys,np.where(np.diff(ys)>1)[0]+1)
            counts.append(sum(spacing*.1<=len(run)<=spacing*.85 for run in runs))
        supported=[v for v in set(counts) if 1<=v<=3 and counts.count(v)>=2]
        if not supported:continue
        events.append(dict(x=stem_x,top=round(y if down else end),bottom=round(end if down else y),
            head=[x,y],down=down,head_detected=True,stem_inferred=True))
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


def refine_fret_crops(figures,image,spacing,heads,read_text):
    """Recover source-pixel readings and join digits at one notation onset."""
    removed=set()
    ordered=sorted(enumerate(figures),key=lambda item:(item[1]['string'],item[1]['x']))
    for (i,a),(j,b) in zip(ordered,ordered[1:]):
        if i in removed or j in removed or a['string']!=b['string']:continue
        if a['parenthesized'] or b['parenthesized']:continue
        gap=b['x']-a['x']-a['w']
        if not 0<=gap<=spacing*.25 or min(a['h'],b['h'])/max(a['h'],b['h'])<.65:continue
        if (a['text'] or a.get('alternative')) not in ('1','2','3'):continue
        left=a['x'];right=b['x']+b['w'];top=min(a['y'],b['y']);bottom=max(a['y']+a['h'],b['y']+b['h'])
        onsets=[e for e in heads if left-spacing*.3<e['head'][0]<right+spacing*.3]
        if len(onsets)!=1 or abs(onsets[0]['head'][0]-(left+right)/2)>spacing*.7:continue
        crop=image[max(0,top-3):bottom+3,left:right]
        gray=cv2.cvtColor(crop,cv2.COLOR_BGR2GRAY)
        variants=[crop,cv2.cvtColor(np.where(gray<180,0,255).astype(np.uint8),cv2.COLOR_GRAY2BGR)]
        readings=read_text([cv2.copyMakeBorder(c,8,8,8,8,cv2.BORDER_CONSTANT,value=(255,255,255)) for c in variants])
        if readings[0][0]==readings[1][0] and len(readings[0][0])==2 and readings[0][0].isdigit() and int(readings[0][0])<=36 and min(v[1] for v in readings)>.8:
            a.update(x=left,y=top,w=right-left,h=bottom-top,x_center=(left+right)/2,
                     text=readings[0][0],confidence=float(min(v[1] for v in readings)),alternative=readings[1][0])
            removed.add(j)
    figures=[c for i,c in enumerate(figures) if i not in removed]
    # A merged two-digit glyph can be confidently read as its right-hand zero.
    # Revisit wide single digits, but only at one independently detected onset.
    for c in figures:
        if c['parenthesized'] or not c['text'].isdigit() or len(c['text'])!=1 or c['w']<c['h']*.9:
            continue
        left,right=c['x'],c['x']+c['w']
        onsets=[e for e in heads if left-spacing*.3<e['head'][0]<right+spacing*.3]
        if len(onsets)!=1:continue
        x,y,w,h=(c[k] for k in ('x','y','w','h'))
        crop=image[max(0,y-3):y+h+3,max(0,x-2):x+w+2]
        gray=cv2.cvtColor(crop,cv2.COLOR_BGR2GRAY)
        variants=[crop,cv2.cvtColor(np.where(gray<180,0,255).astype(np.uint8),cv2.COLOR_GRAY2BGR)]
        readings=read_text([cv2.copyMakeBorder(v,8,8,8,8,cv2.BORDER_CONSTANT,value=(255,255,255)) for v in variants])
        if len(readings)==2 and readings[0][0]==readings[1][0] and len(readings[0][0])==2 and readings[0][0].isdigit() and int(readings[0][0])<=36 and min(v[1] for v in readings)>.85:
            c.update(text=readings[0][0],confidence=float(min(v[1] for v in readings)),alternative=readings[1][0])
    weak=[c for c in figures if not c['text'] or c['confidence']<.35]
    variants=[]
    for c in weak:
        x,y,w,h=(c[k] for k in ('x','y','w','h'))
        crop=image[max(0,y-3):y+h+3,x:x+w];gray=cv2.cvtColor(crop,cv2.COLOR_BGR2GRAY)
        variants.extend([cv2.copyMakeBorder(v,8,8,8,8,cv2.BORDER_CONSTANT,value=(255,255,255))
            for v in (crop,cv2.cvtColor(np.where(gray<180,0,255).astype(np.uint8),cv2.COLOR_GRAY2BGR))])
    readings=read_text(variants)
    for i,c in enumerate(weak):
        a,b=readings[i*2:i*2+2]
        if a[0].isdigit() and int(a[0])<=36 and a[1]>=.5:
            agrees=a[0]==b[0] and b[1]>=.5
            # A single grayscale reading remains an uncertain candidate;
            # thresholding a faint seven to "1" must not replace that reading.
            c.update(text=a[0],confidence=float(min(a[1],b[1]) if agrees else min(.34,a[1])))
    return figures


def corroborate_pitches(events, staff_top, spacing, tuning):
    """Use repeated same-row staff pitches to check a weak TAB digit.

    No clef/key is assumed. Conflicting pitches at the same staff position
    disable that position; only a detected head and one visible TAB string
    can supply an alternative to an uncertain OCR reading.
    """
    from app.models.score import TabNote
    def slot(event):
        if not event.get('head_detected') or not event.get('head'):return None
        position=(event['head'][1]-staff_top)/(spacing*.5)
        tolerance=.4 if event.get('head_partial') else .3
        return round(position) if abs(position-round(position))<tolerance else None
    bank={}
    for event in events:
        beat=event['beat'];key=slot(event)
        if key is None or len(beat.notes)!=1 or 'pitch' in beat.unresolved:continue
        note=beat.notes[0]
        if note.kind=='dead' or event['confidence']<.8:continue
        bank.setdefault(key,[]).append(tuning[note.string-1]+note.fret)
    for event in events:
        beat=event['beat'];key=slot(event);strings=event.get('tab_strings',[])
        pitches=bank.get(key,[])
        if (len(strings)!=1 or len(pitches)<2
                or len(set(pitches))!=1):continue
        string=strings[0];fret=pitches[0]-tuning[string-1]
        if not 0<=fret<=36:continue
        if 'pitch' not in beat.unresolved:
            if len(beat.notes)==1 and beat.notes[0].string==string and beat.notes[0].fret==fret:
                beat.pitch_evidence='staff'
                event['pitch_evidence']='same-row detected head pitch corroborates OCR'
            continue
        differs=beat.notes and any(n.string!=string or n.fret!=fret for n in beat.notes)
        if differs and event['confidence']>=.35:continue
        if not beat.notes or differs:beat.notes=[TabNote(string=string,fret=fret)]
        beat.unresolved.remove('pitch')
        beat.pitch_evidence='staff'
        event['pitch_evidence']='same-row detected head pitch and visible TAB string; >=2 agreeing examples'


def seam_digit_fragments(figures,normalized,lines,seams,spacing):
    """Keep visible partial digits near a known join; do not assign a pitch."""
    if not seams:return figures
    ink=(normalized<115).astype(np.uint8)
    ink[:max(0,round(lines[0]-spacing*.3))]=0
    ink[min(ink.shape[0],round(lines[-1]+spacing*.3)):]=0
    # A translucent playhead can erase the middle of a clipped seven. Join
    # its surviving cap and tail locally; keep the reading unresolved until
    # an actual notation head corroborates its pitch.
    connected=cv2.morphologyEx(ink,cv2.MORPH_CLOSE,np.ones((max(3,round(spacing*.65)),1),np.uint8))
    _,_,stats,_=cv2.connectedComponentsWithStats(connected)
    extra=[]
    for x,y,w,h,area in stats[1:]:
        center=x+w/2
        if not any(abs(center-s)<spacing*.7 for s in seams):continue
        if not (area>=6 and w>=2 and spacing*.15<=h<spacing*1.15 and ink[y:y+h,x:x+w].sum()>=6):continue
        string=int(np.argmin(abs(np.array(lines)-(y+h/2))))+1
        if abs(lines[string-1]-(y+h/2))>spacing*.3:continue
        if any(abs(c['x_center']-center)<spacing*.6 for c in figures):continue
        extra.append(dict(x=int(x),y=int(y),w=int(w),h=int(h),string=string,
            text='',alternative='',confidence=0.,x_center=center,parenthesized=False,seam_fragment=True))
    # If a staff line connects the two surviving strokes to a wide component,
    # inspect their column band with that line removed instead of discarding
    # the whole faint digit. Both its cap and tail must actually be visible.
    for seam in seams:
        x0=max(0,round(seam-spacing*.5));x1=min(ink.shape[1],round(seam+spacing*.5))
        for string,line in enumerate(lines,1):
            y0=max(0,round(line-spacing*.5));y1=min(ink.shape[0],round(line+spacing*.5))
            mask=ink[y0:y1,x0:x1].copy();mid=line-y0
            mask[max(0,mid-2):mid+3]=0
            ys,xs=np.nonzero(mask)
            if len(xs)<6 or not (ys.min()<mid-spacing*.15 and ys.max()>mid+spacing*.15):continue
            x=x0+int(xs.min());y=y0+int(ys.min());w=int(xs.max()-xs.min()+1);h=int(ys.max()-ys.min()+1)
            center=x+w/2
            if w>spacing*.8 or any(abs(c['x_center']-center)<spacing*.6 for c in figures+extra):continue
            extra.append(dict(x=x,y=y,w=w,h=h,string=string,text='',alternative='',confidence=0.,
                              x_center=center,parenthesized=False,seam_fragment=True))
    return figures+extra
