"""Sub-areas: always inside the forest, never overlapping each other.

Both rules are absolute and are enforced (and re-verified) in one place,
`sub_area_service.enforce_within_and_disjoint`, which `POST .../sub-areas` uses.
Pasting sub-areas goes through that endpoint, and so does drawing one.

What used to slip through (found by probing the live API):
  - a forest with blocks but no `boundary_geom`: a sub-area anywhere was stored,
    completely unclipped;
  - an intersection that came back as a `GeometryCollection` (polygon + stray
    edge) or a `Point` was stored as the sub-area, because only `is_empty` was
    checked;
  - a client-supplied `area_hectares` was trusted even after the geometry had
    been trimmed, so the recorded area described land that was cut away.
"""

from __future__ import annotations

import uuid

import pytest
from geoalchemy2.shape import from_shape
from shapely.geometry import Polygon, box, shape

from app.models.calculation import Calculation
from app.models.forest_block import ForestBlock
from app.models.user import User
from app.services.boundary_write_service import persist_boundary

# A "U": two lobes joined by a neck. The gap between the lobes is OUTSIDE.
U_SHAPE = Polygon(
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
BLOCK = box(84.000, 27.000, 84.002, 27.002)
TOL = 1e-9


def _owner(client, db):
    email = f"subarea-{uuid.uuid4().hex[:8]}@example.com"
    client.post(
        "/api/auth/register",
        json={"email": email, "password": "TestPass123!", "full_name": "SA Tester"},
    )
    r = client.post(
        "/api/auth/login", json={"email": email, "password": "TestPass123!"}
    )
    return (
        {"Authorization": f"Bearer {r.json()['access_token']}"},
        db.query(User).filter(User.email == email).first(),
    )


def _calc(db, user, boundary=None, blocks=()):
    calc = Calculation(
        id=uuid.uuid4(),
        user_id=user.id,
        uploaded_filename="sub-area-rules.csv",
        is_draft=False,
    )
    db.add(calc)
    db.flush()
    if boundary is not None:
        calc.boundary_geom = from_shape(boundary, srid=4326)
    for i, b in enumerate(blocks, start=1):
        db.add(
            ForestBlock(
                calculation_id=calc.id,
                name=f"Block-{i}",
                block_name=f"Block-{i}",
                index=i,
                geometry=from_shape(b, srid=4326),
                area_hectares=1,
                area_sqm=10000,
                is_compartment=False,
                division_level=1,
            )
        )
    db.commit()
    return calc


def _post(client, headers, calc, name, geom, category="protected", **extra):
    body = {
        "name": name,
        "category": category,
        "is_excluded": False,
        "geometry": {"type": "Polygon", "coordinates": [list(geom.exterior.coords)]},
        **extra,
    }
    return client.post(
        f"/api/forests/calculations/{calc.id}/sub-areas", headers=headers, json=body
    )


def _stored(client, headers, calc):
    body = client.get(
        f"/api/forests/calculations/{calc.id}/sub-areas", headers=headers
    ).json()
    return body.get("sub_areas", body) if isinstance(body, dict) else body


def _inside(g, extent):
    return g.difference(extent.buffer(TOL)).area < 1e-12


# ---------------------------------------------------------------------------
# Rule 1 — inside the forest
# ---------------------------------------------------------------------------
class TestInsideTheBoundary:
    @pytest.fixture()
    def forest(self, client, db):
        headers, user = _owner(client, db)
        return client, headers, _calc(db, user, boundary=U_SHAPE)

    def test_a_sub_area_inside_is_stored_as_submitted(self, forest):
        client, headers, calc = forest
        r = _post(
            client, headers, calc, "inside", box(84.0005, 27.0005, 84.0015, 27.0035)
        )
        assert r.status_code == 200, r.text
        assert shape(r.json()["geometry"]).geom_type == "Polygon"

    def test_fully_outside_is_refused(self, forest):
        client, headers, calc = forest
        r = _post(
            client, headers, calc, "far away", box(84.010, 27.010, 84.011, 27.011)
        )
        assert r.status_code == 400
        assert "outside the forest boundary" in r.text
        assert _stored(client, headers, calc) == []

    def test_lying_in_the_gap_of_the_boundary_is_refused(self, forest):
        client, headers, calc = forest
        # inside the U's bounding box, but outside the U itself
        r = _post(client, headers, calc, "gap", box(84.0022, 27.002, 84.0038, 27.003))
        assert r.status_code == 400

    def test_straddling_the_edge_is_clipped_to_the_boundary(self, forest):
        client, headers, calc = forest
        submitted = box(
            84.0015, 27.002, 84.0030, 27.003
        )  # half in lobe A, half in the gap
        r = _post(client, headers, calc, "straddle", submitted)
        assert r.status_code == 200, r.text
        g = shape(r.json()["geometry"])
        assert _inside(g, U_SHAPE)
        assert g.area == pytest.approx(submitted.intersection(U_SHAPE).area, rel=1e-6)

    def test_a_polygon_that_also_touches_the_boundary_along_a_stray_edge_stays_a_polygon(
        self, forest
    ):
        """Overlaps lobe A AND merely touches lobe B's edge: the raw intersection is a
        GeometryCollection (polygon + line). Only the polygon may be stored."""
        client, headers, calc = forest
        submitted = box(84.001, 27.002, 84.004, 27.003)
        assert (
            submitted.intersection(U_SHAPE).geom_type == "GeometryCollection"
        )  # the trap is real
        r = _post(client, headers, calc, "collection", submitted)
        assert r.status_code == 200, r.text
        g = shape(r.json()["geometry"])
        assert g.geom_type in ("Polygon", "MultiPolygon")
        assert _inside(g, U_SHAPE)

    def test_touching_the_boundary_at_a_corner_only_is_refused_not_stored_as_a_point(
        self, forest
    ):
        client, headers, calc = forest
        r = _post(client, headers, calc, "corner", box(84.002, 27.004, 84.003, 27.005))
        assert r.status_code == 400
        assert _stored(client, headers, calc) == []

    def test_touching_the_boundary_along_an_edge_only_is_refused_not_stored_as_a_line(
        self, forest
    ):
        client, headers, calc = forest
        submitted = box(
            84.002, 27.002, 84.003, 27.003
        )  # shares lobe A's right edge, lies in the gap
        assert submitted.intersection(U_SHAPE).geom_type == "LineString"
        r = _post(client, headers, calc, "edge", submitted)
        assert r.status_code == 400
        assert _stored(client, headers, calc) == []

    def test_the_area_of_a_trimmed_sub_area_is_recomputed_not_taken_from_the_client(
        self, forest
    ):
        client, headers, calc = forest
        r = _post(
            client,
            headers,
            calc,
            "liar",
            box(84.0015, 27.002, 84.0030, 27.003),
            area_hectares=999,
        )
        assert r.status_code == 200, r.text
        assert r.json()["area_hectares"] != 999
        assert r.json()["area_hectares"] < 1.2  # the ~0.55 ha that is actually inside

    def test_the_area_of_an_untrimmed_sub_area_still_honours_the_client_value(
        self, forest
    ):
        client, headers, calc = forest
        r = _post(
            client,
            headers,
            calc,
            "as-drawn",
            box(84.0005, 27.0005, 84.0015, 27.0035),
            area_hectares=5.0,
        )
        assert r.status_code == 200, r.text
        assert r.json()["area_hectares"] == 5.0


class TestForestWithBlocksButNoBoundary:
    """`has_forest_extent` accepts blocks as the extent, but nothing clipped to them."""

    @pytest.fixture()
    def forest(self, client, db):
        headers, user = _owner(client, db)
        calc = _calc(db, user, boundary=None, blocks=[BLOCK])
        assert calc.boundary_geom is None
        return client, headers, calc

    def test_inside_the_blocks_is_accepted(self, forest):
        client, headers, calc = forest
        assert (
            _post(
                client, headers, calc, "in", box(84.0005, 27.0005, 84.0015, 27.0015)
            ).status_code
            == 200
        )

    def test_outside_the_blocks_is_refused(self, forest):
        client, headers, calc = forest
        r = _post(client, headers, calc, "out", box(84.010, 27.010, 84.011, 27.011))
        assert r.status_code == 400
        assert _stored(client, headers, calc) == []

    def test_straddling_the_blocks_is_clipped_to_them(self, forest):
        client, headers, calc = forest
        r = _post(
            client, headers, calc, "straddle", box(84.0015, 27.0015, 84.0030, 27.0030)
        )
        assert r.status_code == 200, r.text
        assert _inside(shape(r.json()["geometry"]), BLOCK)


class TestNoForestYet:
    """Nothing to clip to: sub-areas are kept, kept disjoint, and marked pending
    so that the first boundary clips them (see TestBoundaryGoingLive)."""

    def test_a_sub_area_is_stored_marked_pending(self, client, db):
        headers, user = _owner(client, db)
        calc = _calc(db, user, boundary=None)
        r = _post(client, headers, calc, "early", box(84.0, 27.0, 84.001, 27.001))
        assert r.status_code == 200, r.text
        db.refresh(calc)
        assert calc.result_data["sub_areas"][0]["pending_boundary_clip"] is True

    def test_pending_sub_areas_still_never_overlap(self, client, db):
        headers, user = _owner(client, db)
        calc = _calc(db, user, boundary=None)
        first = box(84.0, 27.0, 84.002, 27.002)
        assert _post(client, headers, calc, "first", first).status_code == 200
        r = _post(
            client,
            headers,
            calc,
            "second",
            box(84.001, 27.001, 84.003, 27.003),
            category="plantation",
        )
        assert r.status_code == 200, r.text
        assert shape(r.json()["geometry"]).intersection(first).area < 1e-12
        # ...and one wholly inside another is refused, as always
        assert (
            _post(
                client, headers, calc, "inner", box(84.0005, 27.0005, 84.0015, 27.0015)
            ).status_code
            == 400
        )

    def test_a_sub_area_with_a_forest_is_not_marked_pending(self, client, db):
        headers, user = _owner(client, db)
        calc = _calc(db, user, boundary=box(84.0, 27.0, 84.01, 27.01))
        assert (
            _post(
                client, headers, calc, "normal", box(84.001, 27.001, 84.002, 27.002)
            ).status_code
            == 200
        )
        db.refresh(calc)
        assert "pending_boundary_clip" not in calc.result_data["sub_areas"][0]


# ---------------------------------------------------------------------------
# Rule 2 — sub-areas never overlap each other (first created keeps the ground)
# ---------------------------------------------------------------------------
class TestNoOverlapBetweenSubAreas:
    @pytest.fixture()
    def forest(self, client, db):
        headers, user = _owner(client, db)
        return client, headers, _calc(db, user, boundary=box(84.0, 27.0, 84.01, 27.01))

    def test_a_partly_overlapping_sub_area_gives_up_the_overlap(self, forest):
        client, headers, calc = forest
        first = box(84.001, 27.001, 84.003, 27.003)
        second = box(84.002, 27.002, 84.004, 27.004)  # overlaps a quarter of each
        assert _post(client, headers, calc, "first", first).status_code == 200
        r = _post(client, headers, calc, "second", second, category="plantation")
        assert r.status_code == 200, r.text
        g = shape(r.json()["geometry"])
        assert g.intersection(first).area < 1e-12
        assert g.area == pytest.approx(second.difference(first).area, rel=1e-6)

    def test_a_sub_area_entirely_inside_another_is_refused(self, forest):
        client, headers, calc = forest
        assert (
            _post(
                client, headers, calc, "first", box(84.001, 27.001, 84.003, 27.003)
            ).status_code
            == 200
        )
        r = _post(
            client, headers, calc, "inner", box(84.0015, 27.0015, 84.0025, 27.0025)
        )
        assert r.status_code == 400
        assert "entirely within existing sub-areas" in r.text
        assert len(_stored(client, headers, calc)) == 1

    def test_an_identical_copy_is_refused(self, forest):
        client, headers, calc = forest
        same = box(84.001, 27.001, 84.003, 27.003)
        assert _post(client, headers, calc, "first", same).status_code == 200
        assert _post(client, headers, calc, "again", same).status_code == 400
        assert len(_stored(client, headers, calc)) == 1

    def test_a_neighbour_sharing_only_an_edge_is_kept_whole(self, forest):
        client, headers, calc = forest
        assert (
            _post(
                client, headers, calc, "left", box(84.001, 27.001, 84.002, 27.002)
            ).status_code
            == 200
        )
        right = box(84.002, 27.001, 84.003, 27.002)
        r = _post(client, headers, calc, "right", right, category="plantation")
        assert r.status_code == 200, r.text
        assert shape(r.json()["geometry"]).area == pytest.approx(right.area, rel=1e-6)

    def test_a_whole_paste_batch_ends_with_no_two_sub_areas_overlapping(self, forest):
        """The paste sends features one after another; each must give way to those before."""
        client, headers, calc = forest
        squares = [
            box(84.001 + i * 0.0006, 27.001, 84.001 + i * 0.0006 + 0.001, 27.002)
            for i in range(5)
        ]
        for i, sq in enumerate(squares):
            _post(client, headers, calc, f"s{i}", sq, category="plantation")
        geoms = [shape(s["geometry"]) for s in _stored(client, headers, calc)]
        assert len(geoms) == 5
        for i in range(len(geoms)):
            for j in range(i + 1, len(geoms)):
                assert (
                    geoms[i].intersection(geoms[j]).area < 1e-12
                ), f"sub-areas {i} and {j} overlap"


# ---------------------------------------------------------------------------
# The boundary going live clips what was recorded before it
# ---------------------------------------------------------------------------
class TestBoundaryGoingLive:
    def _forest_with_a_block_sub_area(self, client, db):
        headers, user = _owner(client, db)
        calc = _calc(db, user, boundary=None, blocks=[BLOCK])
        r = _post(
            client, headers, calc, "wide", box(84.0005, 27.0005, 84.0018, 27.0018)
        )
        assert r.status_code == 200, r.text
        db.refresh(calc)
        return headers, calc

    def test_the_first_boundary_clips_sub_areas_recorded_before_it(self, client, db):
        headers, calc = self._forest_with_a_block_sub_area(client, db)
        new_boundary = box(84.0, 27.0, 84.001, 27.002)  # narrower than the block

        out = persist_boundary(
            db,
            calc,
            new_boundary,
            clip_against_neighbours=False,
            validate=False,
        )
        db.commit()
        db.refresh(calc)

        assert out["sub_areas_reclip"]["clipped"] == ["wide"]
        stored = shape(calc.result_data["sub_areas"][0]["geometry"])
        assert _inside(stored, new_boundary)

    def test_a_sub_area_left_wholly_outside_the_new_boundary_is_dropped_and_reported(
        self, client, db
    ):
        headers, calc = self._forest_with_a_block_sub_area(client, db)
        far_boundary = box(
            84.0019, 27.0, 84.003, 27.002
        )  # nothing of "wide" is inside it
        out = persist_boundary(
            db,
            calc,
            far_boundary,
            clip_against_neighbours=False,
            validate=False,
        )
        db.commit()
        db.refresh(calc)
        assert out["sub_areas_reclip"]["dropped"] == ["wide"]
        assert calc.result_data["sub_areas"] == []

    def test_reshaping_an_existing_boundary_clips_too(self, client, db):
        """Every boundary write clips, not only the first one. (An edit path that re-clips
        and reports on its own opts out with ``reclip_sub_areas=False`` -- see
        test_sub_area_boundary_paths.py.)"""
        headers, user = _owner(client, db)
        calc = _calc(db, user, boundary=box(84.0, 27.0, 84.01, 27.01))
        assert (
            _post(
                client, headers, calc, "s", box(84.001, 27.001, 84.005, 27.005)
            ).status_code
            == 200
        )
        db.refresh(calc)
        out = persist_boundary(
            db,
            calc,
            box(84.0, 27.0, 84.002, 27.002),
            clip_against_neighbours=False,
            validate=False,
        )
        assert out["sub_areas_reclip"]["clipped"] == ["s"]

    def test_a_first_boundary_with_no_sub_areas_does_nothing_extra(self, client, db):
        headers, user = _owner(client, db)
        calc = _calc(db, user, boundary=None)
        out = persist_boundary(
            db,
            calc,
            box(84.0, 27.0, 84.002, 27.002),
            clip_against_neighbours=False,
            validate=False,
        )
        assert out["sub_areas_reclip"] is None

    # -- no forest at all, sub-areas pasted first, boundary drawn afterwards ---
    def test_pending_sub_areas_are_clipped_when_the_boundary_first_goes_live(
        self, client, db
    ):
        headers, user = _owner(client, db)
        calc = _calc(db, user, boundary=None)
        assert (
            _post(
                client,
                headers,
                calc,
                "sticks-out",
                box(84.0005, 27.0005, 84.0030, 27.0018),
            ).status_code
            == 200
        )
        assert (
            _post(
                client,
                headers,
                calc,
                "wholly-in",
                box(84.0002, 27.0022, 84.0006, 27.0026),
                category="plantation",
            ).status_code
            == 200
        )
        assert (
            _post(
                client,
                headers,
                calc,
                "wholly-out",
                box(84.0100, 27.0100, 84.0110, 27.0110),
                category="tourist",
            ).status_code
            == 200
        )
        db.refresh(calc)

        boundary = box(84.0, 27.0, 84.002, 27.003)
        out = persist_boundary(
            db,
            calc,
            boundary,
            clip_against_neighbours=False,
            validate=False,
        )
        db.commit()
        db.refresh(calc)

        assert out["sub_areas_reclip"]["clipped"] == ["sticks-out"]
        assert out["sub_areas_reclip"]["dropped"] == ["wholly-out"]
        kept = {sa["name"]: sa for sa in calc.result_data["sub_areas"]}
        assert set(kept) == {"sticks-out", "wholly-in"}
        for sa in kept.values():
            assert _inside(shape(sa["geometry"]), boundary), sa["name"]
            assert "pending_boundary_clip" not in sa  # settled: no longer pending

    def test_a_pending_sub_area_already_inside_is_still_settled(self, client, db):
        """Nothing needed cutting, but the marker must still be cleared and saved."""
        headers, user = _owner(client, db)
        calc = _calc(db, user, boundary=None)
        assert (
            _post(
                client, headers, calc, "inside", box(84.0005, 27.0005, 84.0015, 27.0015)
            ).status_code
            == 200
        )
        db.refresh(calc)
        assert calc.result_data["sub_areas"][0]["pending_boundary_clip"] is True

        persist_boundary(
            db,
            calc,
            box(84.0, 27.0, 84.002, 27.002),
            clip_against_neighbours=False,
            validate=False,
        )
        db.commit()
        db.refresh(calc)
        assert "pending_boundary_clip" not in calc.result_data["sub_areas"][0]
