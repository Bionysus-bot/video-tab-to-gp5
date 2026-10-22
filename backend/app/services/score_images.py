"""Extract staff rows without turning repeated musical phrases into duplicates."""
from pathlib import Path
from contextlib import closing

import cv2
import numpy as np
import pypdfium2 as pdfium

from app.services.image_io import imread, imwrite


def staff_groups(image: np.ndarray) -> list[list[int]]:
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    # Yellow playhead should not be mistaken for notation or a barline.
    binary = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                   cv2.THRESH_BINARY_INV, 51, 3)
    horizontal = cv2.morphologyEx(binary, cv2.MORPH_OPEN,
                                  np.ones((1, max(30, image.shape[1] // 34)), np.uint8))
    ys = np.flatnonzero((horizontal > 0).sum(axis=1) > image.shape[1] * 0.20)
    peaks = []
    for y in ys:
        if not peaks or y - peaks[-1][-1] > 3:
            peaks.append([int(y)])
        else:
            peaks[-1].append(int(y))
    lines = [int(np.mean(p)) for p in peaks]
    groups = []
    index = 0
    while index < len(lines):
        found = False
        for count in (6, 5, 4):
            candidate = lines[index:index + count]
            if len(candidate) != count:
                continue
            gaps = np.diff(candidate)
            if 5 <= np.median(gaps) <= 90 and np.max(abs(gaps - np.median(gaps))) <= max(3, np.median(gaps) * .18):
                groups.append(candidate)
                index += count
                found = True
                break
        if not found:
            index += 1
    return groups


def bar_positions(image: np.ndarray, lines: list[int]) -> list[int]:
    gray = cv2.cvtColor(image[lines[0]:lines[-1] + 1], cv2.COLOR_BGR2GRAY)
    binary = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                   cv2.THRESH_BINARY_INV, 51, 3)
    binary = cv2.dilate(binary, np.ones((1, 3), np.uint8))
    vertical = cv2.morphologyEx(binary, cv2.MORPH_OPEN,
                                np.ones((max(5, int(gray.shape[0] * .65)), 1), np.uint8))
    xs = np.flatnonzero((vertical > 0).sum(axis=0) > gray.shape[0] * .6)
    peaks = []
    for x in xs:
        if not peaks or x - peaks[-1] > 5:
            peaks.append(int(x))
    return peaks


def prepare_images(inputs: list[Path], output: Path) -> dict:
    output.mkdir(parents=True, exist_ok=True)
    rows = []
    rejected = []
    previous = None
    def process(image, source):
        nonlocal previous
        if image is None:
            rejected.append(dict(source=source, reason="图片读取失败"))
            return
        groups = staff_groups(image)
        if not groups:
            rejected.append(dict(source=source, reason="未检测到四至六根等距弦线，可能是黑屏、片尾或模糊帧，请复查"))
            return
        for index, group in enumerate(groups):
            spacing = int(np.median(np.diff(group)))
            y0 = max(0, group[0] - spacing * 4)
            y1 = min(image.shape[0], group[-1] + spacing * 5)
            if index:
                y0 = max(y0, (groups[index - 1][-1] + group[0]) // 2)
            if index + 1 < len(groups):
                y1 = min(y1, (group[-1] + groups[index + 1][0]) // 2)
            crop = image[y0:y1].copy()
            # Only byte-identical adjacent rows are skipped. Musical similarity is
            # not enough evidence: repeated phrases may be distinct measures.
            if previous is not None and np.array_equal(previous, crop):
                continue
            previous = crop
            name = f"row_{len(rows) + 1:04d}.png"
            imwrite(str(output / name), crop)
            rows.append(dict(id=name, source=source, strings=len(group),
                             lines=[y - y0 for y in group],
                             bars=bar_positions(crop, [y - y0 for y in group]),
                             width=crop.shape[1], height=crop.shape[0]))

    for path in inputs:
        if path.suffix.lower() == ".pdf":
            with closing(pdfium.PdfDocument(str(path))) as document:
                if len(document) > 100:
                    raise ValueError("第一版最多处理 100 页 PDF")
                for page_number in range(len(document)):
                    page = document[page_number]
                    scale = min(8, 2200 / max(page.get_size()))
                    bitmap = page.render(scale=scale)
                    image = cv2.cvtColor(np.asarray(bitmap.to_pil().convert("RGB")), cv2.COLOR_RGB2BGR)
                    process(image, f"PDF 第 {page_number + 1} 页")
                    bitmap.close()
                    page.close()
        else:
            process(imread(str(path)), path.name)
    return dict(rows=rows, rejected=rejected)
