"""G1 - hole-fill scope-aware (FS-4a.12).

Hole-filling (``_fill_holes`` in ``geometry_edit_service`` and
``auto_block_service``) must never silently re-absorb a hole that is
deliberately excluded ground - private land or a protection working-circle
unit - just because it is smaller than the ~1 ha MMU artifact threshold
(G1: "test with a 0.3 ha plot"; F7's PL_ENCLAVE is that plot). Both services
take ``protect_geom`` (``virtual_root.hole_protect_geom`` = private land ∪
protection units) and keep any hole that materially overlaps it (>50 % of
the hole's own area), regardless of size.
"""

from __future__ import annotations

from shapely.geometry import LinearRing, Polygon
from shapely.geometry import box

from app.models.calculation import Calculation
from app.services import auto_block_service as svc
from app.services import geometry_edit_service as geo
from app.services.forest_units.area_model import forest_area_geom, private_land_geom
from app.services.forest_units.operations.virtual_root import hole_protect_geom

from . import fixtures

# Geometry frame: 1e-5 deg ~ 1 m near (84, 27). A 0.01 deg square is a bit over
# 110 ha; a 0.0005 deg square is ~0.3 ha (below the 1 ha hole-fill threshold).
_BIG = box(84.00, 27.00, 84.01, 27.01)
_SMALL_HOLE = box(84.004, 27.004, 84.0045, 27.0045)  # ~0.3 ha < 1 ha
_BIG_HOLE = box(84.002, 27.002, 84.008, 27.008)  # ~40 ha >= 1 ha
_PROTECT = box(84.0035, 27.0035, 84.0055, 27.0055)  # contains _SMALL_HOLE


def _with_holes(shell, holes):
    return Polygon(shell.exterior, [LinearRing(h.exterior.coords) for h in holes])


def _hole_area_ha(ring_poly, *, m2=False):
    a = geo.area_sqm(ring_poly)
    return a if m2 else a / 10_000.0


# ---------------------------------------------------------------------------
# geometry_edit_service._fill_holes / sanitize_geometry
# ---------------------------------------------------------------------------

def test_geo_fill_keeps_small_hole_overlapping_protect_geom():
    g = _with_holes(_BIG, [_SMALL_HOLE])
    filled, warnings = geo._fill_holes(g, protect_geom=_PROTECT)
    assert len(filled.interiors) == 1  # the 0.3 ha protected hole survives
    assert 0.2 < _hole_area_ha(Polygon(filled.interiors[0])) < 0.4
    assert warnings == []


def test_geo_fill_removes_small_hole_without_protect_geom():
    """Regression guard: with no protect_geom the old behaviour stays - a
    hole below the threshold is an MMU artifact void and is filled."""
    g = _with_holes(_BIG, [_SMALL_HOLE])
    filled, warnings = geo._fill_holes(g)
    assert len(filled.interiors) == 0
    assert warnings == [geo.W_HOLES_FILLED]


def test_geo_fill_keeps_big_hole_without_protect_geom():
    g = _with_holes(_BIG, [_BIG_HOLE])
    filled, _ = geo._fill_holes(g)
    assert len(filled.interiors) == 1
    assert _hole_area_ha(Polygon(filled.interiors[0])) > 1.0


def test_geo_fill_fills_only_the_untouched_hole_when_one_is_protected():
    other = box(84.0085, 27.004, 84.009, 27.0045)  # ~0.3 ha, NOT protected
    g = _with_holes(_BIG, [_SMALL_HOLE, other])
    filled, warnings = geo._fill_holes(g, protect_geom=_PROTECT)
    assert len(filled.interiors) == 1
    kept = Polygon(filled.interiors[0])
    assert kept.intersection(_SMALL_HOLE).area / _SMALL_HOLE.area > 0.99
    assert warnings == [geo.W_HOLES_FILLED]


def test_geo_hole_is_protected_overlap_fraction():
    hole = box(84.004, 27.004, 84.0045, 27.0045)
    covering_six_tenths = box(84.004, 27.004, 84.0045, 27.0043)  # 60 % of hole
    covering_two_fifths = box(84.004, 27.004, 84.0045, 27.0042)  # 40 % of hole
    assert geo._hole_is_protected(hole, covering_six_tenths) is True
    assert geo._hole_is_protected(hole, covering_two_fifths) is False
    # None / empty protect_geom never count as protected ground.
    assert geo._hole_is_protected(hole, None) is False
    from shapely.geometry import Point
    assert geo._hole_is_protected(hole, Point(84.0, 27.0).buffer(0)) is False


def test_geo_hole_is_protected_zero_area_hole_is_never_protected():
    from shapely.geometry import LineString
    degenerate = LineString([(0, 0), (1, 1)])
    assert geo._hole_is_protected(degenerate, _PROTECT) is False


def test_sanitize_geometry_keeps_protected_hole():
    g = _with_holes(_BIG, [_SMALL_HOLE])
    sanitized, warnings = geo.sanitize_geometry(g, protect_geom=_PROTECT)
    assert len(sanitized.interiors) == 1
    assert 0.2 < _hole_area_ha(Polygon(sanitized.interiors[0])) < 0.4
    assert geo.W_HOLES_FILLED not in warnings


# ---------------------------------------------------------------------------
# auto_block_service._fill_holes (pieces-list copy)
# ---------------------------------------------------------------------------

def test_auto_block_fill_keeps_protected_hole():
    pieces = [_with_holes(_BIG, [_SMALL_HOLE])]
    filled = svc._fill_holes(pieces, protect_geom=_PROTECT)
    assert len(filled[0].interiors) == 1
    assert 0.2 < _hole_area_ha(Polygon(filled[0].interiors[0])) < 0.4


def test_auto_block_fill_removes_small_hole_without_protect_geom():
    pieces = [_with_holes(_BIG, [_SMALL_HOLE])]
    filled = svc._fill_holes(pieces)
    assert len(filled[0].interiors) == 0


# ---------------------------------------------------------------------------
# hole_protect_geom against the structure fixtures
# ---------------------------------------------------------------------------

def _calc(db, forest):
    return db.query(Calculation).filter(Calculation.id == forest.calc_id).first()


def test_hole_protect_geom_none_without_private_or_protection(db, make_forest):
    f = make_forest("F0")
    calc = _calc(db, f)
    assert hole_protect_geom(db, calc) is None


def test_hole_protect_geom_covers_f7_private_land_including_the_0_3_ha_enclave(db, make_forest):
    f = make_forest("F7")
    calc = _calc(db, f)
    protect = hole_protect_geom(db, calc)
    assert protect is not None
    enclave = f.sub_geoms["PL_ENCLAVE"]
    pr = private_land_geom(calc)
    assert pr is not None
    # The union is all private land, never less.
    assert protect.intersection(enclave).area / enclave.area > 0.99
    assert protect.area >= pr.area * 0.99


def test_f7_0_3_ha_enclave_survives_fill_holes_on_the_forest_area_shell(db, make_forest):
    """The G1 acceptance test: F7's 0.3 ha private plot is an interior hole of
    the forest-area shell and must survive ``_fill_holes`` (it is excluded
    ground, not an MMU artifact), and WITHOUT protect_geom it is silent-absorbed
    - demonstrating exactly what G1 fixed."""
    f = make_forest("F7")
    calc = _calc(db, f)
    enclave = f.sub_geoms["PL_ENCLAVE"]
    shell = forest_area_geom(calc)
    assert shell is not None

    def rings(g):
        polys = [g] if g.geom_type == "Polygon" else list(g.geoms)
        return [Polygon(p.interiors[i]) for p in polys for i in range(len(p.interiors))]

    # The shell itself carries the 0.3 ha plot as a hole.
    pre = [r for r in rings(shell) if r.intersection(enclave).area / enclave.area > 0.99]
    assert len(pre) == 1
    assert 0.2 < _hole_area_ha(pre[0]) < 0.4

    protect = hole_protect_geom(db, calc)
    filled, warnings = geo._fill_holes(shell, protect_geom=protect)
    post = [r for r in rings(filled) if r.intersection(enclave).area / enclave.area > 0.99]
    assert len(post) == 1  # survives
    assert 0.2 < _hole_area_ha(post[0]) < 0.4
    assert warnings == []  # nothing was filled: every hole is big or protected

    # Regression guard: without protect_geom the plot is below the 1 ha
    # artifact threshold and gets re-absorbed -> G1's bug, still how the caller
    # behaves when it does not know the hole is excluded ground.
    bare, warnings_bare = geo._fill_holes(shell)
    bare_rings = rings(bare)
    assert not any(r.intersection(enclave).area / enclave.area > 0.99 for r in bare_rings)
    assert warnings_bare == [geo.W_HOLES_FILLED]


def test_hole_protect_geom_includes_protection_working_circle_units(db, make_forest):
    f = make_forest("F8")
    calc = _calc(db, f)
    protect = hole_protect_geom(db, calc)
    assert protect is not None
    p1 = f.unit_geoms["P-1"]
    assert protect.intersection(p1).area / p1.area > 0.99