"""Branch coverage for file_processor geometry-guard fallbacks (H4.2).

Two defensive paths never ran: when a footprint cannot be reprojected to
EPSG:4326 (the Nepal bounds check is skipped, not fatal) and when a geometry
cannot have its coordinate magnitudes normalised (it passes through unchanged).
"""
from __future__ import annotations

from shapely.geometry import Polygon

from app.services import file_processor as fp


def test_an_untransformable_footprint_skips_the_nepal_check(monkeypatch):
    """A file whose footprint cannot be reprojected is not refused -- the
    bounds check is skipped, but the import is not silently dropped."""

    def _boom(*a, **k):
        raise RuntimeError("no CRS mapping")

    monkeypatch.setattr(fp, "transform_to_4326", _boom)
    # Must not raise, and must return without judging the box.
    fp.validate_geometry_within_nepal(
        [Polygon([(80, 26), (88, 26), (88, 30), (80, 30)])],
        source_crs="EPSG:32645",
    )


def test_an_unrewriteable_geometry_passes_through_unchanged(monkeypatch):
    """A geometry the magnitude normaliser cannot touch is kept as-is rather
    than dropped or raising."""

    def _boom(*a, **k):
        raise ValueError("cannot transform this geometry")

    monkeypatch.setattr(fp, "transform", _boom)

    keep = Polygon([(0, 0), (10, 0), (10, 10)])
    out, changed = fp._sanitize_coordinate_magnitudes([keep])
    assert out == [keep]
    assert changed == 0
