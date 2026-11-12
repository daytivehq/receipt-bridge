from __future__ import annotations

import hashlib
import io
import os
import re
import subprocess
import tempfile
import warnings
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageEnhance, ImageOps

Image.MAX_IMAGE_PIXELS = 40_000_000


def atomic_write(path: Path, data: bytes):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, tmp = tempfile.mkstemp(dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
        directory = os.open(path.parent, os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def load_image(data: bytes) -> Image.Image:
    with warnings.catch_warnings():
        warnings.simplefilter("error", Image.DecompressionBombWarning)
        with Image.open(io.BytesIO(data)) as source:
            if source.format not in {"JPEG", "PNG", "WEBP"}:
                raise ValueError("JPG·PNG·WebP 이미지만 받을 수 있습니다")
            if source.width * source.height > 40_000_000 or getattr(source, "n_frames", 1) != 1:
                raise ValueError("4천만 화소 이하의 단일 이미지만 받을 수 있습니다")
            source.load()
            image = ImageOps.exif_transpose(source).convert("RGBA")
            white = Image.new("RGBA", image.size, "white")
            white.alpha_composite(image)
            return white.convert("RGB")


def jpeg_bytes(image: Image.Image) -> bytes:
    # Meet Ledger's pixel, side length and byte limits before either preview or upload.
    image = image.copy()
    image.thumbnail((4000, 4000))
    for quality in (92, 85, 75, 65):
        out = io.BytesIO()
        image.save(out, format="JPEG", quality=quality, exif=b"")
        if out.tell() <= 5 * 1024 * 1024:
            return out.getvalue()
    image.thumbnail((2400, 2400))
    out = io.BytesIO()
    image.save(out, format="JPEG", quality=80, exif=b"")
    if out.tell() > 5 * 1024 * 1024:
        raise ValueError("보정 사진을 5MB 이하로 줄이지 못했습니다")
    return out.getvalue()


def perspective(image: Image.Image):
    rgb = np.asarray(image)
    ratio = min(1.0, 1200 / max(image.size))
    small = cv2.resize(rgb, None, fx=ratio, fy=ratio)
    gray = cv2.cvtColor(small, cv2.COLOR_RGB2GRAY)
    edges = cv2.Canny(cv2.GaussianBlur(gray, (5, 5), 0), 40, 120)
    contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    area = small.shape[0] * small.shape[1]
    for contour in sorted(contours, key=cv2.contourArea, reverse=True)[:10]:
        polygon = cv2.approxPolyDP(contour, 0.02 * cv2.arcLength(contour, True), True)
        if len(polygon) != 4 or not cv2.isContourConvex(polygon):
            continue
        fraction = cv2.contourArea(polygon) / area
        if not 0.30 <= fraction <= 0.97:
            continue
        pts = polygon.reshape(4, 2).astype(np.float32) / ratio
        ordered = np.array(
            [
                pts[np.argmin(pts.sum(1))],
                pts[np.argmin(np.diff(pts, axis=1))],
                pts[np.argmax(pts.sum(1))],
                pts[np.argmax(np.diff(pts, axis=1))],
            ],
            np.float32,
        )
        if len(np.unique(ordered, axis=0)) != 4:
            continue
        tl, tr, br, bl = ordered
        width = int(max(np.linalg.norm(tr - tl), np.linalg.norm(br - bl)))
        height = int(max(np.linalg.norm(bl - tl), np.linalg.norm(br - tr)))
        if min(width, height) < 150 or max(width, height) > 12000:
            continue
        dest = np.array([[0, 0], [width - 1, 0], [width - 1, height - 1], [0, height - 1]], np.float32)
        warped = cv2.warpPerspective(
            rgb, cv2.getPerspectiveTransform(ordered, dest), (width, height), borderMode=cv2.BORDER_REPLICATE
        )
        return Image.fromarray(warped), True
    return image, False


def auto_orient(image: Image.Image):
    """Estimate text direction locally; a manual rotation always takes precedence."""
    preview = image.copy()
    preview.thumbnail((2000, 2000))
    data = io.BytesIO()
    preview.save(data, "PNG")
    try:
        result = subprocess.run(
            ["tesseract", "stdin", "stdout", "--psm", "0"],
            input=data.getvalue(),
            capture_output=True,
            timeout=15,
            check=True,
        )
        text = result.stdout[:16000].decode("utf-8", errors="replace")
        angle = re.search(r"^Rotate: (0|90|180|270)$", text, re.M)
        confidence = re.search(r"^Orientation confidence: ([0-9.]+)$", text, re.M)
        if angle and confidence and float(confidence[1]) >= 2:
            degrees = int(angle[1])
            if degrees:
                return image.rotate(
                    -degrees, expand=True
                ), f"글자 방향을 추정해 {degrees}° 회전했습니다. 방향을 확인하세요"
            return image, None
    except (OSError, ValueError, subprocess.SubprocessError):
        pass
    return image, "글자 방향을 확정하지 못했습니다. 사진이 누워 있으면 회전 후 재분석하세요"


def process_image(original: Path, output: Path, rotation=0, use_original=False):
    image = load_image(original.read_bytes())
    notes = []
    if rotation:
        image = image.rotate(-rotation, expand=True)
    else:
        image, note = auto_orient(image)
        if note:
            notes.append(note)
    oriented = image
    if not use_original:
        try:
            image, cropped = perspective(image)
            if cropped:
                # A geometric heuristic cannot prove the crop preserved every digit.
                notes.append("영수증 영역을 추정해 잘랐습니다. 가장자리 숫자를 확인하세요")

            # Global tone changes only; no inpainting, generation, erasing or local redraw.
            image = ImageEnhance.Brightness(image).enhance(1.08)
            image = ImageEnhance.Contrast(image).enhance(1.06)
        except (cv2.error, ValueError):
            image = oriented
            notes.append("보정 실패로 전체 원본을 사용했습니다")
    else:
        notes.append("원본 구도를 사용했습니다")
    data = jpeg_bytes(image)
    atomic_write(output, data)
    return notes, hashlib.sha256(data).hexdigest()


def local_ocr(image: Path, languages: str) -> str:
    try:
        result = subprocess.run(
            ["tesseract", str(image), "stdout", "-l", languages, "--psm", "3"],
            capture_output=True,
            timeout=45,
            check=True,
        )
        return result.stdout[:100_000].decode("utf-8", errors="replace")
    except (OSError, subprocess.SubprocessError):
        return ""
