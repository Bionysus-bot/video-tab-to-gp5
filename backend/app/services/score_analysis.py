"""Visual evidence for fresh local candidates; never changes the saved score."""
import cv2
import numpy as np

from app.services.combined_local import read_combined_local
from app.services.combined_tab import measure_regions
from app.services.image_io import imread,imwrite


def analyze_row(path,row,tuning,output):
    diagnostics={}
    result=read_combined_local(path,row,tuning,diagnostics)
    image=imread(path)
    diagnostics['fragments']=[dict(side=f.side,bounds=f.bounds,candidate=f.measure.model_dump(),complete=f.complete)
                              for f in result.fragments]
    canvas=cv2.resize(image,None,fx=2,fy=2,interpolation=cv2.INTER_CUBIC)
    for measure in diagnostics['measures']:
        a,b=measure['bounds']
        cv2.putText(canvas,f"bar {measure['number']}",(round(a*2)+2,18),cv2.FONT_HERSHEY_SIMPLEX,.45,(180,80,10),1,cv2.LINE_AA)
    for event in diagnostics['events']:
        color=(30,30,220) if event['unresolved'] else (0,125,220) if event['confidence']<.85 else (20,140,20)
        for x,y,w,h in event['boxes']:
            cv2.rectangle(canvas,(round(x*2),round(y*2)),(round((x+w)*2),round((y+h)*2)),color,1)
        if event['head']:
            x,y=event['head'];cv2.circle(canvas,(round(x*2),round(y*2)),5,(220,100,0) if event['head_detected'] else (190,40,180),1)
            cv2.line(canvas,(round(x*2),round(y*2)),(round(event['x']*2),round(row['lines'][0]*2)),color,1)
        label=f"{event['measure']}.{event['beat_index']} /{event['duration']}"
        cv2.putText(canvas,label,(round(event['x']*2)-20,min(canvas.shape[0]-4,round((row['lines'][-1]+20)*2))),cv2.FONT_HERSHEY_SIMPLEX,.35,color,1,cv2.LINE_AA)
    for fragment in diagnostics.get('fragments',[]):
        a,b=fragment['bounds'];cv2.rectangle(canvas,(round(a*2),2),(round(b*2)-2,canvas.shape[0]-2),(20,140,20) if fragment['complete'] else (0,150,230),2)
    imwrite(output,canvas)
    diagnostics['candidate']=result.model_dump()
    return diagnostics
