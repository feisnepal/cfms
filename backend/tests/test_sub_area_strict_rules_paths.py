"""The two absolute sub-area rules on every path that writes a sub-area.

    1. a sub-area lies inside the forest;
    2. no two sub-areas overlap (first created keeps the ground; an edited
       sub-area gives way to the others).

`test_sub_area_strict_rules.py` covers `POST .../sub-areas` (which paste and
drawing use). This file covers the other writers, each of which used to have its
own, weaker version of the rules:

  - the edit funnel (`_write_geometry`: vertex edit / move / edit-geometry) stored
    whatever it was handed;
  - restore-on-undo re-inserted the snapshot even if the ground had been taken;
  - import -> convert-to-builtin used `clip_to_region` (returns the geometry
    UNCHANGED on error, keeps GeometryCollections) and swallowed a failed
    overlap correction;
  - polygon-from-points did no forest clipping at all;
  - the wizard clipped to the boundary but let its sub-areas overlap each other;
  - demoting a protection unit re-emitted a sub-area without an overlap check.
"""

from __future__ import annotations

import io
import json
import uuid

import pytest
from geoalchemy2.shape import from_shape
from shapely.geometry import Polygon, box, mapping, shape
from shapely.ops import unary_union

from app.models.calculation import Calculation
from app.models.forest_block import ForestBlock
from app.models.user import User
from app.services.map_creation_service import process_map_creation_data
from app.services.protection_unit_service import demote_unit_to_subarea

FOREST = box(84.0, 27.0, 84.01, 27.01)
TOL = 1e-9


# ------------------------------------------------------------------ helpers
def _owner(client, db):
    email = f"paths-{uuid.uuid4().hex[:8]}@example.com"
    client.post(
        "/api/auth/register",
        json={"email": email, "password": "TestPass123!", "full_name": "Paths"},
    )
    r = client.post(
        "/api/auth/login", json={"email": email, "password": "TestPass123!"}
    )
    return (
        {"Authorization": f"Bearer {r.json()['access_token']}"},
        db.query(User).filter(User.email == email).first(),
    )


def _calc(db, user, boundary=FOREST):
    calc = Calculation(
        id=uuid.uuid4(), user_id=user.id, uploaded_filename="paths.csv", is_draft=False
    )
    db.add(calc)
    db.flush()
    if boundary is not None:
        calc.boundary_geom = from_shape(boundary, srid=4326)
    db.commit()
    return calc


def _create(client, headers, calc, name, geom, category="protected"):
    r = client.post(
        f"/api/forests/calculations/{calc.id}/sub-areas",
        headers=headers,
        json={
            "name": name,
            "category": category,
            "is_excluded": False,
            "geometry": mapping(geom),
        },
    )
    assert r.status_code == 200, r.text
    return r.json()


def _list(client, headers, calc):
    body = client.get(
        f"/api/forests/calculations/{calc.id}/sub-areas", headers=headers
    ).json()
    return body.get("sub_areas", body) if isinstance(body, dict) else body


def _geoms(client, headers, calc):
    return {sa["name"]: shape(sa["geometry"]) for sa in _list(client, headers, calc)}


def _inside(g, extent):
    return g.difference(extent.buffer(TOL)).area < 1e-12


def _no_overlaps(geoms):
    gs = list(geoms)
    for i in range(len(gs)):
        for j in range(i + 1, len(gs)):
            assert (
                gs[i].intersection(gs[j]).area < 1e-12
            ), f"sub-areas {i} and {j} overlap"


def _edit(client, headers, calc, feature_id, geom):
    return client.post(
        f"/api/v1/calculations/{calc.id}/geometry/edit-geometry",
        headers=headers,
        json={
            "layer_type": "sub_areas",
            "feature_id": feature_id,
            "geometry": mapping(geom),
        },
    )


# ============================================================ edit funnel
class TestEditingASubArea:
    """`edit-geometry` pre-checks topology (409 TOPOLOGY_REJECTED) before it writes; the
    funnel `_write_geometry` is what EVERY edit path ends in, including the ones that do
    not pre-check. So: the API tests cover what the pre-check lets through, and the
    funnel is tested directly for the rules it must enforce on its own."""

    @pytest.fixture()
    def two(self, client, db):
        headers, user = _owner(client, db)
        calc = _calc(db, user)
        a = _create(client, headers, calc, "A", box(84.001, 27.001, 84.003, 27.003))
        b = _create(
            client,
            headers,
            calc,
            "B",
            box(84.005, 27.001, 84.007, 27.003),
            category="plantation",
        )
        return client, headers, calc, a, b

    # -- through the API -------------------------------------------------
    def test_an_edit_inside_the_forest_is_stored_as_drawn(self, two):
        client, headers, calc, a, _ = two
        moved = box(84.0015, 27.0015, 84.0035, 27.0035)
        r = _edit(client, headers, calc, a["id"], moved)
        assert r.status_code == 200, r.text
        assert _geoms(client, headers, calc)["A"].equals(moved)

    def test_dragging_a_vertex_past_the_boundary_clips_it_to_the_boundary(self, two):
        client, headers, calc, a, _ = two
        dragged = box(
            84.008, 27.008, 84.012, 27.012
        )  # runs past the forest's NE corner
        r = _edit(client, headers, calc, a["id"], dragged)
        assert r.status_code == 200, r.text
        g = _geoms(client, headers, calc)["A"]
        assert _inside(g, FOREST)
        assert g.area == pytest.approx(dragged.intersection(FOREST).area, rel=1e-6)

    @pytest.mark.parametrize(
        "target",
        [
            box(84.02, 27.02, 84.03, 27.03),  # wholly outside the forest
            box(84.0055, 27.0015, 84.0065, 27.0025),  # wholly inside another sub-area
            box(84.001, 27.001, 84.006, 27.003),  # reaches into another sub-area
        ],
    )
    def test_an_edit_that_would_break_a_rule_never_changes_the_stored_sub_area(
        self, two, target
    ):
        client, headers, calc, a, _ = two
        before = _geoms(client, headers, calc)
        r = _edit(client, headers, calc, a["id"], target)
        if r.status_code == 200:  # accepted only if it was trimmed to comply
            after = _geoms(client, headers, calc)
            assert _inside(after["A"], FOREST)
            _no_overlaps(after.values())
        else:
            assert r.status_code in (400, 409), r.text
            assert _geoms(client, headers, calc)["A"].equals(before["A"])

    # -- the funnel itself ------------------------------------------------
    def _write(self, db, calc, feature_id, geom):
        from app.api.editing import _write_geometry

        _write_geometry(db, calc, "sub_areas", feature_id, mapping(geom))
        return {
            sa["name"]: shape(sa["geometry"]) for sa in calc.result_data["sub_areas"]
        }

    def test_the_funnel_clips_an_edit_that_runs_past_the_forest(self, two, db):
        client, headers, calc, a, _ = two
        db.refresh(calc)
        dragged = box(84.008, 27.008, 84.012, 27.012)
        stored = self._write(db, calc, a["id"], dragged)
        assert _inside(stored["A"], FOREST)
        assert stored["A"].area == pytest.approx(
            dragged.intersection(FOREST).area, rel=1e-6
        )

    def test_the_funnel_makes_an_edited_sub_area_give_way_to_its_neighbour(
        self, two, db
    ):
        client, headers, calc, a, b = two
        db.refresh(calc)
        over_b = box(84.001, 27.001, 84.006, 27.003)
        stored = self._write(db, calc, a["id"], over_b)
        assert stored["A"].intersection(stored["B"]).area < 1e-12
        assert stored["A"].area == pytest.approx(
            over_b.difference(box(84.005, 27.001, 84.007, 27.003)).area, rel=1e-6
        )
        assert stored["B"].equals(
            box(84.005, 27.001, 84.007, 27.003)
        )  # the neighbour is untouched

    def test_the_funnel_refuses_an_edit_with_nothing_left_inside_the_forest(
        self, two, db
    ):
        from fastapi import HTTPException

        client, headers, calc, a, _ = two
        db.refresh(calc)
        with pytest.raises(HTTPException) as exc:
            self._write(db, calc, a["id"], box(84.02, 27.02, 84.03, 27.03))
        assert exc.value.status_code == 400
        assert "outside the forest boundary" in exc.value.detail

    def test_the_funnel_refuses_an_edit_wholly_onto_another_sub_area(self, two, db):
        from fastapi import HTTPException

        client, headers, calc, a, _ = two
        db.refresh(calc)
        with pytest.raises(HTTPException) as exc:
            self._write(db, calc, a["id"], box(84.0055, 27.0015, 84.0065, 27.0025))
        assert exc.value.status_code == 400
        assert "entirely within existing sub-areas" in exc.value.detail

    def test_the_funnel_does_not_collide_a_sub_area_with_its_own_old_shape(
        self, two, db
    ):
        client, headers, calc, a, _ = two
        db.refresh(calc)
        grown = box(84.0005, 27.0005, 84.0035, 27.0035)
        stored = self._write(db, calc, a["id"], grown)
        assert stored["A"].area == pytest.approx(grown.area, rel=1e-6)

    def test_the_funnel_keeps_a_polygon_a_polygon(self, two, db):
        """An edit whose raw intersection with the forest is polygon + stray edge."""
        client, headers, calc, a, _ = two
        db.refresh(calc)
        # forest is a plain box here, so build the trap from a boundary-touching notch instead:
        # a MultiPolygon edit with one piece inside and one only touching the east edge.
        multi = unary_union(
            [box(84.001, 27.001, 84.002, 27.002), box(84.010, 27.004, 84.012, 27.006)]
        )
        stored = self._write(db, calc, a["id"], multi)
        assert stored["A"].geom_type in ("Polygon", "MultiPolygon")
        assert _inside(stored["A"], FOREST)


# ============================================================ restore on undo
class TestRestoringADeletedSubArea:
    def _delete_then_take_the_ground(self, client, headers, calc, taker):
        a = _create(client, headers, calc, "A", box(84.001, 27.001, 84.004, 27.004))
        snapshot = next(
            sa for sa in _list(client, headers, calc) if sa["id"] == a["id"]
        )
        d = client.delete(
            f"/api/forests/calculations/{calc.id}/sub-areas/{a['id']}", headers=headers
        )
        assert d.status_code in (200, 204), d.text
        _create(client, headers, calc, "Taker", taker, category="plantation")
        return a, snapshot

    def _restore(self, client, headers, calc, a, snapshot):
        return client.post(
            f"/api/v1/calculations/{calc.id}/geometry/restore-feature",
            headers=headers,
            json={
                "layer_type": "sub_areas",
                "feature_id": a["id"],
                "snapshot": snapshot,
            },
        )

    def test_undo_gives_way_to_a_sub_area_drawn_over_the_ground_meanwhile(
        self, client, db
    ):
        headers, user = _owner(client, db)
        calc = _calc(db, user)
        taker = box(84.003, 27.001, 84.006, 27.004)  # takes A's eastern strip
        a, snap = self._delete_then_take_the_ground(client, headers, calc, taker)
        r = self._restore(client, headers, calc, a, snap)
        assert r.status_code == 200, r.text
        geoms = _geoms(client, headers, calc)
        assert set(geoms) == {"A", "Taker"}
        assert geoms["A"].intersection(geoms["Taker"]).area < 1e-12
        assert geoms["A"].area == pytest.approx(
            box(84.001, 27.001, 84.004, 27.004).difference(taker).area, rel=1e-6
        )

    def test_undo_is_refused_when_the_ground_is_wholly_taken(self, client, db):
        headers, user = _owner(client, db)
        calc = _calc(db, user)
        a, snap = self._delete_then_take_the_ground(
            client, headers, calc, box(84.0005, 27.0005, 84.0045, 27.0045)
        )
        r = self._restore(client, headers, calc, a, snap)
        assert r.status_code == 409
        assert "can no longer be restored" in r.text
        assert {sa["name"] for sa in _list(client, headers, calc)} == {"Taker"}

    def test_an_untouched_undo_restores_exactly(self, client, db):
        headers, user = _owner(client, db)
        calc = _calc(db, user)
        a, snap = self._delete_then_take_the_ground(
            client, headers, calc, box(84.008, 27.008, 84.009, 27.009)
        )
        assert self._restore(client, headers, calc, a, snap).status_code == 200
        assert _geoms(client, headers, calc)["A"].equals(
            box(84.001, 27.001, 84.004, 27.004)
        )


# ============================================================ import -> convert
def _import_geojson(client, headers, calc, features):
    fc = {"type": "FeatureCollection", "features": features}
    resp = client.post(
        f"/api/workspace/{calc.id}/import-layer",
        headers=headers,
        files={
            "file": (
                "subareas.geojson",
                io.BytesIO(json.dumps(fc).encode()),
                "application/geo+json",
            )
        },
        data={"purpose": "sub_areas"},
    )
    assert resp.status_code == 200, resp.text
    return client.post(
        f"/api/workspace/{calc.id}/import-layers/{resp.json()['id']}/convert-to-builtin",
        headers=headers,
        json={"target_type": "sub_areas"},
    )


def _feat(name, geom, **props):
    return {
        "type": "Feature",
        "properties": {"name": name, "category": "protected", **props},
        "geometry": mapping(geom),
    }


class TestImportingSubAreas:
    def test_an_import_is_clipped_to_the_forest_and_never_overlaps(self, client, db):
        headers, user = _owner(client, db)
        calc = _calc(db, user)
        first = box(84.001, 27.001, 84.004, 27.004)
        resp = _import_geojson(
            client,
            headers,
            calc,
            [
                _feat("inside", first),
                _feat(
                    "straddles", box(84.008, 27.008, 84.013, 27.013)
                ),  # past the NE corner
                _feat(
                    "overlaps-first", box(84.003, 27.001, 84.006, 27.004)
                ),  # shares a strip with "inside"
                _feat("wholly-outside", box(84.05, 27.05, 84.06, 27.06)),
            ],
        )
        assert resp.status_code == 200, resp.text
        summary = resp.json()["import_summary"]
        assert summary["imported"] == 3
        assert summary["removed"] == 1
        assert summary["clipped"] >= 1 and summary["overlapped"] >= 1

        db.expire_all()
        stored = {
            sa["name"]: shape(sa["geometry"])
            for sa in db.get(Calculation, calc.id).result_data["sub_areas"]
        }
        assert set(stored) == {"inside", "straddles", "overlaps-first"}
        for name, g in stored.items():
            assert g.geom_type in ("Polygon", "MultiPolygon"), name
            assert _inside(g, FOREST), name
        _no_overlaps(stored.values())

    def test_a_feature_touching_the_forest_only_along_its_edge_is_removed_not_stored_as_a_line(
        self, client, db
    ):
        headers, user = _owner(client, db)
        calc = _calc(db, user)
        edge_only = box(
            84.010, 27.002, 84.012, 27.004
        )  # shares the forest's east edge from outside
        assert edge_only.intersection(FOREST).geom_type == "LineString"
        resp = _import_geojson(
            client,
            headers,
            calc,
            [
                _feat("inside", box(84.001, 27.001, 84.002, 27.002)),
                _feat("edge-only", edge_only),
            ],
        )
        assert resp.status_code == 200, resp.text
        db.expire_all()
        names = [
            sa["name"] for sa in db.get(Calculation, calc.id).result_data["sub_areas"]
        ]
        assert names == ["inside"]

    def test_a_feature_whose_clip_is_a_polygon_plus_a_stray_edge_is_stored_as_a_polygon(
        self, client, db
    ):
        """`clip_to_region` returned the raw GeometryCollection; only the polygon may be stored."""
        u_shape = Polygon(
            [
                (84.000, 27.000),
                (84.006, 27.000),
                (84.006, 27.004),
                (84.004, 27.004),
                (84.004, 27.001),
                (84.002, 27.001),
                (84.002, 27.004),
                (84.000, 27.004),
            ]
        )
        headers, user = _owner(client, db)
        calc = _calc(db, user, boundary=u_shape)
        trap = box(
            84.001, 27.002, 84.004, 27.003
        )  # overlaps lobe A, merely touches lobe B's edge
        assert trap.intersection(u_shape).geom_type == "GeometryCollection"
        resp = _import_geojson(client, headers, calc, [_feat("trap", trap)])
        assert resp.status_code == 200, resp.text
        db.expire_all()
        g = shape(db.get(Calculation, calc.id).result_data["sub_areas"][0]["geometry"])
        assert g.geom_type in ("Polygon", "MultiPolygon")
        assert g.difference(u_shape.buffer(TOL)).area < 1e-12

    def test_everything_outside_is_reported_not_stored(self, client, db):
        headers, user = _owner(client, db)
        calc = _calc(db, user)
        resp = _import_geojson(
            client, headers, calc, [_feat("far", box(84.05, 27.05, 84.06, 27.06))]
        )
        assert resp.status_code == 400
        assert "outside the forest boundary" in resp.text
        db.expire_all()
        assert (db.get(Calculation, calc.id).result_data or {}).get(
            "sub_areas", []
        ) == []

    def test_an_import_gives_way_to_sub_areas_already_on_record(self, client, db):
        headers, user = _owner(client, db)
        calc = _calc(db, user)
        _create(client, headers, calc, "existing", box(84.001, 27.001, 84.004, 27.004))
        resp = _import_geojson(
            client, headers, calc, [_feat("new", box(84.003, 27.001, 84.006, 27.004))]
        )
        assert resp.status_code == 200, resp.text
        geoms = _geoms(client, headers, calc)
        assert geoms["existing"].intersection(geoms["new"]).area < 1e-12
        assert geoms["new"].area == pytest.approx(
            box(84.004, 27.001, 84.006, 27.004).area, rel=1e-6
        )


# ============================================================ polygon from points
def _from_points(client, headers, calc, ring):
    return client.post(
        f"/api/workspace/{calc.id}/polygon-from-points",
        headers=headers,
        json={
            "points": [list(p) for p in ring],
            "target_type": "sub_areas",
            "name": "from-points",
        },
    )


class TestPolygonFromPoints:
    def test_a_polygon_past_the_boundary_is_clipped_to_it(self, client, db):
        headers, user = _owner(client, db)
        calc = _calc(db, user)
        ring = [(84.008, 27.008), (84.013, 27.008), (84.013, 27.013), (84.008, 27.013)]
        assert _from_points(client, headers, calc, ring).status_code == 200
        g = _geoms(client, headers, calc)["from-points"]
        assert _inside(g, FOREST)
        assert g.area == pytest.approx(
            Polygon(ring).intersection(FOREST).area, rel=1e-6
        )

    def test_a_polygon_wholly_outside_is_refused(self, client, db):
        headers, user = _owner(client, db)
        calc = _calc(db, user)
        r = _from_points(
            client,
            headers,
            calc,
            [(84.05, 27.05), (84.06, 27.05), (84.06, 27.06), (84.05, 27.06)],
        )
        assert r.status_code == 400
        assert _list(client, headers, calc) == []

    def test_a_polygon_over_an_existing_sub_area_gives_way(self, client, db):
        headers, user = _owner(client, db)
        calc = _calc(db, user)
        _create(client, headers, calc, "existing", box(84.001, 27.001, 84.004, 27.004))
        ring = [(84.003, 27.001), (84.006, 27.001), (84.006, 27.004), (84.003, 27.004)]
        assert _from_points(client, headers, calc, ring).status_code == 200
        geoms = _geoms(client, headers, calc)
        assert geoms["existing"].intersection(geoms["from-points"]).area < 1e-12


# ============================================================ wizard (forest creation)
class TestWizardCreation:
    OUTER = mapping(box(84.0, 27.0, 84.002, 27.002))

    def _sa(self, i, geom, category="protected"):
        return {
            "id": f"sa-{i}",
            "name": f"S{i}",
            "category": category,
            "geometry": mapping(geom),
        }

    def _run(self, sub_areas):
        _wkt, meta = process_map_creation_data(self.OUTER, [], sub_areas=sub_areas)
        return meta.get("sub_areas", [])

    def test_sub_areas_are_clipped_to_the_boundary(self):
        out = self._run([self._sa(1, box(84.001, 27.001, 84.004, 27.004))])
        assert len(out) == 1
        assert _inside(shape(out[0]["geometry"]), shape(self.OUTER))

    def test_sub_areas_never_overlap_each_other(self):
        out = self._run(
            [
                self._sa(1, box(84.0002, 27.0002, 84.0012, 27.0012)),
                self._sa(
                    2, box(84.0008, 27.0008, 84.0018, 27.0018)
                ),  # overlaps the first
                self._sa(
                    3, box(84.0006, 27.0006, 84.0010, 27.0010)
                ),  # wholly inside the first
            ]
        )
        assert [s["name"] for s in out] == ["S1", "S2"]  # S3 has nothing left
        _no_overlaps(shape(s["geometry"]) for s in out)

    def test_edge_or_corner_contact_is_skipped_not_kept_as_a_line_or_point(self):
        out = self._run(
            [
                self._sa(
                    1, box(84.002, 27.0005, 84.003, 27.0015)
                ),  # touches the east edge only
                self._sa(
                    2, box(84.002, 27.002, 84.003, 27.003)
                ),  # touches the NE corner only
                self._sa(3, box(84.0005, 27.0005, 84.0015, 27.0015)),
            ]
        )
        assert [s["name"] for s in out] == ["S3"]
        assert all(
            shape(s["geometry"]).geom_type in ("Polygon", "MultiPolygon") for s in out
        )


# ============================================================ demoting a protection unit
class TestDemotingAProtectionUnit:
    def _unit(self, db, calc, geom):
        unit = ForestBlock(
            calculation_id=calc.id,
            name="P-1",
            block_name="P-1",
            index=1,
            geometry=from_shape(geom, srid=4326),
            area_hectares=1,
            area_sqm=10000,
            is_compartment=False,
            division_level=1,
            working_circle="protection",
        )
        db.add(unit)
        db.commit()
        return unit

    def test_demoting_keeps_the_sub_area_clear_of_ones_drawn_over_the_ground_meanwhile(
        self, client, db
    ):
        headers, user = _owner(client, db)
        calc = _calc(db, user)
        unit_geom = box(84.001, 27.001, 84.004, 27.004)
        unit = self._unit(db, calc, unit_geom)
        taker = box(84.003, 27.001, 84.006, 27.004)
        _create(client, headers, calc, "Taker", taker, category="plantation")
        db.expire_all()
        calc = db.get(Calculation, calc.id)

        demote_unit_to_subarea(db, calc, str(unit.id))
        db.commit()
        db.expire_all()

        subs = {
            sa["name"]: shape(sa["geometry"])
            for sa in db.get(Calculation, calc.id).result_data["sub_areas"]
        }
        assert "P-1" in subs and "Taker" in subs
        assert subs["P-1"].intersection(subs["Taker"]).area < 1e-12
        assert subs["P-1"].area == pytest.approx(
            unit_geom.difference(taker).area, rel=1e-6
        )

    def test_demoting_is_refused_when_the_ground_is_wholly_covered(self, client, db):
        headers, user = _owner(client, db)
        calc = _calc(db, user)
        unit = self._unit(db, calc, box(84.001, 27.001, 84.004, 27.004))
        _create(
            client,
            headers,
            calc,
            "Cover",
            box(84.0005, 27.0005, 84.0045, 27.0045),
            category="plantation",
        )
        db.expire_all()
        calc = db.get(Calculation, calc.id)
        with pytest.raises(ValueError, match=r"^SUBAREA_PLACEMENT:"):
            demote_unit_to_subarea(db, calc, str(unit.id))
