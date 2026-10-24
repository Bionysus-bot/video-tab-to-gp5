"""Runs inside the frozen EXE, not the development Python environment."""
import json,time,urllib.request,urllib.error,uuid,io

def check(url,token,data_dir):
    def call(path,data=None,content='application/json'):
        req=urllib.request.Request(url+path,data=data,headers={'X-Pujian-Session':token,'Content-Type':content})
        with urllib.request.urlopen(req,timeout=90) as r:return json.load(r)
    try:urllib.request.urlopen(url+'/api/projects',timeout=5)
    except urllib.error.HTTPError as exc:assert exc.code==403
    else:raise AssertionError('Unauthenticated access accepted')
    from PIL import Image
    import cv2,numpy as np
    import guitarpro
    from pathlib import Path
    image=np.full((360,1000,3),245,np.uint8)
    for y in (80,105,130,155,180):cv2.line(image,(60,y),(940,y),(175,175,175),1)
    for x in (60,940):cv2.line(image,(x,80),(x,180),(180,180,180),1)
    for x in (150,350,550,750):
        cv2.putText(image,'7',(x-8,190),cv2.FONT_HERSHEY_SIMPLEX,.8,(40,40,40),2)
        cv2.line(image,(x,204),(x,241),(50,50,50),2)
    pdf=io.BytesIO();Image.fromarray(image).save(pdf,'PDF',resolution=72)
    pid=call('/api/projects',b'{}')['id']
    boundary='smoke'+uuid.uuid4().hex
    body=(f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="desktop-test.pdf"\r\nContent-Type: application/pdf\r\n\r\n'.encode()+pdf.getvalue()+f'\r\n--{boundary}--\r\n'.encode())
    source=call(f'/api/projects/{pid}/inputs/pdf',body,'multipart/form-data; boundary='+boundary)
    job=call(f'/api/projects/{pid}/conversion-jobs',json.dumps(dict(source='pdf',input_id=source['id'],layout='tab',tuning=[43,38,33,28,23],recover=False,review=False)).encode())
    deadline=time.monotonic()+180
    while job['status'] not in ('completed','failed','partial','cancelled','interrupted'):
        assert time.monotonic()<deadline,'Recognition deadline exceeded'
        time.sleep(.5);job=call(f'/api/projects/{pid}/conversion-jobs/{job["id"]}')
    assert job['status']=='completed',job
    artifact=job['artifact']
    req=urllib.request.Request(url+f'/api/projects/{pid}/artifacts/{artifact["id"]}/download',headers={'X-Pujian-Session':token})
    path=data_dir/'desktop-test.gp5'
    with urllib.request.urlopen(req,timeout=20) as r:path.write_bytes(r.read())
    track=guitarpro.parse(str(path)).tracks[0]
    assert [s.value for s in track.strings]==[43,38,33,28,23]
    notes=[(n.string,n.value) for m in track.measures for v in m.voices for b in v.beats for n in b.notes]
    assert notes==[(5,7)]*4,notes
    (data_dir/'smoke-result.json').write_text(json.dumps(dict(ok=True,project=pid,notes=notes,strings=5)),encoding='utf-8')
