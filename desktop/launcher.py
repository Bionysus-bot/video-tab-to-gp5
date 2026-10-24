"""Windows desktop host. Existing web entry and user projects remain independent."""
import multiprocessing
import sys

if __name__ == '__main__':
    multiprocessing.freeze_support()

import argparse
import ctypes
import json
import logging
import os
from pathlib import Path
import secrets
import socket
import subprocess
import threading
import time
import urllib.request

BUNDLE = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parents[1]))
FROZEN = bool(getattr(sys, 'frozen', False))

def configure(data):
    data.mkdir(parents=True, exist_ok=True)
    os.environ['PYTHONIOENCODING']='utf-8'
    os.environ['PYTHONUTF8']='1'
    for name in ('stdout','stderr'):
        stream=getattr(sys,name)
        if stream is None:
            setattr(sys,name,(data/'process.log').open('a',encoding='utf-8',buffering=1))
        elif hasattr(stream,'reconfigure'):
            stream.reconfigure(encoding='utf-8',errors='replace')
    os.environ['PUJIAN_DATA_DIR'] = str(data)
    os.environ['PUJIAN_FRONTEND_DIR'] = str(BUNDLE/'frontend'/'dist')
    os.environ['PATH'] = str(BUNDLE/'tools') + os.pathsep + os.environ.get('PATH', '')
    if not FROZEN:sys.path.insert(0, str(BUNDLE/'backend'))
    logging.basicConfig(filename=data/'desktop.log',level=logging.INFO,encoding='utf-8')
    urllib.request.install_opener(urllib.request.build_opener(urllib.request.ProxyHandler({})))

def serve(port, token):
    import uvicorn
    from app.main import app
    from starlette.responses import JSONResponse, RedirectResponse
    from fastapi import Request
    @app.middleware('http')
    async def local_session(request: Request, call_next):
        if request.url.path == '/' and secrets.compare_digest(request.query_params.get('desktop_session', ''), token):
            response=RedirectResponse('/')
            response.set_cookie('pujian_session',token,httponly=True,samesite='strict')
            return response
        supplied=request.cookies.get('pujian_session','') or request.headers.get('X-Pujian-Session','')
        if not secrets.compare_digest(supplied,token):return JSONResponse({'detail':'Desktop session required'},status_code=403)
        return await call_next(request)
    server=uvicorn.Server(uvicorn.Config(app,host='127.0.0.1',port=port,log_config=None))
    @app.post('/desktop/shutdown')
    async def shutdown():
        from app.services import conversion_pipeline as pipeline
        with pipeline._live_lock:
            for item in pipeline._live.values():
                # Each live entry stores its cancellation event.
                item.set()
        server.should_exit=True
        return {'status':'stopping'}
    # The web app mounts static '/' last; keep desktop control ahead of that mount.
    app.router.routes.insert(0,app.router.routes.pop())
    server.run()

def request(url,token,data=None):
    req=urllib.request.Request(url,data=data,headers={'X-Pujian-Session':token,'Content-Type':'application/json'})
    with urllib.request.urlopen(req,timeout=2) as response:return json.load(response)

def stop(child,url,token):
    try:request(url+'/desktop/shutdown',token,b'{}')
    except Exception:pass
    try:child.wait(timeout=6)
    except subprocess.TimeoutExpired:pass
    if child.poll() is None:
        subprocess.run(['taskkill','/PID',str(child.pid),'/T','/F'],capture_output=True,creationflags=subprocess.CREATE_NO_WINDOW)
    try:child.wait(timeout=5)
    except subprocess.TimeoutExpired:child.kill()

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--data-dir',type=Path,default=Path(os.environ.get('LOCALAPPDATA',Path.home()))/'PuJian')
    parser.add_argument('--serve',type=int)
    parser.add_argument('--smoke-test',action='store_true')
    parser.add_argument('--window-test',action='store_true')
    args=parser.parse_args();args.data_dir=args.data_dir.resolve();configure(args.data_dir)
    if args.serve:
        serve(args.serve,os.environ['PUJIAN_SESSION']);return
    from ctypes import wintypes
    ctypes.windll.kernel32.CreateMutexW.restype=wintypes.HANDLE
    ctypes.windll.kernel32.CloseHandle.argtypes=[wintypes.HANDLE]
    mutex=ctypes.windll.kernel32.CreateMutexW(None,False,'Local\\PuJianDesktop')
    if not mutex:raise ctypes.WinError()
    if ctypes.windll.kernel32.GetLastError()==183:
        ctypes.windll.kernel32.CloseHandle(mutex)
        if args.smoke_test or args.window_test:raise RuntimeError('谱间已在运行')
        ctypes.windll.user32.MessageBoxW(0,'谱间已在运行，请切换到已打开的窗口。','谱间',0);return
    token=secrets.token_urlsafe(32)
    with socket.socket() as sock:
        sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    url=f'http://127.0.0.1:{port}'
    command=[sys.executable]+([] if FROZEN else [str(Path(__file__).resolve())])+['--serve',str(port),'--data-dir',str(args.data_dir.resolve())]
    env={**os.environ,'PUJIAN_SESSION':token,'PYTHONIOENCODING':'utf-8'}
    with (args.data_dir/'backend.log').open('a',encoding='utf-8') as logfile:
        child=subprocess.Popen(command,env=env,stdout=logfile,stderr=logfile,creationflags=subprocess.CREATE_NO_WINDOW)
        try:
            deadline=time.monotonic()+60
            last_error=None
            while True:
                if child.poll() is not None:raise RuntimeError('后台启动失败，请查看 backend.log。')
                try:
                    if request(url+'/api/health',token).get('status')=='ok':break
                except Exception as exc:
                    if str(exc)!=last_error:logging.warning('Health check: %s: %s',type(exc).__name__,exc);last_error=str(exc)
                if time.monotonic()>deadline:raise RuntimeError('后台启动超时，请查看 backend.log。')
                time.sleep(.2)
            if args.smoke_test:
                from smoke import check
                check(url,token,args.data_dir)
            else:
                import webview
                webview.settings['ALLOW_DOWNLOADS']=True
                window=webview.create_window('谱间 v0.3.0 · 桌面版',url+'/?desktop_session='+token,width=1280,height=900,min_size=(960,640))
                if args.window_test:
                    def verify_window():
                        try:
                            for _ in range(60):
                                if window.evaluate_js("Boolean(document.querySelector('.studio'))"):
                                    (args.data_dir/'window-result.json').write_text(json.dumps({'window_loaded':True,'engine':'WebView2'}),encoding='utf-8')
                                    return
                                time.sleep(.5)
                            logging.error('Window did not render the studio')
                        except Exception:logging.exception('Window self-test failed')
                        finally:window.destroy()
                    window.events.loaded += lambda: threading.Thread(target=verify_window,daemon=True).start()
                webview.start(gui='edgechromium',private_mode=False,storage_path=str(args.data_dir/'webview'))
                if args.window_test and not (args.data_dir/'window-result.json').exists():raise RuntimeError('窗口加载测试未通过')
        finally:
            stop(child,url,token)
            ctypes.windll.kernel32.CloseHandle(mutex)
            if args.smoke_test:
                with socket.socket() as probe:
                    probe.settimeout(1)
                    if probe.connect_ex(('127.0.0.1',port))==0:raise RuntimeError('后台未退出')

if __name__=='__main__':
    try:main()
    except Exception as exc:
        logging.exception('Desktop error')
        if '--smoke-test' in sys.argv or '--serve' in sys.argv or '--window-test' in sys.argv:sys.exit(1)
        ctypes.windll.user32.MessageBoxW(0,str(exc)+'\n请查看用户数据目录中的 desktop.log / backend.log。','谱间启动失败',0x10)
