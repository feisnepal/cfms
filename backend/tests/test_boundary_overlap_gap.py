"""Boundary preview / confirm — CLIP ONLY (2026-08-28 rework).

  - ``preview_boundary`` / ``points_preview`` clip the proposed boundary against
    adjoining forests and return ``overlapping_forests`` + ``resolved_geometry``.
    No gap analysis, no ``gaps`` list.
  - ``confirm_boundary`` 409s when a posted geometry still shares AREA with a
    neighbour; a shared edge (0-area) is fine.
  - A neighbour that splits the boundary in two yields a MultiPolygon and both
    parts are kept.
  - The PUT /boundary edit path clips too — a vertex dragged into a neighbour is
    trimmed back.
  - ``file_dispute`` gap path is unchanged (a separate DFO tool).
"""

from __future__ import annotations

import os
from uuid import uuid4

import pytest
from shapely.geometry import box

AUTH = "/api/auth"
BOUNDARY = "/api/forests/boundary"


@pytest.fixture(autouse=True)
def _clip_params():
    """Low min-forest floor so the small unit-degree test boxes are not bounced;
    wide adjacency so the (unchanged) gap-dispute path still sees the ~100 m
    band between the deliberately-separated test polygons."""
    keys = {
        "BOUNDARY_MIN_FOREST_HA": "0.01",
        "BOUNDARY_ADJACENCY_M": "200",
        "BOUNDARY_MIN_FRAGMENT_HA": "0.000001",
    }
    saved = {k: os.environ.get(k) for k in keys}
    for k, v in keys.items():
        os.environ[k] = v
    yield
    for k, v in saved.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


def _register_user(client, tag):
    email = f"{tag}_{uuid4().hex[:8]}@example.com"
    client.post(
        AUTH + "/register",
        json={"email": email, "password": "Passw0rd!x", "full_name": "Test"},
    )
    resp = client.post(AUTH + "/login", json={"email": email, "password": "Passw0rd!x"})
    assert resp.status_code == 200, resp.text
    token = resp.json()["access_token"]
    me = client.get(AUTH + "/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200, me.text
    return {"Authorization": f"Bearer {token}"}, me.json()["id"]


def _calc(db, user_id, name, poly, status="validated"):
    """Create a Calculation with a PostGIS boundary geometry for a user."""
    from sqlalchemy import func
    from app.models.calculation import Calculation

    c = Calculation(
        user_id=user_id,
        forest_name=name,
        boundary_geom=func.ST_GeomFromText(poly.wkt, 4326),
    )
    if status:
        c.boundary_status = status
    db.add(c)
    db.commit()
    db.refresh(c)
    return c


def _geojson(poly):
    return poly.__geo_interface__


# ---------------------------------------------------------------------------
# HELPERS — region-parameterised A/B boxes
# ---------------------------------------------------------------------------
#
# Proposed forest A (~1.1 km box).  Neighbour B sits 100 m (0.0009 deg) north
# of A with the same x-range, so the band between them is a clean horizontal
# RIBBON gap.  ``x0`` is a distinct longitude so every test's fixtures live in
# their own neighbourhood (the tests share one test DB and must not see each
# other's forests within the 200 m preview radius).


def _region(x0):
    a = box(x0, 28.0, x0 + 0.01, 28.01)
    b = box(x0, 28.0109, x0 + 0.01, 28.02)
    return a, b




# ---------------------------------------------------------------------------
# PREVIEW clips overlap, no gap analysis
# ---------------------------------------------------------------------------


class TestPreviewClipsOverlap:
    def test_preview_gap_only_neighbour_is_untouched(self, client, db):
        # A sits just south of B with a ~100 m gap, no overlap -> nothing to clip.
        h, uid = _register_user(client, "pvgap")
        a_box, b_box = _region(78.0)
        _calc(db, uid, "Neighbour B", b_box)

        resp = client.post(
            BOUNDARY + "/preview",
            json={"geometry": _geojson(a_box), "method": "upload", "forest_id": None},
            headers=h,
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert "gaps" not in body or not body.get("gaps")
        assert body["status"] in ("no_overlap", "acceptable")
        assert float(body["removed_ha"]) < 0.01, "a gap-only neighbour must not clip anything"
        assert body["resolved_geometry"] is not None

    def test_preview_clips_the_overlap_and_lists_the_forest(self, client, db):
        h, uid = _register_user(client, "pvclip")
        a_box = box(74.0, 28.0, 74.02, 28.01)          # ~2.2 km wide
        overlap_b = box(74.012, 27.995, 74.03, 28.02)   # covers the east ~40 %
        _calc(db, uid, "East B", overlap_b)

        resp = client.post(
            BOUNDARY + "/preview",
            json={"geometry": _geojson(a_box), "method": "upload", "forest_id": None},
            headers=h,
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["status"] == "acceptable", body
        assert float(body["removed_ha"]) > 0
        assert body["resolved_geometry"] is not None
        of = body["overlapping_forests"]
        assert of and float(of[0]["overlap_ha"]) > 0
        assert of[0]["geometry"] is not None, "neighbour outline for the map"

    def test_preview_keeps_all_pieces_when_a_neighbour_splits_the_boundary(self, client, db):
        # B is a vertical band through the middle of A -> clip yields two pieces.
        # x≈70 is a neighbourhood no other test in this file touches.
        h, uid = _register_user(client, "pvsplit")
        a_box = box(70.0, 28.0, 70.03, 28.01)
        mid_b = box(70.013, 27.99, 70.017, 28.02)  # slices A in half
        _calc(db, uid, "Middle B", mid_b)

        resp = client.post(
            BOUNDARY + "/preview",
            json={"geometry": _geojson(a_box), "method": "upload", "forest_id": None},
            headers=h,
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["resolved_geometry"]["type"] == "MultiPolygon", body["resolved_geometry"]["type"]
        assert len(body["resolved_geometry"]["coordinates"]) == 2


# ---------------------------------------------------------------------------
# CONFIRM still 409s on remaining overlap
# ---------------------------------------------------------------------------


class TestConfirmRejectsOverlap:
    def test_confirm_409_when_resolved_yet_overlaps(self, client, db):
        h, uid = _register_user(client, "cfrm")
        # The neighbour fully owns the area the resolved boundary claims, so the
        # resolved boundary is entirely within existing (overlapping) land and
        # confirm must reject it.
        _calc(db, uid, "Overlap B", box(80.005, 28.005, 80.02, 28.02))

        resp = client.post(
            BOUNDARY + "/confirm",
            json={
                "resolved_geometry": _geojson(box(80.006, 28.006, 80.019, 28.019)),
                "original_geometry": _geojson(box(80.005, 28.005, 80.02, 28.02)),
                "forest_name": "Clean Forest",
                "method": "upload",
            },
            headers=h,
        )
        assert resp.status_code == 409, resp.text

    def test_confirm_clips_a_partial_residual_overlap(self, client, db):
        # Clip-only: a posted geometry that still partly overlaps a neighbour is
        # CLIPPED on write (not 409'd) — persist_boundary subtracts the neighbour.
        h, uid = _register_user(client, "cfrmpart")
        west_b = box(80.5, 28.0, 80.51, 28.01)
        _calc(db, uid, "West B", west_b)

        resp = client.post(
            BOUNDARY + "/confirm",
            json={
                # eastern half is clean, western half sits inside West B
                "resolved_geometry": _geojson(box(80.505, 28.003, 80.52, 28.008)),
                "original_geometry": _geojson(box(80.505, 28.003, 80.52, 28.008)),
                "forest_name": "Half Over Forest",
                "method": "upload",
            },
            headers=h,
        )
        assert resp.status_code == 201, resp.text
        from app.models.calculation import Calculation
        from geoalchemy2.shape import to_shape

        db.expire_all()
        calc = db.query(Calculation).filter(Calculation.id == resp.json()["id"]).first()
        saved = to_shape(calc.boundary_geom)
        assert saved.intersection(west_b).area < 1e-9, "saved boundary must not overlap West B"
        assert saved.area > 0

    def test_confirm_ok_when_only_sharing_an_edge(self, client, db):
        # GAP-3: sharing the boundary LINE with a neighbour (0-area) is allowed —
        # that is the desired "adjacent forests share a common boundary" outcome.
        h, uid = _register_user(client, "cfrmedge")
        _calc(db, uid, "East B", box(80.81, 28.0, 80.82, 28.01))

        resp = client.post(
            BOUNDARY + "/confirm",
            json={
                "resolved_geometry": _geojson(box(80.8, 28.0, 80.81, 28.01)),
                "original_geometry": _geojson(box(80.8, 28.0, 80.81, 28.01)),
                "forest_name": "Edge Sharing Forest",
                "method": "upload",
            },
            headers=h,
        )
        assert resp.status_code == 201, resp.text


# ---------------------------------------------------------------------------
# GAP-AWARE DISPUTE
# ---------------------------------------------------------------------------


class TestGapDispute:
    def test_gap_dispute_flags_target_only_and_stores_gap(self, client, db):
        h_filer, uid_filer = _register_user(client, "gapfiler")
        _, uid_target = _register_user(client, "gaptarget")

        a_box, b_box = _region(86.0)
        filer = _calc(db, uid_filer, "Filer CF", a_box)
        target = _calc(db, uid_target, "Target CF", b_box)

        resp = client.post(
            BOUNDARY + "/dispute",
            json={
                "forest_id": str(target.id),
                "reason_np": "There is an unclaimed gap between our forests",
                "dispute_reason_type": "gap",
            },
            headers=h_filer,
        )
        assert resp.status_code == 200, resp.text
        dispute_id = resp.json()["dispute_id"]

        # The target is flagged, the filer's own forest is NOT (pure-gap: the
        # filer claims only the unclaimed band, not the target's land.)
        from app.models.boundary_dispute import BoundaryDispute

        db.rollback()
        d = db.query(BoundaryDispute).filter(BoundaryDispute.id == dispute_id).first()
        assert d is not None
        assert d.dispute_reason_type == "gap"
        assert d.gap_geometry is not None
        assert d.forest_id_2 == filer.id
        # Target disputed, filer untouched.
        from app.models.calculation import Calculation

        db.rollback()
        t = db.query(Calculation).filter(Calculation.id == target.id).first()
        f = db.query(Calculation).filter(Calculation.id == filer.id).first()
        assert t.boundary_status == "disputed"
        assert f.boundary_status == "validated"

    def test_gap_dispute_requires_a_real_gap_neighbour(self, client, db):
        h_filer, uid_filer = _register_user(client, "gapnone")
        _, uid_target = _register_user(client, "gaptargetnone")

        _calc(db, uid_filer, "Filer CF", box(84.5, 29.0, 84.6, 29.1))  # far away
        _, b_box = _region(87.0)
        target = _calc(db, uid_target, "Target CF", b_box)

        resp = client.post(
            BOUNDARY + "/dispute",
            json={
                "forest_id": str(target.id),
                "reason_np": "There is an unclaimed gap between our forests",
                "dispute_reason_type": "gap",
            },
            headers=h_filer,
        )
        assert resp.status_code == 400, resp.text


# ---------------------------------------------------------------------------
# PB-3 — single boundary-write point behind confirm / include / edit
# ---------------------------------------------------------------------------
#
# All three paths must persist through the shared service so geometry_version,
# result_data.geometry and area_hectares stay consistent. Ordinary-save
# behaviour is unchanged (a supplied area is kept). No unit is auto-created
# from a boundary write (FS-2.4/FS-2.8 + C1-C3/Q5).


class TestP3SingleWritePoint:
    def test_edit_put_writes_version_and_geometry_no_unit_created(self, client, db):
        h, uid = _register_user(client, "p3edit")
        from app.models.calculation import Calculation

        calc = Calculation(user_id=uid, forest_name="P3 Edit CF")
        db.add(calc)
        db.commit()
        db.refresh(calc)
        payload = _geojson(box(88.0, 28.0, 88.01, 28.01))

        resp = client.put(
            f"/api/forests/calculations/{calc.id}/boundary",
            headers=h,
            json={"geometry": payload, "area_hectares": 0},
        )
        assert resp.status_code == 200, resp.text
        assert "single_block_created" not in resp.json()
        assert float(resp.json()["area_hectares"]) > 0

        db.expire_all()
        db.refresh(calc)
        assert (calc.geometry_version or 0) == 1, "geometry_version must bump"
        assert calc.result_data["geometry"] is not None
        assert calc.result_data["area_hectares"] > 0

        from app.models.forest_block import ForestBlock

        n_blocks = (
            db.query(ForestBlock).filter(ForestBlock.calculation_id == calc.id).count()
        )
        assert n_blocks == 0, "no unit is auto-created from a boundary write"

    def test_edit_put_keeps_client_supplied_area(self, client, db):
        # Ordinary-save parity: a non-zero supplied area is kept (NOT overwritten
        # by the geodesic recompute) — PB-3 must not change this.
        h, uid = _register_user(client, "p3area")
        from app.models.calculation import Calculation

        calc = Calculation(user_id=uid, forest_name="P3 Area CF")
        db.add(calc)
        db.commit()
        db.refresh(calc)
        resp = client.put(
            f"/api/forests/calculations/{calc.id}/boundary",
            headers=h,
            json={
                "geometry": _geojson(box(81.1, 28.0, 81.11, 28.01)),
                "area_hectares": 2500,
            },
        )
        assert resp.status_code == 200, resp.text
        assert float(resp.json()["area_hectares"]) == 2500.0
        db.expire_all()
        db.refresh(calc)
        assert calc.result_data["area_hectares"] == 2500

    def test_edit_put_clips_a_vertex_dragged_into_a_neighbour(self, client, db):
        # Point C: an edit that pushes the boundary into a neighbour is trimmed
        # back on write, the same way an import is.
        h, uid = _register_user(client, "p3clipedit")
        from app.models.calculation import Calculation

        _calc(db, uid, "East B", box(81.412, 27.99, 81.43, 28.02))
        calc = Calculation(user_id=uid, forest_name="Clip Edit CF")
        db.add(calc)
        db.commit()
        db.refresh(calc)

        # a_box overlaps East B on its eastern third
        resp = client.put(
            f"/api/forests/calculations/{calc.id}/boundary",
            headers=h,
            json={"geometry": _geojson(box(81.4, 28.0, 81.42, 28.01)), "confirmed": True},
        )
        assert resp.status_code == 200, resp.text

        db.expire_all()
        db.refresh(calc)
        from geoalchemy2.shape import to_shape

        saved = to_shape(calc.boundary_geom)
        east_b = box(81.412, 27.99, 81.43, 28.02)
        assert saved.intersection(east_b).area < 1e-9, "stored boundary must not overlap the neighbour"
        assert saved.area > 0

    def test_confirm_syncs_result_data_and_version(self, client, db):
        # confirm previously wrote only boundary_geom via raw SQL; PB-3 unifies it
        # so geometry_version + result_data.geometry stay consistent too.
        h, uid = _register_user(client, "p3conf")
        from app.models.calculation import Calculation

        resp = client.post(
            BOUNDARY + "/confirm",
            headers=h,
            json={
                "resolved_geometry": _geojson(box(81.7, 28.0, 81.71, 28.01)),
                "original_geometry": _geojson(box(81.7, 28.0, 81.71, 28.01)),
                "forest_name": "P3 Confirm CF",
                "method": "upload",
            },
        )
        assert resp.status_code == 201, resp.text
        calc_id = resp.json()["id"]

        db.expire_all()
        calc = db.query(Calculation).filter(Calculation.id == calc_id).first()
        assert calc is not None
        assert (calc.geometry_version or 0) == 1, "confirm must bump geometry_version"
        assert calc.result_data["geometry"] is not None, "confirm must sync result_data"

    def test_confirm_edit_accept_keeps_same_calculation(self, client, db):
        # PF-3 edit/reshape path: confirm WITH calculation_id must persist onto
        # the EXISTING calculation (same uuid), not create a duplicate forest.
        h, uid = _register_user(client, "p3ce")
        from app.models.calculation import Calculation

        calc = Calculation(user_id=uid, forest_name="Confirm Edit CF")
        db.add(calc)
        db.commit()
        db.refresh(calc)
        orig_id = calc.id

        resp = client.post(
            BOUNDARY + "/confirm",
            headers=h,
            json={
                "resolved_geometry": _geojson(box(82.0, 28.0, 82.01, 28.01)),
                "original_geometry": _geojson(box(82.0, 28.0, 82.01, 28.01)),
                "forest_name": "Confirm Edit CF",
                "method": "digitize",
                "calculation_id": str(orig_id),
            },
        )
        assert resp.status_code == 201, resp.text
        returned_id = resp.json()["id"]
        assert returned_id == str(orig_id), (
            "confirm with calculation_id must keep the same calculation, "
            f"got {returned_id} != {orig_id}"
        )

        db.expire_all()
        calc = db.query(Calculation).filter(Calculation.id == orig_id).first()
        assert calc is not None
        assert (calc.geometry_version or 0) == 1
        assert calc.result_data["geometry"] is not None
        # forest name preserved (not reset) on the edit path
        assert calc.forest_name == "Confirm Edit CF"

    def test_edit_put_writes_immediately_for_a_gap_only_neighbour(self, client, db):
        # Clip-only rework: a neighbour that only leaves a GAP (no overlap) is not
        # a review trigger — the boundary is written as-is and the user closes the
        # gap afterwards with the vertex editor.
        h, uid = _register_user(client, "p3prov")
        a_box, b_box = _region(82.3)
        _calc(db, uid, "Neighbour B", b_box)
        from app.models.calculation import Calculation

        calc = Calculation(user_id=uid, forest_name="Editable CF")
        db.add(calc)
        db.commit()
        db.refresh(calc)
        resp = client.put(
            f"/api/forests/calculations/{calc.id}/boundary",
            headers=h,
            json={"geometry": _geojson(a_box), "area_hectares": 0},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body.get("needs_overlap_review") is not True, body
        db.expire_all()
        db.refresh(calc)
        assert (calc.geometry_version or 0) == 1
        assert calc.boundary_geom is not None

    def test_edit_put_confirmed_writes_when_gap(self, client, db):
        h, uid = _register_user(client, "p3prov2")
        a_box, b_box = _region(82.6)
        _calc(db, uid, "Neighbour B", b_box)
        from app.models.calculation import Calculation

        calc = Calculation(user_id=uid, forest_name="Editable CF2")
        db.add(calc)
        db.commit()
        db.refresh(calc)
        resp = client.put(
            f"/api/forests/calculations/{calc.id}/boundary",
            headers=h,
            json={"geometry": _geojson(a_box), "area_hectares": 0, "confirmed": True},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json().get("needs_overlap_review") is not True
        assert "single_block_created" not in resp.json()
        db.expire_all()
        db.refresh(calc)
        assert (calc.geometry_version or 0) == 1
        assert calc.boundary_geom is not None
