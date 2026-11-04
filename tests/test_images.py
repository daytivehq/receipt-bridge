import io

import numpy as np
import pytest
from PIL import Image, ImageDraw

from receipt_bridge.images import atomic_write, load_image, perspective, process_image


def test_original_preserved_output_limits_metadata_and_rotation(tmp_path):
    image = Image.new("RGB", (4500, 3500), "white")
    exif = Image.Exif()
    exif[274] = 6  # EXIF rotate 90 degrees.
    exif[315] = "PRIVATE_METADATA"
    out = io.BytesIO()
    image.save(out, "JPEG", exif=exif)
    original, corrected = tmp_path / "original.bin", tmp_path / "out.jpg"
    atomic_write(original, out.getvalue())
    assert load_image(out.getvalue()).size == (3500, 4500)
    process_image(original, corrected, rotation=90, use_original=True)
    assert original.read_bytes() == out.getvalue()
    assert len(corrected.read_bytes()) <= 5 * 1024 * 1024
    with Image.open(corrected) as result:
        assert result.width * result.height <= 16_000_000
        assert result.width > result.height
        assert not result.getexif()
    assert b"PRIVATE_METADATA" not in corrected.read_bytes()


def test_perspective_detects_receipt_without_new_drawing():
    image = Image.new("RGB", (800, 1000), "#303030")
    draw = ImageDraw.Draw(image)
    draw.polygon([(180, 80), (650, 140), (700, 910), (100, 850)], fill="white")
    for y in range(250, 750, 50):
        draw.line([(250, y), (550, y)], fill="black", width=5)
    corrected, cropped = perspective(image)
    assert cropped and min(corrected.size) > 150
    assert np.asarray(corrected).mean() > np.asarray(image).mean()


def test_reject_non_image_and_multi_frame(tmp_path):
    with pytest.raises(Exception):
        load_image(b"<html>not an image</html>")
    out = io.BytesIO()
    Image.new("RGB", (30, 30)).save(out, "GIF")
    with pytest.raises(ValueError):
        load_image(out.getvalue())


def test_real_local_ocr_when_installed(tmp_path):
    import shutil

    from receipt_bridge.images import local_ocr
    from tests.fakes import sample_image

    if not shutil.which("tesseract"):
        pytest.skip("Tesseract is exercised in the Docker test image")
    image = tmp_path / "test.png"
    image.write_bytes(sample_image())
    text = local_ocr(image, "eng")
    assert "12000" in text and "total" in text.casefold()
