"""Charts go into the document as PNG pictures. A bare SVG as the picture itself shows clipped, with its legend labels missing, in
Word and as a black or empty box elsewhere (found on a real export, 2026-10-18)."""
import base64
import re
import zipfile
from io import BytesIO

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from docx import Document

from app.utils.svg_to_png import add_svg_picture, image_mime, is_raster


def _png_data_uri():
    from app.services.report.chart_generator import _save_or_base64

    fig, ax = plt.subplots(figsize=(3, 2))
    ax.pie([3, 1], labels=["a", "b"])
    return _save_or_base64(fig)


def test_the_chart_maker_returns_a_png_not_an_svg():
    uri = _png_data_uri()
    assert uri.startswith("data:image/png;base64,")
    assert is_raster(base64.b64decode(uri.split(",", 1)[1]))


def test_a_raster_is_added_as_an_ordinary_picture_and_the_package_has_no_svg():
    doc = Document()
    add_svg_picture(doc, _png_data_uri(), width_inches=4)
    buf = BytesIO()
    doc.save(buf)
    names = zipfile.ZipFile(buf).namelist()
    assert any(n.startswith("word/media/") and n.endswith(".png") for n in names)
    assert not any(n.endswith(".svg") for n in names)


def test_image_mime_follows_the_bytes():
    assert image_mime(bytes([0x89]) + b"PNG\r\n") == "image/png"
    assert image_mime(bytes([0xFF, 0xD8, 0xFF]) + b"x") == "image/jpeg"
    assert image_mime(b"<svg xmlns='http://www.w3.org/2000/svg'/>") == "image/svg+xml"


def test_an_old_cached_svg_is_never_read_back_into_a_document(tmp_path, monkeypatch):
    from uuid import uuid4

    from app.services.operational_plan import op_docx_builder as b

    monkeypatch.setattr(b, "_CHART_CACHE_DIR", str(tmp_path))
    cid = uuid4()
    sub = tmp_path / str(cid)
    sub.mkdir()
    (sub / "landcover_pie.svg").write_bytes(b"<svg/>")
    assert b._chart_cache_get(cid, "landcover_pie") is None
    b._chart_cache_set(cid, "landcover_pie", BytesIO(bytes([0x89]) + b"PNG\r\n"))
    assert b._chart_cache_get(cid, "landcover_pie") is not None
