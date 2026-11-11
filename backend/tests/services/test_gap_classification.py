"""GAP-1 — gap classification (snap / absorb / offer / report), medial width,
and the case-(c) fix (overlap + gap against the same neighbour).

Shapes are scaled to real metres near Kathmandu (84.0E, 28.0N):
1 deg lon ~ 98.2 km, 1 deg lat ~ 110.6 km.
"""

from shapely.geometry import Polygon, box

from app.services.gap_detector import (
    GapParams,
    classify_gap_action,
    detect_relations,
    _medial_width_m,
)


class _NBR:
    def __init__(self, boundary_geom, fid="nbr-1"):
        self.id = fid
        self.forest_name = "Neighbour"
        self.name_np = None
        self.boundary_geom = boundary_geom


P = GapParams(adjacency_m=400.0)  # defaults: sliver 5 m, absorb ≤50 m & ≤5 ha, large 300 m


# -- classify_gap_action (pure) --------------------------------------------------
def test_classify_pure():
    assert classify_gap_action("ribbon", 3.0, 0.1, True, P) == "snap"
    assert classify_gap_action("ribbon", 25.0, 2.0, True, P) == "absorb"
    assert classify_gap_action("ribbon", 70.0, 2.0, True, P) == "offer"   # too wide
    assert classify_gap_action("ribbon", 25.0, 9.0, True, P) == "offer"   # too large
    assert classify_gap_action("island", 25.0, 2.0, True, P) == "offer"   # blob
    assert classify_gap_action("mixed", 25.0, 2.0, True, P) == "offer"
    assert classify_gap_action("ribbon", 800.0, 2.0, True, P) == "report" # huge
    assert classify_gap_action("none", 0.0, 0.0, True, P) == "report"
    assert classify_gap_action("ribbon", 25.0, 2.0, False, P) == "report" # not adjacent


# -- medial width --------------------------------------------------------------
def test_medial_width_of_a_thin_strip():
    # ~980 m long, ~22 m tall strip near Kathmandu.
    strip = box(84.00, 28.00, 84.01, 28.0002)
    w = _medial_width_m(strip)
    assert 18 < w < 26, w


def test_medial_width_ignores_bbox_for_a_bent_strip():
    # L-shaped ~25 m-wide corridor: bbox short side would read ~600 m.
    d = 25 / 110570  # ~25 m in degrees lat
    e = 25 / 98240   # ~25 m in degrees lon
    L = Polygon([
        (84.000, 28.000), (84.000, 28.006), (84.000 + e, 28.006),
        (84.000 + e, 28.000 + d), (84.006, 28.000 + d), (84.006, 28.000),
    ])
    w = _medial_width_m(L)
    assert 20 < w < 32, w


# -- end-to-end action on realistic fixtures ----------------------------------
_PROPOSED = box(84.00, 28.00, 84.01, 28.005)  # ~980 m x ~550 m


def _rel(nbr):
    rels = detect_relations(_PROPOSED.__geo_interface__, [nbr], P)
    return next((r for r in rels if r.id == "nbr-1"), None)


def test_narrow_ribbon_is_absorbed():
    # 22 m gap to a forest just north, spanning the full width -> ribbon, ~2 ha.
    nbr = _NBR(box(84.00, 28.00520, 84.01, 28.0090))
    r = _rel(nbr)
    assert r is not None and r.gap_polygon is not None
    assert r.gap_shape == "ribbon"
    assert 0 < r.gap_width_m <= 50
    assert r.gap_action == "absorb"


def test_wide_ribbon_is_only_offered():
    # ~90 m gap -> ribbon shape but over the 50 m absorb cap.
    nbr = _NBR(box(84.00, 28.00581, 84.01, 28.0095))
    r = _rel(nbr)
    assert r is not None and r.gap_polygon is not None
    assert r.gap_width_m > 50
    assert r.gap_action == "offer"


def test_sliver_is_snapped():
    # ~3 m gap -> below the sliver width, closed automatically.
    nbr = _NBR(box(84.00, 28.00503, 84.01, 28.0090))
    r = _rel(nbr)
    assert r is not None
    assert r.gap_action == "snap"


# -- case (c): overlap AND gap against the same neighbour --------------------
def test_case_c_overlap_and_central_gap_both_reported():
    # Neighbour's straight south edge sits at lat 28.0098. The proposed north
    # edge rises above it at the two ends (overlap) and dips below it in the
    # middle (a ~44 m central gap).
    prop = Polygon([
        (84.000, 28.0000), (84.010, 28.0000), (84.010, 28.0102),
        (84.0070, 28.0102), (84.0060, 28.0094), (84.0040, 28.0094),
        (84.0030, 28.0102), (84.000, 28.0102),
    ])
    nbr = _NBR(box(84.000, 28.0098, 84.010, 28.020))
    rels = detect_relations(prop.__geo_interface__, [nbr], P)
    r = next((x for x in rels if x.id == "nbr-1"), None)
    assert r is not None
    assert r.overlap_ha > 0, "the end overlaps must still be reported"
    assert r.gap_polygon is not None, "the central gap must now surface (case c)"
    assert r.gap_ha > 0
