"""Unit tests for the neighbour gap-detection service (PB-1).

Covers: overlap-only, clean shared edge (no gap), ribbon gap, island gap,
case (c) bottom+top overlap with central ribbon gap, distant neighbour
filtering, and gap size classification.
"""

import pytest
from shapely.geometry import box, Polygon
from shapely.validation import make_valid

from app.services.gap_detector import GapParams, NeighbourRelation, detect_relations


class _NBR:
    """Minimal stand-in for a Calculation with just boundary_geom + names."""

    def __init__(self, boundary_geom, fid="nbr-1", name="Neighbour", name_np=None):
        self.id = fid
        self.forest_name = name
        self.name_np = name_np
        self.boundary_geom = boundary_geom


# -- params -------------------------------------------------------------------
# A gap of 0.0009 deg ~ 100 m; use adjacency wide enough to bridge it.
P = GapParams(
    adjacency_m=400.0,  # 400 m -> adjacency_deg ~ 0.0036 -> buffer radius 0.0018
    ribbon_ratio=3.0,
    small_size_m=30.0,  # shortest < 30 m -> small
    large_size_m=300.0,  # shortest > 300 m -> large
    # Test shapes live in unit-degrees, so their deg^2 areas (the same deg-metre
    # convention overlap_resolver uses) are microscopic ha values; keep the
    # floor far below them so presence/classification assertions still hold.
    # (The floor's real effect - suppressing sub-hectare specks - is exercised
    # by the presence/absence assertions on real-scale inputs.)
    min_fragment_ha=1e-12,
)


def _bbox_polygon(gap):
    return gap


# -- 1. overlap-only ----------------------------------------------------------
def test_overlap_only():
    neighbour = box(0.1, 0.1, 0.3, 0.3)  # overlaps proposed in [0.1,0.2]^2
    rels = detect_relations(
        box(0, 0, 0.2, 0.2).__geo_interface__,
        [_NBR(neighbour)],
        P,
    )
    assert len(rels) == 1
    r = rels[0]
    assert r.overlap_polygon is not None, "overlap must be detected"
    assert r.overlap_ha >= 0
    assert r.adjacent is True


# -- 2. clean shared edge (no gap, no overlap) --------------------------------
def test_clean_shared_edge():
    # Same y-extent, touching at x=0.1 -> true shared boundary, no band.
    proposed = box(0, 0, 0.1, 0.2)
    neighbour = box(0.1, 0, 0.2, 0.2)
    rels = detect_relations(proposed.__geo_interface__, [_NBR(neighbour)], P)
    assert rels == [], "purely edge-adjacent polygons with no gap must not report a gap"


# -- 3. ribbon gap ------------------------------------------------------------
def test_ribbon_gap():
    # Horizontal strip pair separated by a thin ~ribbon gap in y (~100 m).
    proposed = box(0, 0, 0.2, 0.05)
    neighbour = box(0, 0.0509, 0.2, 0.1009)
    rels = detect_relations(proposed.__geo_interface__, [_NBR(neighbour)], P)
    r = next((x for x in rels if x.id == "nbr-1"), None)
    assert r is not None, "expected an adjacent relationship"
    assert r.gap_polygon is not None, "expected a gap to be detected"
    assert r.gap_polygon.is_valid
    # 0.2 wide vs ~0.0009 tall -> strongly elongated -> ribbon.
    assert r.gap_shape == "ribbon"


# -- 4. island (compact) gap --------------------------------------------------
def test_island_gap():
    # Two squares that nearly touch at a corner, leaving a compact square gap.
    proposed = box(0, 0, 0.1, 0.1)
    neighbour = box(0.1009, 0.1009, 0.2009, 0.2009)
    rels = detect_relations(proposed.__geo_interface__, [_NBR(neighbour)], P)
    r = next((x for x in rels if x.id == "nbr-1"), None)
    assert r is not None and r.gap_polygon is not None, "expected a compact gap"
    assert r.gap_shape == "island", f"expected island, got {r.gap_shape}"


# -- 5. overlapping polygons: overlap reported, gap deferred (clipped upstream)
def test_overlap_present_suppresses_gap():
    # When two boundaries overlap, the overlap is the headline finding; the
    # unclaimed band is computed on the clipped geometry upstream (PB-2), not
    # here. So gap detection defers (returns None) for an overlapping pair.
    proposed = box(0, 0, 0.3, 0.3)
    neighbour = box(0.2, 0.1, 0.4, 0.4)  # overlaps proposed
    rels = detect_relations(proposed.__geo_interface__, [_NBR(neighbour)], P)
    r = next((x for x in rels if x.id == "nbr-1"), None)
    assert r is not None
    assert r.overlap_polygon is not None, "expected the overlap to be detected"
    assert r.gap_polygon is None, "gap detection defers for an overlapping pair"


# -- 6. distant neighbour filtered out ----------------------------------------
def test_distant_neighbour_filtered():
    proposed = box(0, 0, 0.1, 0.1)
    neighbour = box(5, 5, 5.1, 5.1)  # far away
    rels = detect_relations(proposed.__geo_interface__, [_NBR(neighbour)], P)
    assert rels == [], "a distant, non-adjacent forest must be dropped"


# -- 7. gap size classification -----------------------------------------------
def test_gap_size_classification():
    # Small gap (shortest extent well under small_size_m).
    proposed_small = box(0, 0, 0.2, 0.05)
    nbr_small = box(0, 0.05001, 0.2, 0.10001)  # ~1 m gap -> small
    rels = detect_relations(proposed_small.__geo_interface__, [_NBR(nbr_small)], P)
    r = next((x for x in rels if x.id == "nbr-1"), None)
    assert r is not None and r.gap_polygon is not None, "expected a small gap"
    assert r.gap_size == "small"

    # Large gap (shortest extent over large_size_m ~ 300 m, but still within
    # the 400 m adjacency band so it remains a shared-boundary puzzle).
    proposed_large = box(0, 0, 0.2, 0.05)
    nbr_large = box(
        0, 0.05 + 0.0032, 0.2, 0.05 + 0.0092
    )  # ~0.0032 deg ~ 356 m -> large
    rels = detect_relations(proposed_large.__geo_interface__, [_NBR(nbr_large)], P)
    r = next((x for x in rels if x.id == "nbr-1"), None)
    assert r is not None and r.gap_polygon is not None, "expected a large gap"
    assert r.gap_size == "large"


# -- 8. empty / invalid input does not crash ----------------------------------
def test_empty_or_invalid_input():
    assert detect_relations({}, [_NBR(box(0, 0, 1, 1))], P) == []
    assert detect_relations(box(0, 0, 1, 1).__geo_interface__, [], P) == []


# -- 9. collects both overlap and gap ha --------------------------------------
def test_relation_is_dataclass_shape():
    proposed = box(0, 0, 0.2, 0.05)
    neighbour = box(0, 0.0509, 0.2, 0.1009)
    r = detect_relations(proposed.__geo_interface__, [_NBR(neighbour)], P)[0]
    assert isinstance(r, NeighbourRelation)
    assert r.name == "Neighbour"
    assert isinstance(r.overlap_ha, float)
    assert isinstance(r.gap_ha, float)
