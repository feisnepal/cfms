"""
SVG utilities for embedding in DOCX
Embeds SVG directly via OPC archive manipulation (bypasses Cairo dep)
"""
import io
from typing import Optional
from base64 import b64decode
from lxml import etree
import logging

logger = logging.getLogger(__name__)


def svg_to_png_bytes(svg_bytes: bytes, scale: float = 2.0) -> bytes:
    """Convert SVG bytes to PNG bytes using CairoSVG"""
    import cairosvg
    return cairosvg.svg2png(bytestring=svg_bytes, scale=scale)


def svg_to_png_stream(svg_bytes: bytes, scale: float = 2.0) -> io.BytesIO:
    """Convert SVG bytes to PNG BytesIO"""
    png_bytes = svg_to_png_bytes(svg_bytes, scale)
    return io.BytesIO(png_bytes)


def is_svg_data_uri(data_uri: str) -> bool:
    """Check if a data URI is SVG"""
    return data_uri.startswith("data:image/svg+xml")


def ensure_png_stream(data_uri: str, scale: float = 2.0) -> Optional[io.BytesIO]:
    """
    Convert a data URI (SVG or PNG) to a PNG BytesIO suitable for python-docx.
    Falls back to None if CairoSVG is unavailable — callers should handle this.
    """
    if not data_uri or not data_uri.startswith("data:"):
        return None
    encoded = data_uri.split(",", 1)[1]
    raw_bytes = b64decode(encoded)
    if data_uri.startswith("data:image/svg+xml"):
        try:
            return svg_to_png_stream(raw_bytes, scale)
        except Exception:
            logger.exception(
                "SVG could not be rasterised - the caller will fall back to a "
                "placeholder"
            )
            return None
    return io.BytesIO(raw_bytes)


def _decode_data_uri(data_uri: str) -> tuple[bytes, str]:
    """Decode a data URI into (raw_bytes, mime_type)."""
    if not data_uri or not data_uri.startswith("data:"):
        raise ValueError("Not a data URI")
    header, encoded = data_uri.split(",", 1)
    mime = header.split(";")[0].replace("data:", "")
    raw_bytes = b64decode(encoded)
    return raw_bytes, mime


def _get_svg_dimensions(svg_bytes: bytes) -> tuple[float, float]:
    """Parse SVG to get intrinsic width/height in pixels (or viewBox fallback)."""
    try:
        root = etree.fromstring(svg_bytes)
        vb = root.get("viewBox")
        if vb:
            parts = vb.strip().split()
            if len(parts) == 4:
                return float(parts[2]), float(parts[3])
        for attr in ("width", "height"):
            val = root.get(attr)
            if val:
                import re
                numeric = re.sub(r"[^\d.]", "", val)
                if numeric:
                    w = float(re.sub(r"[^\d.]", "", root.get("width", "600")))
                    h = float(re.sub(r"[^\d.]", "", root.get("height", "400")))
                    return w, h
    except Exception:
        logger.warning(
            "SVG dimensions unreadable - falling back to the default canvas "
            "size, which may crop or stretch the image", exc_info=True,
        )
    return 600.0, 400.0


_RASTER_MAGIC = (b"\x89PNG\r\n\x1a\n", b"\xff\xd8\xff", b"GIF8")


def is_raster(raw: bytes) -> bool:
    """PNG, JPEG or GIF bytes, judged by their first bytes (not by a name or a mime type that may be wrong)."""
    return bytes(raw[:8]).startswith(_RASTER_MAGIC)


def image_mime(raw: bytes) -> str:
    """The mime type of an image's bytes, for an <img src="data:..."> in the HTML preview."""
    head = bytes(raw[:8])
    if head.startswith(b"\x89PNG"):
        return "image/png"
    if head.startswith(b"\xff\xd8"):
        return "image/jpeg"
    if head.startswith(b"GIF8"):
        return "image/gif"
    return "image/svg+xml"


def add_svg_picture(doc, data_uri_or_bytes, width_inches=5.0):
    """
    Embed a chart or map picture into the DOCX.

    A PNG/JPEG goes in as an ordinary picture, which every Word, viewer and phone shows. A bare SVG (the old chart format) is
    written as the picture itself with no PNG behind it; Word draws such a picture clipped, with the legend labels missing,
    and other viewers show a black or empty box, so the chart producers now make PNG and this route is only a fallback.
    Bypasses python-docx's add_picture() for SVG, which rejects it.

    Args:
        doc: python-docx Document
        data_uri_or_bytes: "data:image/svg+xml;base64,..." string or raw SVG bytes
        width_inches: desired display width in inches (default 5.0)
    Returns:
        The added picture shape, or None if embedding fails.
    """
    if isinstance(data_uri_or_bytes, str) and data_uri_or_bytes.startswith("data:"):
        raw_bytes, _ = _decode_data_uri(data_uri_or_bytes)
    elif isinstance(data_uri_or_bytes, (bytes, bytearray)):
        raw_bytes = bytes(data_uri_or_bytes)
    else:
        return None

    if is_raster(raw_bytes):
        from docx.shared import Inches

        return doc.add_picture(io.BytesIO(raw_bytes), width=Inches(width_inches))

    svg_w, svg_h = _get_svg_dimensions(raw_bytes)
    package = doc.part.package

    from docx.parts.image import ImagePart
    from docx.opc.packuri import PackURI
    from docx.opc.constants import RELATIONSHIP_TYPE as RT
    from docx.oxml.shape import CT_Inline
    from docx.shared import Inches, Emu

    n = len(package.image_parts) + 1
    partname = PackURI(f"/word/media/image{n}.svg")
    image_part = ImagePart(partname, "image/svg+xml", raw_bytes)
    package.image_parts.append(image_part)

    rId = doc.part.relate_to(image_part, RT.IMAGE)
    shape_id = doc.part.next_id

    width_emu = Inches(width_inches).emu
    height_emu = int(width_emu * svg_h / svg_w)

    inline = CT_Inline.new_pic_inline(shape_id, rId, f"image{n}.svg", width_emu, height_emu)

    p = doc.add_paragraph()
    run = p.add_run()
    run._r.add_drawing(inline)
    return inline
