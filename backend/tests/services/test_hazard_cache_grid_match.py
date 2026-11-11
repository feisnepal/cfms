"""A cached hazard / soil-loss GeoTIFF is valid only for the grid it was computed on.

Drawing or cutting a user-group polygon changes the grid (it spans forest + user group). A stale cache of the old
shape used to raise "operands could not be broadcast together", which the OP collector swallowed, so the chapter
claimed the DEM / soil / geology data was "not available".
"""
import numpy as np
import rasterio
from affine import Affine

from app.services.operational_plan import soil_erosion as se


class _Grid:
    def __init__(self, w, h):
        self.width, self.height = w, h


def _tif(path, w, h):
    with rasterio.open(path, "w", driver="GTiff", width=w, height=h, count=1, dtype="float32",
                       transform=Affine(0.001, 0, 85.0, 0, -0.001, 27.5)) as ds:
        ds.write(np.zeros((h, w), dtype="float32"), 1)


def test_cache_matches_only_the_same_shape(tmp_path):
    p = tmp_path / "c.tif"
    _tif(p, 53, 55)
    assert se.cache_matches_grid(p, _Grid(53, 55)) is True
    assert se.cache_matches_grid(p, _Grid(75, 50)) is False  # the user group grew: recompute


def test_unreadable_cache_is_treated_as_stale(tmp_path):
    p = tmp_path / "bad.tif"
    p.write_bytes(b"not a tiff")
    assert se.cache_matches_grid(p, _Grid(10, 10)) is False
