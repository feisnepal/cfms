"""FL-5: the fire-line routes - tick-list, ticking, drawn lines with per-segment widths, and re-widening."""
from __future__ import annotations

import pytest
from shapely.geometry import LineString, box, mapping

from app.services import fire_line_service as fls
from app.services import strip_geometry as sg
from tests.services.test_fire_line_service import H, W, X0, Y0, _calc
from tests.test_sampling_add_units import _headers

OUTER = sg.OUTER_LABEL


def url(calc, tail=""):
    return f"/api/calculations/{calc.id}/fire-lines{tail}"


@pytest.fixture()
def forest(client, db):
    calc = _calc(db, [("Left", box(X0, Y0, X0 + W / 2, Y0 + H)), ("Right", box(X0 + W / 2, Y0, X0 + W, Y0 + H))])
    fls.sync_fire_lines(db, calc.id)
    db.refresh(calc)
    return calc, _headers(client, db, calc)


def drawn_line(widths=1.5, extra=None):
    """A two-segment line across the Left unit, 120 m + 120 m or so, well inside the forest."""
    line = LineString([(X0 + W * 0.05, Y0 + H * 0.3), (X0 + W * 0.25, Y0 + H * 0.3), (X0 + W * 0.45, Y0 + H * 0.35)])
    return {"centerline": mapping(line), "widths_m": widths, **(extra or {})}


# ---------------------------------------------------------------- the tick-list
def test_the_list_shows_every_candidate_ticked_with_its_totals(client, forest):
    calc, h = forest
    body = client.get(url(calc), headers=h).json()
    assert body["status"]["state"] == "ok"
    assert sorted(r["name"] for r in body["rows"]) == sorted(["Left-Right", f"Left-{OUTER}", f"Right-{OUTER}"])
    assert all(r["ticked"] and r["strip_id"] and r["group"] == "boundary" for r in body["rows"])
    assert body["totals"]["boundary"]["count"] == 3 and body["totals"]["boundary"]["ha"] > 0
    assert body["drawn"] == []


def test_unticking_removes_the_strip_and_ticking_brings_it_back(client, forest):
    calc, h = forest
    rows = client.get(url(calc), headers=h).json()["rows"]
    key = next(r["unit_key"] for r in rows if r["name"] == "Left-Right")
    off = client.post(url(calc, "/decisions"), json={"changes": [{"unit_key": key, "included": False}]}, headers=h).json()
    row = next(r for r in off["rows"] if r["unit_key"] == key)
    assert row["ticked"] is False and row["strip_id"] is None and off["totals"]["boundary"]["count"] == 2
    again = client.post(url(calc, "/decisions"), json={"changes": [{"unit_key": key, "included": False}]}, headers=h).json()
    assert again["totals"]["boundary"]["count"] == 2                                  # the same list twice: the same state
    on = client.post(url(calc, "/decisions"), json={"changes": [{"unit_key": key, "included": True}]}, headers=h).json()
    row = next(r for r in on["rows"] if r["unit_key"] == key)
    assert row["ticked"] is True and row["strip_id"] and on["totals"]["boundary"]["count"] == 3


def test_select_none_then_select_all(client, forest):
    calc, h = forest
    keys = [r["unit_key"] for r in client.get(url(calc), headers=h).json()["rows"]]
    none = client.post(url(calc, "/decisions"), json={"changes": [{"unit_key": k, "included": False} for k in keys]}, headers=h).json()
    assert none["totals"] == {} and not any(r["ticked"] for r in none["rows"])
    every = client.post(url(calc, "/decisions"), json={"changes": [{"unit_key": k, "included": True} for k in keys]}, headers=h).json()
    assert every["totals"]["boundary"]["count"] == 3 and all(r["ticked"] for r in every["rows"])


def test_a_regenerate_keeps_the_unticks(client, forest):
    calc, h = forest
    key = next(r["unit_key"] for r in client.get(url(calc), headers=h).json()["rows"] if r["name"] == "Left-Right")
    client.post(url(calc, "/decisions"), json={"changes": [{"unit_key": key, "included": False}]}, headers=h)
    out = client.post(url(calc, "/regenerate"), json={}, headers=h).json()
    assert out["totals"]["boundary"]["count"] == 2 and next(r for r in out["rows"] if r["unit_key"] == key)["ticked"] is False


# ---------------------------------------------------------------- drawing
def test_the_preview_shows_the_strip_and_saves_nothing(client, forest):
    calc, h = forest
    before = client.get(url(calc), headers=h).json()
    r = client.post(url(calc, "/preview"), json=drawn_line([1.0, 2.0]), headers=h)
    assert r.status_code == 200, r.text
    p = r.json()
    assert p["segment_widths_m"] == [1.0, 2.0] and p["length_m"] > 200 and p["area_ha"] > 0 and p["parts"] == 1
    assert p["geometry"]["type"] in ("Polygon", "MultiPolygon") and p["name"].startswith("Left")
    assert client.get(url(calc), headers=h).json()["totals"] == before["totals"]


def test_a_single_width_applies_to_every_segment(client, forest):
    calc, h = forest
    p = client.post(url(calc, "/preview"), json=drawn_line(2.0), headers=h).json()
    assert p["segment_widths_m"] == [2.0, 2.0]
    assert p["area_ha"] * 10_000 == pytest.approx(p["length_m"] * 4.0, rel=0.05)


def test_creating_a_drawn_line_and_replaying_it(client, forest):
    calc, h = forest
    body = drawn_line([1.0, 3.0], {"name": "My ridge line", "client_id": "c-123"})
    first = client.post(url(calc), json=body, headers=h)
    assert first.status_code == 201, first.text
    again = client.post(url(calc), json=body, headers=h)
    assert again.json()["replayed"] is True and again.json()["created"] == first.json()["created"]
    listed = client.get(url(calc), headers=h).json()
    assert [d["name"] for d in listed["drawn"]] == ["My ridge line"] and listed["totals"]["drawn"]["count"] == 1
    assert listed["drawn"][0]["segment_widths_m"] == [1.0, 3.0]


def test_a_drawn_line_survives_a_regenerate_and_an_untick_of_everything_else(client, forest):
    calc, h = forest
    client.post(url(calc), json=drawn_line(1.5, {"name": "Mine", "client_id": "c-1"}), headers=h)
    keys = [r["unit_key"] for r in client.get(url(calc), headers=h).json()["rows"]]
    client.post(url(calc, "/decisions"), json={"changes": [{"unit_key": k, "included": False} for k in keys]}, headers=h)
    out = client.post(url(calc, "/regenerate"), json={}, headers=h).json()
    assert [d["name"] for d in out["drawn"]] == ["Mine"]


def test_changing_the_widths_of_a_line_marks_it_edited(client, forest):
    calc, h = forest
    created = client.post(url(calc), json=drawn_line(1.0, {"name": "Mine", "client_id": "c-2"}), headers=h).json()
    sid = created["created"][0]
    narrow = client.get(url(calc), headers=h).json()["drawn"][0]["area_ha"]
    r = client.patch(url(calc, f"/{sid}/widths"), json={"widths_m": [3.0, 3.0]}, headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["area_ha"] == pytest.approx(narrow * 3.0, rel=0.1)
    # a generated strip becomes 'edited' and a regenerate leaves it alone
    row = next(x for x in client.get(url(calc), headers=h).json()["rows"] if x["name"] == "Left-Right")
    client.patch(url(calc, f"/{row['strip_id']}/widths"), json={"widths_m": [4.0]}, headers=h)
    client.post(url(calc, "/regenerate"), json={}, headers=h)
    after = next(x for x in client.get(url(calc), headers=h).json()["rows"] if x["name"] == "Left-Right")
    assert after["edited"] is True and after["strip_id"] == row["strip_id"] and after["area_ha"] > row["area_ha"]


# ---------------------------------------------------------------- errors and access
def test_bad_requests_are_friendly(client, forest):
    calc, h = forest
    bad = client.post(url(calc, "/preview"), json=drawn_line([1.0]), headers=h)             # 2 segments, 1 width
    assert bad.status_code == 400 and bad.json()["detail"]["code"] == "bad_widths"
    wide = client.post(url(calc, "/preview"), json=drawn_line(80.0), headers=h)
    assert wide.status_code == 400 and wide.json()["detail"]["code"] == "bad_widths"
    point = client.post(url(calc, "/preview"), json={"centerline": {"type": "Point", "coordinates": [X0, Y0]}, "widths_m": 1.5}, headers=h)
    assert point.status_code == 400 and point.json()["detail"]["code"] == "bad_geometry"
    away = {"centerline": mapping(LineString([(X0 + 1, Y0 + 1), (X0 + 1.1, Y0 + 1)])), "widths_m": 1.5}
    out = client.post(url(calc, "/preview"), json=away, headers=h)
    assert out.status_code == 422 and out.json()["detail"]["code"] == "outside_forest"
    assert client.patch(url(calc, "/no-such-id/widths"), json={"widths_m": 2.0}, headers=h).status_code == 404


def test_a_locked_structure_refuses_writes_but_still_lists(client, db, forest):
    calc, h = forest
    calc.structure_locked = True
    db.commit()
    assert client.get(url(calc), headers=h).status_code == 200
    assert client.post(url(calc), json=drawn_line(), headers=h).status_code == 423
    assert client.post(url(calc, "/decisions"), json={"changes": [{"unit_key": "x", "included": False}]}, headers=h).status_code == 423
    assert client.post(url(calc, "/regenerate"), json={}, headers=h).status_code == 423


def test_nobody_else_can_use_them(client, db, forest):
    from tests.services.test_sampling_stratified import _user

    calc, _ = forest
    stranger = _user(db)
    r = client.post("/api/auth/login", json={"email": stranger.email, "password": "TestPass123!"})
    if r.status_code != 200:
        pytest.skip("cannot log in a second test user here")
    other = {"Authorization": f"Bearer {r.json()['access_token']}"}
    assert client.get(url(calc), headers=other).status_code == 403
    assert client.post(url(calc), json=drawn_line(), headers=other).status_code == 403


def test_it_needs_a_login(client, forest):
    calc, _ = forest
    assert client.get(url(calc)).status_code in (401, 403)


# ---------------------------------------------------------------- "Clear data" on the sub-area layer
def test_clearing_the_sub_area_layer_removes_the_fire_lines_too_and_they_stay_gone(client, db, forest):
    """It used to answer "deleted" and leave every fire line (owner, 2026-10-20)."""
    calc, h = forest
    assert client.get(url(calc), headers=h).json()["totals"]["boundary"]["count"] == 3
    r = client.delete(f"/api/forests/calculations/{calc.id}/sub-areas", headers=h)
    assert r.status_code == 200 and r.json()["deleted_count"] == 3
    body = client.get(url(calc), headers=h).json()
    assert body["totals"].get("boundary", {}).get("count", 0) == 0 and all(not row["ticked"] for row in body["rows"])
    fls.sync_fire_lines(db, calc.id, force=True)                                   # a regenerate does not bring them back
    db.refresh(calc)
    assert not [s for s in calc.result_data["sub_areas"] if s.get("category") == "fire_line"]
    ticked = client.post(url(calc, "/decisions"), json={"changes": [{"unit_key": row["unit_key"], "included": True} for row in body["rows"]]}, headers=h).json()
    assert ticked["totals"]["boundary"]["count"] == 3                              # and they can be ticked again
