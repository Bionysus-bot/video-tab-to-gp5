"""Build clean source/web ZIPs without local media, dependencies or Git history."""

import argparse
import fnmatch
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[1]
ROOT_FILES = (
    '.gitignore', '.gitattributes', 'README.md', 'LICENSE', 'NOTICE', 'CHANGELOG.md',
    'LICENSES/UPSTREAM-MIT.txt', 'docs/COPYRIGHT.md',
    'start.ps1', 'stop.ps1', 'start.sh', 'stop.sh', 'backend/requirements.txt',
    'frontend/package.json', 'frontend/package-lock.json', 'frontend/index.html',
    'frontend/tsconfig.json', 'frontend/vite.config.ts',
)
TREES = (
    ('backend/app', '*.py'), ('backend/tests', 'test_*.py'),
    ('frontend/src', '*'), ('docs', '*.md'), ('scripts', '*.py'),
    ('.github/workflows', '*.yml'), ('LICENSES', '*.txt'),
)


def source_files():
    paths = {ROOT / name for name in ROOT_FILES}
    paths.add(ROOT / 'backend/tests/__init__.py')
    for folder, pattern in TREES:
        for path in (ROOT / folder).rglob('*'):
            relative = path.relative_to(ROOT)
            if (path.is_file() and fnmatch.fnmatch(path.name, pattern)
                    and not any(part in {'__pycache__', 'fixtures', 'node_modules', '.venv'}
                                for part in relative.parts)
                    and not path.name.endswith('_private.py')
                    and not path.is_symlink()):
                paths.add(path)
    missing = [str(path.relative_to(ROOT)) for path in paths if not path.is_file()]
    if missing:
        raise SystemExit('Missing source files: ' + ', '.join(missing))
    return paths


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--include-web', action='store_true',
                        help='Include frontend/dist built with npm run build.')
    args = parser.parse_args()
    paths = source_files()
    if args.include_web:
        directory = ROOT / 'frontend/dist'
        if not (directory / 'index.html').is_file():
            raise SystemExit('Build the frontend first: cd frontend && npm ci && npm run build')
        paths.update(path for path in directory.rglob('*')
                     if path.is_file() and not path.is_symlink())
    destination = ROOT / '.release'
    destination.mkdir(exist_ok=True)
    output = destination / ('video-tab-to-gp5-web.zip' if args.include_web
                            else 'video-tab-to-gp5-source.zip')
    with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in sorted(paths):
            archive.write(path, 'video-tab-to-gp5/' + path.relative_to(ROOT).as_posix())
    print(f'{output.name}: {len(paths)} files, {output.stat().st_size:,} bytes')


if __name__ == '__main__':
    main()
