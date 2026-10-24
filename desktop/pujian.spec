from pathlib import Path
import shutil
import ssl
from PyInstaller.utils.hooks import collect_all, collect_submodules, copy_metadata
root=Path(SPECPATH).parent
binaries=[];datas=[(str(root/'frontend/dist'),'frontend/dist'),(str(root/'backend/app'),'app'),(str(root/'LICENSES'),'LICENSES'),(str(root/'LICENSE'),'licenses')]
# Some Python distributions require an extra CA file when creating SSL contexts.
runtime_ca=Path(ssl.__file__).with_name('codex-rejected-cas.pem')
if runtime_ca.is_file():datas.append((str(runtime_ca),'.'))
hidden=collect_submodules('app')+['uvicorn.logging','uvicorn.loops.auto','uvicorn.protocols.http.auto','uvicorn.protocols.websockets.auto','uvicorn.lifespan.on','webview.platforms.edgechromium','webview.platforms.winforms','smoke']
for package in ('rapidocr_onnxruntime','onnxruntime','webview','pythonnet','clr_loader','pypdfium2'):
    d,b,h=collect_all(package);datas+=d;binaries+=b;hidden+=h
for package in ('rapidocr-onnxruntime','onnxruntime','numpy','opencv-python'):
    datas+=copy_metadata(package)
for tool in ('ffmpeg','ffprobe'):
    binaries.append((str(Path(shutil.which(tool)).resolve()),'tools'))
a=Analysis([str(root/'desktop/launcher.py')],pathex=[str(root/'backend'),str(root/'desktop')],binaries=binaries,datas=datas,hiddenimports=hidden,excludes=['PyQt5','PyQt6','PySide2','PySide6','cefpython3','IPython','matplotlib','pandas','scipy','tkinter'],noarchive=False)
pyz=PYZ(a.pure)
exe=EXE(pyz,a.scripts,[],exclude_binaries=True,name='PuJian',debug=False,bootloader_ignore_signals=False,strip=False,upx=False,console=False)
coll=COLLECT(exe,a.binaries,a.datas,strip=False,upx=False,name='PuJian')
