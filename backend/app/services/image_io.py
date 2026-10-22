"""OpenCV image I/O that supports Unicode paths on Windows."""
from pathlib import Path

import cv2
import numpy as np


def imread(path: str | Path, flags: int = cv2.IMREAD_COLOR):
    try:
        data = np.fromfile(str(path), dtype=np.uint8)
    except OSError:
        return None
    if not data.size:
        return None
    return cv2.imdecode(data, flags)


def imwrite(path: str | Path, image: np.ndarray) -> bool:
    success, encoded = cv2.imencode(Path(path).suffix, image)
    if success:
        encoded.tofile(str(path))
    return success
