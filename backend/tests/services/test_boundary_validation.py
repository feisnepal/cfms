"""boundary_validation — the four forest-boundary upload rules (UNIFIED_UPLOAD_PLAN §5).

R0 geometry sanity · R1 within Nepal · R2 area ≤ 1000 ha ·
R3 built-up + cropland ≤ 40% · R4 protected area must be Buffer Zone (5% tol).

`_check_geometry` runs against real PostGIS (the `db` fixture). The threshold
logic for R2–R4 is exercised with a fake session returning canned rows, so the
tests do not need the `admin.*` / `rasters.*` reference layers (which the
migrations-only test DB lacks).
"""

from __future__ import annotations

import contextlib
from types import SimpleNamespace

import pytest

from app.services import boundary_validation as bv


# ── fake session ────────────────────────────────────────────────────────
class _FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def first(self):
        return self._rows[0] if self._rows else None

    def scalar(self):
        if not self._rows:
            return None
        r = self._rows[0]
        return r[0] if isinstance(r, (list, tuple)) else r

    def fetchall(self):
        return list(self._rows)


class _FakeDB:
    """Returns `responder(sql, params)` for every execute; nested txns are no-ops."""

    def __init__(self, responder):
        self._responder = responder

    def execute(self, stmt, params=None):
        return _FakeResult(self._responder(str(stmt), params or {}))

    def begin_nested(self):
        return contextlib.nullcontext()


# ── BoundaryReport ─────────────────────────────────────────────────────
def test_report_ok_is_false_only_when_an_error_is_present():
    rep = bv.BoundaryReport()
    assert rep.ok
    rep.add("x", "warning", "w", "w")
    assert rep.ok and rep.warnings and not rep.errors
    rep.add("y", "error", "e", "e")
    assert not rep.ok and rep.errors


def test_report_as_dict_groups_by_level():
    rep = bv.BoundaryReport(facts={"area_ha": 42.0})
    rep.add("a", "error", "e", "e")
    rep.add("b", "warning", "w", "w")
    rep.add("c", "info", "i", "i")
    d = rep.as_dict()
    assert d["ok"] is False
    assert [x["code"] for x in d["errors"]] == ["a"]
    assert [x["code"] for x in d["warnings"]] == ["b"]
    assert [x["code"] for x in d["info"]] == ["c"]
    assert d["facts"]["area_ha"] == 42.0


# ── R0 geometry (real PostGIS) ─────────────────────────────────────────
_INSIDE_NEPAL = (
    "POLYGON((85.30 27.68, 85.33 27.68, 85.33 27.70, 85.30 27.70, 85.30 27.68))"
)


def test_geometry_ok_for_a_plain_polygon_in_nepal(db):
    rep = bv.BoundaryReport()
    assert bv._check_geometry(db, _INSIDE_NEPAL, rep) is True
    assert rep.ok


def test_geometry_rejects_a_line(db):
    rep = bv.BoundaryReport()
    assert bv._check_geometry(db, "LINESTRING(85.3 27.6, 85.4 27.7)", rep) is False
    assert any(f.code == "boundary.not_polygon" for f in rep.errors)


def test_geometry_rejects_self_intersecting_polygon(db):
    bowtie = (
        "POLYGON((85.30 27.60, 85.40 27.70, 85.30 27.70, 85.40 27.60, 85.30 27.60))"
    )
    rep = bv.BoundaryReport()
    assert bv._check_geometry(db, bowtie, rep) is False
    assert any(f.code == "boundary.invalid_geometry" for f in rep.errors)


def test_geometry_does_not_reject_far_coordinates_on_its_own(db):
    # R0 no longer owns "outside Nepal" — the precise verdict (and any border
    # clipping) is R1's job against admin.province. A far-away, non-swapped
    # polygon is geometrically usable; it is R1 that will reject it.
    far = "POLYGON((10 50, 11 50, 11 51, 10 51, 10 50))"
    rep = bv.BoundaryReport()
    assert bv._check_geometry(db, far, rep) is True
    assert not rep.errors


def test_geometry_flags_swapped_lat_lon(db):
    # Nepal point ~ (85.3, 27.6); swapped is (27.6, 85.3) — still a valid polygon
    swapped = (
        "POLYGON((27.60 85.30, 27.70 85.30, 27.70 85.33, 27.60 85.33, 27.60 85.30))"
    )
    rep = bv.BoundaryReport()
    assert bv._check_geometry(db, swapped, rep) is False
    assert any(f.code == "boundary.latlon_swapped" for f in rep.errors)


def test_geometry_warns_on_multipart(db):
    two = (
        "MULTIPOLYGON(((85.30 27.60, 85.32 27.60, 85.32 27.62, 85.30 27.62, 85.30 27.60)),"
        "((85.40 27.60, 85.42 27.60, 85.42 27.62, 85.40 27.62, 85.40 27.60)))"
    )
    rep = bv.BoundaryReport()
    assert bv._check_geometry(db, two, rep) is True
    assert any(f.code == "boundary.multipart" for f in rep.warnings)


# ── R1 Nepal province clip ───────────────────────────────────────────
def _nepal_row(
    total, inside, wkt="MULTIPOLYGON(((85 27,85.1 27,85.1 27.1,85 27.1,85 27)))"
):
    return SimpleNamespace(total_ha=total, inside_ha=inside, inside_wkt=wkt)


def test_r1_fully_outside_nepal_is_an_error_and_keeps_no_geometry():
    fake = _FakeDB(lambda sql, p: [_nepal_row(100.0, 0.0, "MULTIPOLYGON EMPTY")])
    rep = bv.BoundaryReport()
    out = bv._nepal_clip(fake, _INSIDE_NEPAL, rep)
    assert out is None
    assert any(f.code == "boundary.outside_nepal" for f in rep.errors)


def test_r1_fully_inside_is_accepted_unchanged():
    fake = _FakeDB(lambda sql, p: [_nepal_row(100.0, 100.0)])
    rep = bv.BoundaryReport()
    assert bv._nepal_clip(fake, _INSIDE_NEPAL, rep) is None
    assert not rep.errors and not rep.warnings


def test_r1_border_sliver_is_tolerated_without_a_notice():
    fake = _FakeDB(lambda sql, p: [_nepal_row(100.0, 99.8)])  # 0.2% out
    rep = bv.BoundaryReport()
    assert bv._nepal_clip(fake, _INSIDE_NEPAL, rep) is None
    assert not rep.errors and not rep.warnings


def test_r1_straddling_border_clips_and_warns():
    clip_wkt = "MULTIPOLYGON(((85 27,85.05 27,85.05 27.05,85 27.05,85 27)))"
    fake = _FakeDB(lambda sql, p: [_nepal_row(100.0, 70.0, clip_wkt)])  # 30% out
    rep = bv.BoundaryReport()
    out = bv._nepal_clip(fake, _INSIDE_NEPAL, rep)
    assert out == clip_wkt
    assert not rep.errors
    w = [f for f in rep.warnings if f.code == "boundary.clipped_to_nepal"]
    assert w and w[0].detail["removed_pct"] == 30.0 and w[0].detail["kept_ha"] == 70.0


# ── R2 area ≤ 1000 ha ─────────────────────────────────────────────────
def test_r2_error_above_1000_ha():
    fake = _FakeDB(lambda sql, p: [(1500.0,)])
    rep = bv.BoundaryReport()
    bv._check_area(fake, _INSIDE_NEPAL, rep)
    assert any(f.code == "boundary.area_exceeds_limit" for f in rep.errors)
    assert rep.facts["area_ha"] == 1500.0


def test_r2_ok_at_the_limit():
    fake = _FakeDB(lambda sql, p: [(1000.0,)])
    rep = bv.BoundaryReport()
    bv._check_area(fake, _INSIDE_NEPAL, rep)
    assert not rep.errors


# ── R3 built-up + cropland ≤ 40% ──────────────────────────────────────
def _lc_rows(built, crop, tree):
    return [
        SimpleNamespace(code=bv._ESA_BUILT_UP, n=built),
        SimpleNamespace(code=bv._ESA_CROPLAND, n=crop),
        SimpleNamespace(code=10, n=tree),
    ]


def test_r3_error_when_builtup_plus_cropland_over_40pct():
    fake = _FakeDB(lambda sql, p: _lc_rows(built=30, crop=20, tree=50))  # 50%
    rep = bv.BoundaryReport()
    bv._check_builtup_cropland(fake, _INSIDE_NEPAL, rep)
    assert any(f.code == "boundary.builtup_cropland_exceeds_limit" for f in rep.errors)
    assert rep.facts["built_up_plus_cropland_pct"] == 50.0


def test_r3_ok_at_40pct():
    fake = _FakeDB(lambda sql, p: _lc_rows(built=25, crop=15, tree=60))  # 40%
    rep = bv.BoundaryReport()
    bv._check_builtup_cropland(fake, _INSIDE_NEPAL, rep)
    assert not rep.errors


def test_r3_info_when_raster_has_no_coverage():
    fake = _FakeDB(lambda sql, p: [])
    rep = bv.BoundaryReport()
    bv._check_builtup_cropland(fake, _INSIDE_NEPAL, rep)
    assert any(f.code == "boundary.landcover_no_coverage" for f in rep.findings)
    assert not rep.errors


# ── R4 protected area / Buffer Zone ───────────────────────────────────
def _pa_row(total, bz, non_bz, descrs, names="Some NP"):
    return SimpleNamespace(
        total_ha=total, bz_ha=bz, non_bz_ha=non_bz, descrs=descrs, names=names
    )


def test_r4_outside_any_protected_area_is_a_pass():
    fake = _FakeDB(lambda sql, p: [_pa_row(100.0, 0.0, 0.0, None, None)])
    rep = bv.BoundaryReport()
    bv._check_protected_area(fake, _INSIDE_NEPAL, rep)
    assert not rep.errors and not rep.warnings
    assert rep.facts["protected_area"] == "outside"


def test_r4_entirely_in_a_buffer_zone_is_a_pass():
    fake = _FakeDB(lambda sql, p: [_pa_row(100.0, 100.0, 0.0, "Buffer Zone")])
    rep = bv.BoundaryReport()
    bv._check_protected_area(fake, _INSIDE_NEPAL, rep)
    assert not rep.errors
    assert any(f.code == "boundary.protected_area_buffer_zone" for f in rep.findings)


def test_r4_small_non_buffer_overlap_is_a_warning():
    fake = _FakeDB(
        lambda sql, p: [_pa_row(100.0, 90.0, 4.0, "Buffer Zone, National Park")]
    )
    rep = bv.BoundaryReport()
    bv._check_protected_area(fake, _INSIDE_NEPAL, rep)
    assert not rep.errors
    assert any(
        f.code == "boundary.protected_area_non_buffer_tolerance" for f in rep.warnings
    )
    assert rep.facts["protected_area"]["non_buffer_pct"] == 4.0


def test_r4_large_non_buffer_overlap_is_an_error():
    fake = _FakeDB(lambda sql, p: [_pa_row(100.0, 0.0, 40.0, "National Park")])
    rep = bv.BoundaryReport()
    bv._check_protected_area(fake, _INSIDE_NEPAL, rep)
    assert any(
        f.code == "boundary.protected_area_outside_buffer_zone" for f in rep.errors
    )


# ── orchestrator resilience ──────────────────────────────────────────
def test_validate_never_raises_and_degrades_missing_layers_to_info():
    def boom(sql, p):
        s = sql.lower()
        if "st_isvalid" in s:  # geometry check succeeds
            return [
                SimpleNamespace(
                    valid=True,
                    reason="",
                    gtype="POLYGON",
                    empty=False,
                    nparts=1,
                    xmin=85.3,
                    xmax=85.33,
                    ymin=27.68,
                    ymax=27.70,
                )
            ]
        raise RuntimeError("relation does not exist")

    rep = bv.validate_forest_boundary(_FakeDB(boom), _INSIDE_NEPAL, forest_name="X")
    assert rep.ok  # nothing could be checked, so nothing blocks
    codes = {f.code for f in rep.findings if f.level == "info"}
    assert "boundary.nepal_check_unavailable" in codes
    assert "boundary.landcover_unavailable" in codes
    assert "boundary.protected_area_check_unavailable" in codes


# ── enforce_boundary_rules (the write-path gate) ─────────────────────
def test_enforce_raises_on_an_error_and_carries_the_422_detail():
    fake = _FakeDB(lambda sql, p: [(1500.0,)])  # area check → over 1000 ha

    def geom_ok(sql, p):
        if "st_isvalid" in sql.lower():
            return [
                SimpleNamespace(
                    valid=True,
                    reason="",
                    gtype="POLYGON",
                    empty=False,
                    nparts=1,
                    xmin=85.3,
                    xmax=85.33,
                    ymin=27.68,
                    ymax=27.70,
                )
            ]
        if "st_area" in sql.lower():
            return [(1500.0,)]
        return []

    with pytest.raises(bv.BoundaryRulesViolation) as ei:
        bv.enforce_boundary_rules(_FakeDB(geom_ok), _INSIDE_NEPAL, forest_name="X")
    detail = ei.value.detail
    assert detail["code"] == "boundary_validation_failed"
    assert "1,500 ha" in detail["message"] or "1500" in detail["message"]
    assert detail["boundary_validation"]["ok"] is False
    _ = fake  # noqa: intentionally unused


def test_enforce_returns_the_report_when_clean():
    def geom_ok(sql, p):
        s = sql.lower()
        if "st_isvalid" in s:
            return [
                SimpleNamespace(
                    valid=True,
                    reason="",
                    gtype="POLYGON",
                    empty=False,
                    nparts=1,
                    xmin=85.3,
                    xmax=85.33,
                    ymin=27.68,
                    ymax=27.70,
                )
            ]
        if "province" in s or "st_intersection" in s:
            return [_nepal_row(500.0, 500.0)]
        if "st_area" in s:
            return [(500.0,)]
        if "esa_world_cover" in s:
            return [SimpleNamespace(code=10, n=100)]
        if "protected_area" in s:
            return [
                SimpleNamespace(
                    total_ha=500.0, bz_ha=0.0, non_bz_ha=0.0, descrs=None, names=None
                )
            ]
        return []

    res = bv.enforce_boundary_rules(_FakeDB(geom_ok), _INSIDE_NEPAL, forest_name="X")
    assert res.report.ok
    assert res.clipped is False
    assert res.effective_wkt == _INSIDE_NEPAL


# ── guarded integration ──────────────────────────────────────────────
def test_integration_runs_end_to_end_if_reference_layers_exist(db):
    from sqlalchemy import text as _t

    has_admin = db.execute(
        _t(
            "SELECT 1 FROM information_schema.tables "
            "WHERE table_schema='admin' AND table_name='province'"
        )
    ).first()
    if not has_admin:
        pytest.skip("admin.* reference layers not in the test database")
    rep = bv.validate_forest_boundary(db, _INSIDE_NEPAL, forest_name="smoke")
    assert isinstance(rep.as_dict(), dict)
    assert "area_ha" in rep.facts
