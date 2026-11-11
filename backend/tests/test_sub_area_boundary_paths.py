"""Sub-areas must lie inside the forest -- whichever route the boundary took.

`persist_boundary` clips sub-areas itself, but about a dozen other places write
`calculations.boundary_geom` directly (raw SQL or an ORM assignment). Until now only
two of them re-clipped, so a boundary that appeared or shrank through any other
route left sub-areas outside the forest.

Two situations, for every writer:
  - NO boundary yet: sub-areas were stored as *pending*; the first boundary clips them;
  - a boundary REPLACED by a smaller one: anything outside it is clipped or dropped.
In both, the change is REPORTED (a recorded sub-area must never shrink or vanish silently).

Every test gets its own patch of ground (`w`): the boundary-writing routes clip against
neighbouring forests, and these tests commit, so sharing coordinates would make one test's
forest a "neighbour" of the next.
"""

from __future__ import annotations

import itertools
import json
import uuid

import pytest
from geoalchemy2.shape import from_shape
from shapely.affinity import translate
from shapely.geometry import MultiPolygon, box, mapping, shape
from sqlalchemy import text

from app.models.boundary_dispute import BoundaryDispute
from app.models.calculation import Calculation
from app.models.user import User, UserRole
from app.services.boundary_write_service import persist_boundary

TOL = 1e-9
_slot = itertools.count()


class World:
    """One test's ground. BIG is the old forest, SMALL its western half (the new boundary)."""

    def __init__(self, n: int):
        dx, dy = 0.05 * (n % 60), 0.05 * (
            n // 60
        )  # 82.0-85.0 E, 27.0+ N: inside Nepal, never shared

        def at(g):
            return translate(g, xoff=82.0 + dx, yoff=27.0 + dy)

        self.at = at
        self.BIG = at(box(0.000, 0.000, 0.020, 0.020))
        self.SMALL = at(box(0.000, 0.000, 0.010, 0.020))
        # wholly inside SMALL / straddling its east edge / wholly outside it
        self.WEST = at(box(0.001, 0.002, 0.006, 0.008))
        self.STRADDLE = at(box(0.007, 0.002, 0.013, 0.008))
        self.EAST = at(box(0.012, 0.002, 0.018, 0.008))


@pytest.fixture()
def w():
    return World(next(_slot))


# ------------------------------------------------------------------ helpers
def _owner(client, db, role=None):
    email = f"bnd-{uuid.uuid4().hex[:8]}@example.com"
    client.post(
        "/api/auth/register",
        json={"email": email, "password": "TestPass123!", "full_name": "Boundary"},
    )
    r = client.post(
        "/api/auth/login", json={"email": email, "password": "TestPass123!"}
    )
    user = db.query(User).filter(User.email == email).first()
    if role is not None:
        user.role = role
        db.commit()
    return {"Authorization": f"Bearer {r.json()['access_token']}"}, user


def _calc(db, user, boundary=None, draft=False):
    calc = Calculation(
        id=uuid.uuid4(),
        user_id=user.id,
        forest_name="Bnd Forest",
        uploaded_filename="bnd.csv",
        is_draft=draft,
    )
    db.add(calc)
    db.flush()
    if boundary is not None:
        calc.boundary_geom = from_shape(boundary, srid=4326)
    db.commit()
    return calc


def _add_sub_areas(client, headers, calc, w):
    for name, geom in (("west", w.WEST), ("straddle", w.STRADDLE), ("east", w.EAST)):
        r = client.post(
            f"/api/forests/calculations/{calc.id}/sub-areas",
            headers=headers,
            json={
                "name": name,
                "category": "protected",
                "is_excluded": False,
                "geometry": mapping(geom),
            },
        )
        assert r.status_code == 200, r.text


def _stored(db, calc):
    db.expire_all()
    return {
        sa["name"]: sa
        for sa in (db.get(Calculation, calc.id).result_data or {}).get("sub_areas", [])
    }


def _inside(g, extent):
    return g.difference(extent.buffer(TOL)).area < 1e-12


def _assert_clipped_to_small(db, calc, w):
    stored = _stored(db, calc)
    assert set(stored) == {"west", "straddle"}, sorted(
        stored
    )  # "east" was wholly outside: dropped
    for name, sa in stored.items():
        assert _inside(shape(sa["geometry"]), w.SMALL), name
        assert "pending_boundary_clip" not in sa, f"{name} is still marked pending"
    assert shape(stored["west"]["geometry"]).equals(w.WEST)  # untouched
    assert shape(stored["straddle"]["geometry"]).area == pytest.approx(
        w.STRADDLE.intersection(w.SMALL).area, rel=1e-6
    )  # trimmed to the edge


def _assert_reported(body):
    assert body["sub_areas_clipped"] == ["straddle"], body
    assert body["sub_areas_dropped"] == ["east"], body


# ---------------------------------------------------------------- the writers
def _put_boundary(client, headers, calc, w):
    r = client.put(
        f"/api/forests/calculations/{calc.id}/boundary",
        headers=headers,
        json={"geometry": mapping(w.SMALL), "confirmed": True},
    )
    assert r.status_code == 200, r.text
    return r.json()


def _patch_geometry(client, headers, calc, w):
    r = client.patch(
        f"/api/forests/calculations/{calc.id}/geometry",
        headers=headers,
        json={"geometry": mapping(w.SMALL), "reanalyze": False},
    )
    assert r.status_code == 200, r.text
    return r.json()


def _merge_boundary(client, headers, calc, w):
    r = client.post(
        f"/api/forests/calculations/{calc.id}/merge-forest-boundary",
        headers=headers,
        json={"geometries": [mapping(w.SMALL)]},
    )
    assert r.status_code == 200, r.text
    return r.json()


def _polygon_from_points(client, headers, calc, w):
    ring = list(w.SMALL.exterior.coords)[:-1]
    r = client.post(
        f"/api/workspace/{calc.id}/polygon-from-points",
        headers=headers,
        json={
            "points": [list(p) for p in ring],
            "target_type": "boundary",
            "name": "b",
        },
    )
    assert r.status_code == 200, r.text
    return None  # this route does not report; the stored result is asserted


def _restore_boundary(client, headers, calc, w):
    r = client.post(
        f"/api/v1/calculations/{calc.id}/geometry/restore-feature",
        headers=headers,
        json={
            "layer_type": "boundary",
            "feature_id": "boundary",
            "snapshot": {"geometry": mapping(w.SMALL)},
        },
    )
    assert r.status_code == 200, r.text
    return r.json()


REPORTING = [_put_boundary, _patch_geometry, _merge_boundary, _restore_boundary]
ALL = REPORTING + [_polygon_from_points]


def _id(fn):
    return fn.__name__.lstrip("_")


class TestTheFirstBoundaryClipsPendingSubAreas:
    """No boundary yet: the sub-areas were stored pending; whichever route brings the boundary clips them."""

    @pytest.mark.parametrize("write", ALL, ids=_id)
    def test_via(self, client, db, w, write):
        headers, user = _owner(client, db)
        calc = _calc(db, user, boundary=None)
        _add_sub_areas(client, headers, calc, w)
        assert all(sa["pending_boundary_clip"] for sa in _stored(db, calc).values())

        body = write(client, headers, calc, w)

        _assert_clipped_to_small(db, calc, w)
        if write in REPORTING:
            _assert_reported(body)

    def test_a_draft_becoming_a_forest_clips_its_pending_sub_areas(self, client, db, w):
        headers, user = _owner(client, db)
        calc = _calc(db, user, boundary=None, draft=True)
        _add_sub_areas(client, headers, calc, w)
        r = client.post(
            f"/api/forests/drafts/{calc.id}/convert",
            headers=headers,
            json={"outer_boundary": mapping(w.SMALL)},
        )
        assert r.status_code == 200, r.text
        _assert_clipped_to_small(db, calc, w)


class TestReplacingABoundaryWithASmallerOne:
    """A boundary already exists (sub-areas were clipped to the BIG one): a smaller one clips them again."""

    @pytest.mark.parametrize("write", ALL, ids=_id)
    def test_via(self, client, db, w, write):
        headers, user = _owner(client, db)
        calc = _calc(db, user, boundary=w.BIG)
        _add_sub_areas(client, headers, calc, w)
        assert set(_stored(db, calc)) == {"west", "straddle", "east"}
        assert not any(
            "pending_boundary_clip" in sa for sa in _stored(db, calc).values()
        )

        body = write(client, headers, calc, w)

        _assert_clipped_to_small(db, calc, w)
        if write in REPORTING:
            _assert_reported(body)


class TestOtherBoundaryWriters:
    @pytest.mark.xfail(
        strict=True,
        reason="edit-boundary (legacy interactive editor, no frontend caller) 400s on any existing boundary "
        "before reaching the re-clip: SELECT ST_AsEWKB(:geom) cannot adapt a WKBElement. Broken on "
        "HEAD too; remove this marker when that endpoint is repaired.",
    )
    def test_removing_a_polygon_from_the_boundary_drops_the_sub_areas_that_were_in_it(
        self, client, db, w
    ):
        headers, user = _owner(client, db)
        west_poly = w.at(box(0.000, 0.000, 0.008, 0.020))
        east_poly = w.at(box(0.012, 0.000, 0.020, 0.020))
        calc = _calc(db, user, boundary=MultiPolygon([west_poly, east_poly]))
        for name, g in (
            ("in-west", w.at(box(0.001, 0.002, 0.005, 0.006))),
            ("in-east", w.at(box(0.013, 0.002, 0.017, 0.006))),
        ):
            r = client.post(
                f"/api/forests/calculations/{calc.id}/sub-areas",
                headers=headers,
                json={
                    "name": name,
                    "category": "protected",
                    "is_excluded": False,
                    "geometry": mapping(g),
                },
            )
            assert r.status_code == 200, r.text

        boundary_json = db.execute(
            text("select ST_AsGeoJSON(boundary_geom) from calculations where id = :i"),
            {"i": str(calc.id)},
        ).scalar()
        stored_boundary = shape(json.loads(boundary_json))
        east_index = next(
            i for i, p in enumerate(stored_boundary.geoms) if p.intersects(east_poly)
        )

        r = client.post(
            f"/api/forests/calculations/{calc.id}/edit-boundary",
            headers=headers,
            json={
                "operation": "remove_polygon",
                "target_index": east_index,
                "reanalyze": False,
            },
        )
        assert r.status_code == 200, r.text
        assert r.json()["sub_areas_dropped"] == ["in-east"]
        assert set(_stored(db, calc)) == {"in-west"}

    def test_saving_blocks_clips_sub_areas_to_the_forest_the_blocks_make(
        self, client, db, w
    ):
        headers, user = _owner(client, db)
        calc = _calc(db, user, boundary=w.BIG)
        _add_sub_areas(client, headers, calc, w)
        r = client.patch(
            f"/api/forests/calculations/{calc.id}/update-blocks",
            headers=headers,
            json={
                "blocks": [
                    {"block_id": "b1", "block_name": "B1", "geometry": mapping(w.SMALL)}
                ],
                "update_boundary": True,
            },
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["sub_areas_clipped_to_forest"] == ["straddle"], body
        assert body["sub_areas_dropped"] == ["east"], body
        _assert_clipped_to_small(db, calc, w)
        # the legacy per-block clip recorded ~0 ha (square degrees / 10 000); the area must be real
        assert _stored(db, calc)["straddle"]["area_hectares"] > 1.0

    def test_resolving_a_boundary_dispute_clips_the_forests_sub_areas(
        self, client, db, w
    ):
        admin_headers, admin = _owner(client, db, role=UserRole.SUPER_ADMIN)
        target = _calc(db, admin, boundary=w.BIG)
        other = _calc(db, admin, boundary=w.at(box(0.030, 0.0, 0.040, 0.02)))
        _add_sub_areas(client, admin_headers, target, w)
        dispute = BoundaryDispute(
            filed_by_user_id=admin.id,
            forest_id_1=target.id,
            forest_id_2=other.id,
            dispute_reason_np="सीमा विवाद परीक्षण",
            resolution_type=None,
        )
        db.add(dispute)
        db.commit()
        r = client.post(
            f"/api/admin/boundary-disputes/{dispute.id}/resolve",
            headers=admin_headers,
            json={
                "forest_id": str(target.id),
                "new_boundary": mapping(w.SMALL),
                "reason_np": "सीमा सच्याइयो, परीक्षणका लागि",
                "resolution_type": "edit_forest_1",
            },
        )
        assert r.status_code == 200, r.text
        _assert_clipped_to_small(db, target, w)


class TestPersistBoundaryItself:
    def _forest_with_a_protruding_sub_area(self, client, db, w):
        headers, user = _owner(client, db)
        calc = _calc(db, user, boundary=w.BIG)
        _add_sub_areas(client, headers, calc, w)
        db.refresh(calc)
        return calc

    def test_every_write_clips_including_a_replacement_of_an_existing_boundary(
        self, client, db, w
    ):
        calc = self._forest_with_a_protruding_sub_area(client, db, w)
        out = persist_boundary(
            db,
            calc,
            w.SMALL,
            clip_against_neighbours=False,
            validate=False,
        )
        db.commit()
        assert out["sub_areas_reclip"]["clipped"] == ["straddle"]
        assert out["sub_areas_reclip"]["dropped"] == ["east"]
        _assert_clipped_to_small(db, calc, w)

    def test_a_caller_that_reports_its_own_reclip_can_opt_out(self, client, db, w):
        calc = self._forest_with_a_protruding_sub_area(client, db, w)
        out = persist_boundary(
            db,
            calc,
            w.SMALL,
            clip_against_neighbours=False,
            validate=False,
            reclip_sub_areas=False,
        )
        db.commit()
        assert out["sub_areas_reclip"] is None
        assert set(_stored(db, calc)) == {
            "west",
            "straddle",
            "east",
        }  # left for the caller to re-clip

    def test_enlarging_a_boundary_changes_nothing(self, client, db, w):
        headers, user = _owner(client, db)
        calc = _calc(db, user, boundary=w.SMALL)
        r = client.post(
            f"/api/forests/calculations/{calc.id}/sub-areas",
            headers=headers,
            json={
                "name": "w",
                "category": "protected",
                "is_excluded": False,
                "geometry": mapping(w.WEST),
            },
        )
        assert r.status_code == 200, r.text
        db.refresh(calc)
        out = persist_boundary(
            db,
            calc,
            w.BIG,
            clip_against_neighbours=False,
            validate=False,
        )
        assert out["sub_areas_reclip"] == {"clipped": [], "dropped": [], "unchanged": 1}
