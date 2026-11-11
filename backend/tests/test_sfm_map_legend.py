"""The SFM tab's map legend lists only what this forest has (owner request, 2026-10-12)."""
from __future__ import annotations

import uuid

import pytest
from shapely.geometry import box

from app.services.sustainable_fm import map_legend as ml


def _units(n: int) -> list[dict]:
    # n boxes of 0.01 x 0.01 degrees side by side (a few tens of hectares each)
    return [{"id": str(i), "name": f"C{i + 1}", "geometry": box(85.5 + 0.011 * i, 27.4, 85.51 + 0.011 * i, 27.41)} for i in range(n)]


@pytest.fixture()
def feed(monkeypatch):
    """Serve a forest of units + per-unit SFM values without a database."""
    from app.services.operational_plan import thematic_overlay as to

    def install(values: dict):
        monkeypatch.setattr(to, "_load_sfm_unit_values", lambda db, cid, variant="baseline": values)
        monkeypatch.setattr(to, "_with_user_colours", lambda db, cid, spec: spec)
        monkeypatch.setattr(ml, "_leaf_units", lambda db, cid: _units(len(values)))

    return install


def _legend(spec_key: str):
    return ml.build_legend(None, uuid.uuid4(), spec_key)


def test_only_the_forest_types_this_forest_has_are_listed_with_units_and_hectares(feed):
    feed({
        "C1": {"effective_type_no": 3}, "C2": {"effective_type_no": 3}, "C3": {"effective_type_no": 7}, "C4": {"effective_type_no": None},
    })
    out = _legend("sfm__forest_type")
    assert out["state"] == "ready"
    by = {c["key"]: c for c in out["classes"]}
    assert set(by) >= {"3", "7"} and len(by) <= 3  # types 3 and 7 (plus a "no data" entry for the unit with no type), never all 14
    assert by["3"]["count"] == 2 and by["7"]["count"] == 1
    assert by["3"]["area_ha"] > by["7"]["area_ha"] > 0
    assert abs(sum(c["share_pct"] for c in out["classes"]) - 100.0) < 0.5
    assert all(c["color"].startswith("#") for c in out["classes"])


def test_orientation_lists_the_orientations_present(feed):
    feed({"C1": {"orientation": "Production"}, "C2": {"orientation": "Production"}, "C3": {"orientation": "Protection"}})
    out = _legend("sfm__orientation")
    assert {c["key"] for c in out["classes"]} == {"Production", "Protection"}  # "Conservation" is not in this forest: not in the legend
    assert next(c for c in out["classes"] if c["key"] == "Production")["count"] == 2


def test_stock_classes_that_no_unit_falls_in_are_left_out(feed):
    feed({"C1": {"gs_ge40_m3_per_ha": 180.0}, "C2": {"gs_ge40_m3_per_ha": 260.0}, "C3": {"gs_ge40_m3_per_ha": 190.0}})
    out = _legend("sfm__gs_vs_threshold")
    keys = {c["key"] for c in out["classes"]}
    assert "0" not in keys  # nothing under 150 m3/ha
    assert keys == {"1", "2"}
    assert next(c for c in out["classes"] if c["key"] == "1")["count"] == 2  # 180 and 190 sit in the 150-200 class


def test_nothing_stored_is_not_computed_never_a_build(feed):
    feed({})
    assert _legend("sfm__forest_type") == {"state": "not_computed", "key": "sfm__forest_type"}


def test_an_unknown_map_is_refused():
    with pytest.raises(KeyError):
        ml.build_legend(None, uuid.uuid4(), "sfm__nope")


def test_the_endpoint_answers_the_owner_and_not_someone_else(client, db):
    from app.models.calculation import Calculation
    from tests.integration.test_user_group_journey import _register

    headers, uid = _register(client)
    c = Calculation(user_id=uid, forest_name=f"SFM legend {uuid.uuid4().hex[:6]}")
    db.add(c)
    db.commit()
    ok = client.get(f"/api/calculations/{c.id}/sustainable-fm/map-legend/sfm__forest_type", headers=headers)
    assert ok.status_code == 200, ok.text
    assert ok.json()["state"] in ("not_computed", "no_data", "ready")
    assert client.get(f"/api/calculations/{c.id}/sustainable-fm/map-legend/sfm__nope", headers=headers).status_code == 404
    other, _ = _register(client)
    assert client.get(f"/api/calculations/{c.id}/sustainable-fm/map-legend/sfm__forest_type", headers=other).status_code in (403, 404)
