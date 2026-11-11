"""Regression: the 3-phase overlap resolver must report REAL hectares.

Historic defect: ``resolve_overlap`` ran on raw EPSG:4326 lon/lat geometry and
divided the resulting *square-degree* ``.area`` by 10 000 as if it were m².
At Nepal's latitude one square degree is ~1.2e10 m², so every ``resolved_area_ha``
came out ~1e-8 — always below ``min_forest_ha`` (0.5) — and every submission
with any overlap was rejected as ``remaining_too_small``.

The engine now projects to the local UTM zone before any area or tolerance
maths, so areas are true hectares and the resolved geometry is returned in
4326 for the map / confirm step.
"""

from shapely.geometry import box, mapping

from app.services.overlap_resolver import resolve_overlap, ResolutionParams


class _NBR:
    def __init__(self, boundary_geom, fid="nbr-1"):
        self.id = fid
        self.forest_name = "Neighbour"
        self.name_np = ""
        self.boundary_geom = boundary_geom


# A ~2.0 km x ~1.7 km box near Kathmandu (84.0E, 28.0N) ≈ 327 ha.
_PROPOSED = box(84.00, 28.00, 84.02, 28.015)


def test_no_overlap_reports_real_hectares():
    res = resolve_overlap(mapping(_PROPOSED), [])
    assert res.status == "no_overlap"
    # ~327 ha, definitely not ~3e-6 ha.
    assert 300 < res.orig_area_ha < 360
    assert res.resolved_area_ha == res.orig_area_ha


def test_partial_overlap_is_acceptable_not_rejected():
    # Neighbour covers the eastern ~40 % of the proposed box.
    nbr = _NBR(box(84.012, 27.995, 84.025, 28.02))
    res = resolve_overlap(mapping(_PROPOSED), [nbr], ResolutionParams())

    assert res.status == "acceptable", (res.status, res.reason)
    assert res.reason is None
    # ~196 ha remains — comfortably above the 0.5 ha floor that the bug tripped.
    assert res.resolved_area_ha > 150
    assert 35 < res.removed_pct < 45
    assert res.overlapping_forests[0]["overlap_ha"] > 100

    # Resolved geometry must come back in lon/lat (4326), not UTM metres.
    minx, miny, maxx, maxy = res.resolved.bounds
    assert 83 < minx < 85 and 27 < miny < 29


def test_true_remaining_too_small_still_rejects():
    # Neighbour swallows all but a ~15 m strip of the proposed box.
    nbr = _NBR(box(84.0002, 27.99, 84.03, 28.03))
    res = resolve_overlap(mapping(_PROPOSED), [nbr], ResolutionParams())
    assert res.status == "reject"
    assert res.reason in ("remaining_too_small", "overlap_too_large", "all_fragments_too_small")
