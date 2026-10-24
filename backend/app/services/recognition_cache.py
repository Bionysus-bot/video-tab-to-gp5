"""Project-local cache of machine recognition, never of human review state."""

from functools import lru_cache
import hashlib
from importlib import metadata
import json
from pathlib import Path
import uuid

from app.models.score import RecognitionResult
from app.services.local_tab_reader import OCR_THREADS


def file_hash(path: Path) -> str:
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


@lru_cache(maxsize=1)
def reader_signature() -> str:
    services = Path(__file__).resolve().parent
    files = [services / name for name in (
        'local_tab_reader.py', 'image_io.py', 'tab_recognizer.py', 'recognition_cache.py',
        'combined_tab.py', 'combined_local.py', 'model_repair.py', 'score_continuity.py','notation_graph.py',
        'conversion_workers.py','score_images.py','local_review.py')]
    files.append(services.parent / 'models/score.py')
    versions = {}
    for name in ('rapidocr-onnxruntime', 'onnxruntime', 'numpy', 'opencv-python'):
        versions[name] = metadata.version(name)
    distribution = metadata.distribution('rapidocr-onnxruntime')
    # Include the actual recognizer weights without loading an inference session.
    files.extend(Path(distribution.locate_file(name)) for name in (
        'rapidocr_onnxruntime/config.yaml',
        'rapidocr_onnxruntime/models/ch_PP-OCRv4_rec_infer.onnx'))
    payload = {'schema': 1, 'threads': OCR_THREADS, 'versions': versions,
               'files': [(path.name, file_hash(path)) for path in files]}
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def cache_key(image: Path, row: dict, tuning: list[int]) -> str | None:
    try:
        payload = {'reader': reader_signature(), 'image': file_hash(image),
                   'row': row, 'tuning': tuning}
        content = json.dumps(payload, sort_keys=True, separators=(',', ':'), allow_nan=False)
        return hashlib.sha256(content.encode('utf-8')).hexdigest()
    except (OSError, ValueError, TypeError, metadata.PackageNotFoundError):
        # Caching is optional: unreadable inputs still use the usual error path.
        return None


def load_result(directory: Path, key: str) -> RecognitionResult | None:
    try:
        entry = json.loads((directory / f'{key}.json').read_text(encoding='utf-8'))
        if not isinstance(entry, dict) or entry.get('key') != key:
            return None
        encoded = json.dumps(entry['result'], sort_keys=True, separators=(',', ':'), allow_nan=False)
        if entry.get('result_sha256') != hashlib.sha256(encoded.encode('utf-8')).hexdigest():
            return None
        result = RecognitionResult.model_validate(entry['result'])
        for measure in result.measures:
            measure.reviewed = False
        return result
    except (OSError, ValueError, TypeError, KeyError):
        return None


def store_result(directory: Path, key: str, result: RecognitionResult) -> None:
    temporary = directory / f'.{key}.{uuid.uuid4().hex}.tmp'
    try:
        directory.mkdir(parents=True, exist_ok=True)
        cached = result.model_copy(deep=True)
        for measure in cached.measures:
            measure.reviewed = False
        entry = {'key': key, 'result': cached.model_dump()}
        encoded = json.dumps(entry['result'], sort_keys=True, separators=(',', ':'), allow_nan=False)
        entry['result_sha256'] = hashlib.sha256(encoded.encode('utf-8')).hexdigest()
        temporary.write_text(json.dumps(entry, ensure_ascii=False), encoding='utf-8')
        temporary.replace(directory / f'{key}.json')
    except OSError:
        pass  # A full disk or read-only cache must not prevent recognition.
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
