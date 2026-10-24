"""Build a Windows local-test desktop bundle, notices, ZIP and optional installer."""
import argparse
import importlib.metadata
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / 'output' / 'desktop'


def notices():
    bundle = OUTPUT / 'PuJian'
    if not (bundle / 'PuJian.exe').is_file():
        raise SystemExit('Build PuJian.exe first')
    target = bundle / 'licenses'
    target.mkdir(exist_ok=True)
    for name in ('LICENSE', 'NOTICE', 'desktop/THIRD_PARTY.md'):
        shutil.copy2(ROOT / name, target / Path(name).name)
    shutil.copy2(ROOT / 'docs/DESKTOP.md', bundle / '使用说明.md')
    for dist in importlib.metadata.distributions():
        for item in dist.files or ():
            if item.name.lower().startswith(('license', 'copying', 'notice')):
                source = Path(dist.locate_file(item))
                if not source.is_file():
                    continue
                relative = Path(*item.parts)
                destination = target / 'python-packages' / dist.metadata['Name'] / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, destination)
    executable = shutil.which('ffmpeg')
    if not executable:
        raise SystemExit('ffmpeg is required')
    ffmpeg = Path(executable).resolve()
    distribution = ffmpeg.parent.parent
    for name in ('LICENSE', 'README.txt'):
        if (distribution / name).is_file():
            shutil.copy2(distribution / name, target / ('FFmpeg-' + name))
    version = subprocess.run([str(ffmpeg), '-version'], capture_output=True, check=True).stdout
    (target / 'FFmpeg-build.txt').write_bytes(version)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--skip-freeze', action='store_true')
    parser.add_argument('--iscc', type=Path, help='Optional Inno Setup ISCC.exe path')
    args = parser.parse_args()
    if sys.platform != 'win32':
        raise SystemExit('Build this Windows application on Windows')
    if not args.skip_freeze:
        subprocess.run([sys.executable, '-m', 'PyInstaller', '--noconfirm',
                        '--distpath', str(OUTPUT), '--workpath', str(ROOT / '.runtime/desktop-build'),
                        str(ROOT / 'desktop/pujian.spec')], cwd=ROOT, check=True)
    notices()
    archive = OUTPUT / 'PuJian-0.3.0-Windows-x64-Portable'
    shutil.make_archive(str(archive), 'zip', root_dir=OUTPUT, base_dir='PuJian')
    if args.iscc:
        subprocess.run([str(args.iscc.resolve()), str(ROOT / 'desktop/setup.iss')],
                       cwd=ROOT, check=True)
    import hashlib
    artifacts = sorted(OUTPUT.glob('PuJian-0.3.0-Windows-x64-*'))
    checksums = '\n'.join(hashlib.sha256(p.read_bytes()).hexdigest() + '  ' + p.name
                          for p in artifacts if p.is_file())
    (OUTPUT / 'SHA256SUMS.txt').write_text(checksums + '\n', encoding='utf-8')
    for artifact in artifacts:
        print(f'{artifact.name}: {artifact.stat().st_size:,} bytes')


if __name__ == '__main__':
    main()
