"""P10 — building-footprint fallback for household coordinates
(HOUSEHOLD_VULNERABILITY_ANALYSIS_PLAN.md §9).

When ``household_information.latitude/longitude`` is a placeholder or off-grid,
each household is moved to a real building footprint from
``user_group_buildings`` so the hazard grids can be sampled per household.
"""

from __future__ import annotations

import uuid

from affine import Affine

from app.models.calculation import Calculation
from app.models.user import User, UserRole
from app.services.operational_plan import household_vulnerability as hv

import pytest as _pytest_for_limit

pytestmark = _pytest_for_limit.mark.usefixtures("relax_user_group_limit")  # the fixtures here draw an 8,590 ha group


class _Grid:
    """Minimal GridSpec stand-in: only `.transform` / `.width` / `.height`."""

    # lon [85.00, 85.10], lat [27.40, 27.50], 100 × 100 cells
    transform = Affine(0.001, 0.0, 85.00, 0.0, -0.001, 27.50)
    width = 100
    height = 100


# ── _coords_usable (pure) ───────────────────────────────────────────────


def _hh(lon, lat, tole="T", i=0):
    return {"id": f"h{i}", "address_tole": tole, "longitude": lon, "latitude": lat}


def test_coords_usable_rejects_a_single_placeholder_point():
    hh = [_hh(85.30, 27.50, i=i) for i in range(20)]  # all identical
    assert hv._coords_usable(hh, _Grid()) is False


def test_coords_usable_rejects_off_grid_points():
    hh = [_hh(85.30 + i * 0.001, 27.50 + i * 0.001, i=i) for i in range(20)]
    # varied, but ~0.3° east of the grid → outside the 0.02° margin
    assert hv._coords_usable(hh, _Grid()) is False


def test_coords_usable_accepts_varied_in_grid_points():
    hh = [_hh(85.04 + i * 0.0005, 27.44 + i * 0.0005, i=i) for i in range(20)]
    assert hv._coords_usable(hh, _Grid()) is True


# ── DB helpers ─────────────────────────────────────────────────────────


def _seed_buildings(db, calc, *, settlements):
    """settlements = {name: [(lon, lat), …]}"""
    from geoalchemy2.shape import from_shape
    from shapely.geometry import MultiPolygon, Point
    from app.models.user_group import UserGroupBuilding, UserGroupExtent

    ext = UserGroupExtent(
        calculation_id=calc.id,
        user_id=calc.user_id,
        extent_geometry=from_shape(
            MultiPolygon([Point(85.05, 27.45).buffer(0.05)]), srid=4326
        ),
        source_type="manual",
    )
    db.add(ext)
    db.flush()
    for name, pts in settlements.items():
        db.add(
            UserGroupBuilding(
                extent_id=ext.id,
                settlement_name=name,
                building_count=len(pts),
                buildings_geojson=[
                    {"lon": lon, "lat": lat, "area": 100.0} for lon, lat in pts
                ],
            )
        )
    db.commit()


def _calc(db):
    u = User(
        email=f"hc{uuid.uuid4().hex[:8]}@t.com",
        full_name="HC",
        role=UserRole.USER,
        hashed_password="x",
    )
    db.add(u)
    db.flush()
    c = Calculation(user_id=u.id, uploaded_filename="x.csv")
    db.add(c)
    db.flush()
    return c


# ── _settlement_building_centroids ─────────────────────────────────────


def test_settlement_building_centroids_reads_geojson_list(db):
    calc = _calc(db)
    _seed_buildings(
        db,
        calc,
        settlements={
            "Chaukltol": [(85.03, 27.44), (85.031, 27.441)],
            "Shantichok": [(85.05, 27.42)],
        },
    )
    by = hv._settlement_building_centroids(db, calc.id)
    assert set(by) == {"chaukltol", "shantichok"}
    assert len(by["chaukltol"]) == 2
    assert by["shantichok"] == [(85.05, 27.42)]


def test_settlement_building_centroids_empty_without_user_group(db):
    calc = _calc(db)
    assert hv._settlement_building_centroids(db, calc.id) == {}


# ── _resolve_household_points ─────────────────────────────────────────


def test_resolve_moves_placeholder_households_to_footprints(db):
    calc = _calc(db)
    # 30 buildings spread across the grid
    pts = [(85.02 + i * 0.002, 27.41 + i * 0.002) for i in range(30)]
    _seed_buildings(db, calc, settlements={"Onlyville": pts})

    households = [
        _hh(85.30, 27.50, tole=f"गाउँ-{1 + i % 5}", i=i) for i in range(20)
    ]
    src = hv._resolve_household_points(db, calc.id, households, _Grid(), "auto")

    assert src == "building_footprint"
    assert all(h["coord_source"] == "building_footprint" for h in households)
    # every point is a real seeded building centroid, none is the placeholder
    seeded = set(pts)
    assert all((h["longitude"], h["latitude"]) in seeded for h in households)
    assert all(h["longitude"] != 85.30 for h in households)
    # the 5 distinct toles land in different windows → >1 distinct point
    per_tole = {}
    for h in households:
        per_tole.setdefault(h["address_tole"], set()).add(
            (h["longitude"], h["latitude"])
        )
    assert len({next(iter(v)) for v in per_tole.values()}) >= 3


def test_resolve_respects_survey_override(db):
    calc = _calc(db)
    _seed_buildings(db, calc, settlements={"X": [(85.05, 27.45)]})
    households = [_hh(85.30, 27.50, i=i) for i in range(5)]
    src = hv._resolve_household_points(db, calc.id, households, _Grid(), "survey")
    assert src == "survey"
    assert all(h["longitude"] == 85.30 for h in households)
    assert all(h["coord_source"] == "survey" for h in households)


def test_resolve_returns_none_without_buildings(db):
    calc = _calc(db)
    households = [_hh(85.30, 27.50, i=i) for i in range(5)]
    src = hv._resolve_household_points(db, calc.id, households, _Grid(), "auto")
    assert src == "none"
    assert all(h["longitude"] == 85.30 for h in households)


def test_resolve_keeps_usable_survey_coords_under_auto(db):
    calc = _calc(db)
    _seed_buildings(db, calc, settlements={"X": [(85.05, 27.45)]})
    households = [
        _hh(85.04 + i * 0.001, 27.44 + i * 0.001, i=i) for i in range(10)
    ]
    src = hv._resolve_household_points(db, calc.id, households, _Grid(), "auto")
    assert src == "survey"
    assert all(h["coord_source"] == "survey" for h in households)
    assert households[3]["longitude"] == 85.04 + 3 * 0.001  # untouched


# ── owner rule 2026-10-05: surveyed coordinates are kept; only households WITHOUT them go to buildings ──


def _pt(lon, lat, tole="T", i=0):
    return {"id": f"h{i}", "address_tole": tole, "longitude": lon, "latitude": lat}


def test_mixed_forest_keeps_survey_points_and_places_the_rest_on_buildings(monkeypatch):
    surveyed = [_pt(85.02 + 0.01 * i, 27.42 + 0.01 * i, i=i) for i in range(4)]
    unsurveyed = [_pt(None, None, i=10 + i) for i in range(3)]
    households = surveyed + unsurveyed
    before = [(h["longitude"], h["latitude"]) for h in surveyed]
    monkeypatch.setattr(hv, "_settlement_building_centroids", lambda db, cid: {"t": [(85.05, 27.45), (85.06, 27.46)]})

    src = hv._resolve_household_points(None, "c", households, _Grid(), "auto")

    assert src == "mixed"
    assert [(h["longitude"], h["latitude"]) for h in surveyed] == before  # untouched
    assert all(h["coord_source"] == "survey" for h in surveyed)
    assert all(h["coord_source"] == "building_footprint" and h["latitude"] is not None for h in unsurveyed)


def test_households_without_any_coordinates_all_go_to_buildings(monkeypatch):
    households = [_pt(None, None, i=i) for i in range(3)]
    monkeypatch.setattr(hv, "_settlement_building_centroids", lambda db, cid: {"t": [(85.05, 27.45)]})
    assert hv._resolve_household_points(None, "c", households, _Grid(), "auto") == "building_footprint"


def test_unplaced_household_when_no_buildings_exist(monkeypatch):
    households = [_pt(None, None, i=0), _pt(85.03, 27.43, i=1), _pt(85.04, 27.44, i=2)]
    monkeypatch.setattr(hv, "_settlement_building_centroids", lambda db, cid: {})
    src = hv._resolve_household_points(None, "c", households, _Grid(), "auto")
    assert src == "survey"
    assert households[0]["coord_source"] == "none" and households[0]["latitude"] is None


# ── owner decision 2026-10-05: household lat/lon is NOT used; every household goes to a building ──


def test_survey_coordinates_are_not_read_by_the_vulnerability_analysis(db, auth_headers):
    import uuid
    from sqlalchemy import text
    from app.models.user import User

    uid = str(db.query(User).filter(User.email == "testuser@example.com").first().id)
    cid = uuid.uuid4()
    db.execute(text("INSERT INTO calculations (id, user_id, forest_name, status) VALUES (:i,:u,'F','PROCESSING')"),
               {"i": cid, "u": uid})
    db.execute(text(
        "INSERT INTO household_information (id, calculation_id, house_no, surname, female_count, male_count, "
        "latitude, longitude, created_by, version) VALUES (:h,:c,1,'S',1,1,27.45,85.05,:u,0)"
    ), {"h": uuid.uuid4(), "c": cid, "u": uid})
    db.commit()

    rows = hv._fetch_households(db, cid)

    assert len(rows) == 1
    assert rows[0]["latitude"] is None and rows[0]["longitude"] is None  # present in the table, deliberately unused


def test_buildings_stand_in_for_households_when_there_is_no_household_data(monkeypatch):
    """No household records at all: one neutral stand-in per building footprint, each kept on its own building."""
    monkeypatch.setattr(hv, "_settlement_building_centroids", lambda db, cid: {"ghumaune": [(85.01, 27.41), (85.02, 27.42)], "": [(85.03, 27.43)]})

    rows = hv._buildings_as_households(None, "c")

    assert len(rows) == 3 and all(r["is_proxy"] for r in rows)
    assert {(r["longitude"], r["latitude"]) for r in rows} == {(85.01, 27.41), (85.02, 27.42), (85.03, 27.43)}
    assert all(r["female_count"] == 0 and r["prosperity_level"] is None for r in rows)  # no invented attributes


def test_a_stand_in_is_never_moved_by_the_resolver(monkeypatch):
    monkeypatch.setattr(hv, "_settlement_building_centroids", lambda db, cid: {"t": [(85.9, 27.9)]})
    proxy = {**_pt(85.05, 27.45, i=1), "is_proxy": True, "coord_source": "building_footprint"}
    src = hv._resolve_household_points(None, "c", [proxy], _Grid(), "building_footprint")
    assert (proxy["longitude"], proxy["latitude"]) == (85.05, 27.45)
    assert src == "building_footprint"
