"""Divide ONE selected block / compartment by a natural basis (river-ridge, slope, aspect,
canopy) -- the per-feature sibling of the whole-forest Auto-create, which refuses once any
block exists (BLOCKS_EXIST).

FS-4a.6 (D3/D1): the children follow the parent's BRANCH, one level deeper -- a block's
natural divide carves SUB-BLOCKS (the retired chain that minted compartments under a
block is gone), a compartment's carves sub-compartments as before, and any deeper level
may be divided again (A1).

The slope source is used because it needs only a synthetic raster (same fixture shape as
``test_auto_block_slope.py``): a 20x20 grid, columns 1..10 band 1, columns 11..20 band 3.
Every source shares the clip seam under test, so this covers the mechanism for all four.
"""

from __future__ import annotations

import uuid

import pytest
from geoalchemy2.shape import from_shape, to_shape
from shapely import wkt as shapely_wkt
from shapely.geometry import Polygon, mapping, shape
from shapely.ops import unary_union
from sqlalchemy import text

from app.models.calculation import Calculation
from app.models.forest_block import ForestBlock
from app.models.user import User, UserRole
from app.services import auto_block_service as svc

_GRID = [[3 if c >= 11 else 1 for c in range(1, 21)] for _r in range(1, 21)]
_ARR = (
    "ARRAY["
    + ",".join("ARRAY[" + ",".join(str(v) for v in row) + "]" for row in _GRID)
    + "]::double precision[][]"
)
# 0.0001 deg per cell: cols 1..10 = x 84.0000..84.0010 (band 1), cols 11..20 = 84.0010..84.0020 (band 3)
_FOREST = Polygon([(84.0, 27.0), (84.002, 27.0), (84.002, 27.002), (84.0, 27.002)])
# the middle of the forest: x 84.0005..84.0015 -> 5 columns of band 1 and 5 of band 3
_MIDDLE = Polygon(
    [(84.0005, 27.0), (84.0015, 27.0), (84.0015, 27.002), (84.0005, 27.002)]
)


@pytest.fixture()
def slope_raster(db):
    db.execute(text("CREATE SCHEMA IF NOT EXISTS rasters"))
    db.execute(
        text(
            "CREATE TABLE IF NOT EXISTS rasters.slope_regulation (rid serial PRIMARY KEY, rast raster)"
        )
    )
    db.execute(text("DELETE FROM rasters.slope_regulation"))
    db.execute(
        text(
            "INSERT INTO rasters.slope_regulation (rast) SELECT ST_SetValues("
            "  ST_AddBand(ST_MakeEmptyRaster(20, 20, 84.0, 27.002, 0.0001, -0.0001, 0, 0, 4326), '8BUI'::text, 0, 0),"
            f"  1, 1, 1, {_ARR})"
        )
    )
    db.commit()
    yield
    db.execute(text("DROP TABLE IF EXISTS rasters.slope_regulation"))
    db.commit()


def _owner(client, db):
    email = f"autodiv-{uuid.uuid4().hex[:8]}@example.com"
    client.post(
        "/api/auth/register",
        json={"email": email, "password": "TestPass123!", "full_name": "Auto Divide"},
    )
    r = client.post(
        "/api/auth/login", json={"email": email, "password": "TestPass123!"}
    )
    headers = {"Authorization": f"Bearer {r.json()['access_token']}"}
    return headers, db.query(User).filter(User.email == email).first()


def _calc(db, user, result_data=None):
    calc = Calculation(
        id=str(uuid.uuid4()),
        user_id=user.id,
        uploaded_filename="auto-divide.csv",
        is_draft=False,
        structure_locked=False,
        result_data=result_data or {},
    )
    db.add(calc)
    db.flush()
    calc.boundary_geom = from_shape(_FOREST, srid=4326)
    db.commit()
    return calc


def _block(db, calc, geom, name="Block-1", compartment=False, level=1, parent=None):
    row = ForestBlock(
        calculation_id=calc.id,
        name=name,
        block_name=name,
        geometry=from_shape(geom, srid=4326),
        area_hectares=1.0,
        area_sqm=10000.0,
        index=1 if parent is None else 2,
        is_compartment=compartment,
        division_level=level,
        parent_block_id=parent.id if parent is not None else None,
        is_locked=False,
        child_count=0,
    )
    db.add(row)
    db.commit()
    return row


def _url(calc, parent, what):
    return f"/api/v1/calculations/{calc.id}/blocks/{parent.id}/auto-divide/{what}"


def _accept(preview):
    return [
        {
            "index": f["properties"]["index"],
            "name": f["properties"]["name"],
            "natural_name": f["properties"]["natural_name"],
            "dominant_slope_band": f["properties"]["slope_band"],
            "geometry": f["geometry"],
        }
        for f in preview["pieces"]["features"]
    ]


def _children(db, parent):
    db.expire_all()
    return (
        db.query(ForestBlock)
        .filter(ForestBlock.parent_block_id == parent.id)
        .order_by(ForestBlock.display_order)
        .all()
    )


# ---------------------------------------------------------------------------
# the clip seam
# ---------------------------------------------------------------------------
def test_clip_to_scope_is_a_noop_without_a_scope():
    pieces = [_FOREST]
    assert svc._clip_to_scope(pieces, None) is pieces


def test_clip_to_scope_keeps_only_the_part_inside_and_raises_when_nothing_is():
    clipped = svc._clip_to_scope([_FOREST], _MIDDLE)
    assert len(clipped) == 1
    assert clipped[0].area == pytest.approx(_MIDDLE.area)
    far = Polygon([(90.0, 30.0), (90.001, 30.0), (90.001, 30.001)])
    with pytest.raises(ValueError, match="no_coverage_in_feature"):
        svc._clip_to_scope([_FOREST], far)


def test_a_divide_fetches_only_the_feature_not_the_whole_forest(
    client, db, slope_raster, monkeypatch
):
    """Rule 19: the scope has to reach the *fetch*, not just the Python clip.

    ``_clip_to_scope`` after a whole-forest vectorize made this look correct
    while still reading the entire raster once per compartment -- the
    expensive part is invisible to a geometry assertion. The block here is
    ``_MIDDLE`` (exactly half the forest), so the scope handed to the fetch
    must be _MIDDLE-sized; a whole-forest read passes ``None``.
    """
    from app.services.sustainable_fm import slope_vectorize as slope_mod

    seen: list[str | None] = []
    real = slope_mod.slope_class_pieces

    def spy(calc, db, params, scope_wkt=None):
        seen.append(scope_wkt)
        return real(calc, db, params, scope_wkt=scope_wkt)

    monkeypatch.setattr(slope_mod, "slope_class_pieces", spy)

    headers, user = _owner(client, db)
    calc = _calc(db, user)
    parent = _block(db, calc, _MIDDLE)
    r = client.post(
        _url(calc, parent, "preview"), headers=headers, json={"source": "slope"}
    )
    assert r.status_code == 200

    assert seen, "the piece fetch was never called"
    assert seen[0] is not None, (
        "rule 19: the scope must reach the fetch, not only _clip_to_scope"
    )
    scope_area = shapely_wkt.loads(seen[0]).area
    assert scope_area == pytest.approx(_MIDDLE.area)
    assert scope_area == pytest.approx(_FOREST.area / 2)
    # (the whole-forest path always carries the root scope -- boundary-sized by
    # design, FS-4a.6 -- and is covered by test_auto_block_root_scope.py)


# ---------------------------------------------------------------------------
# the endpoints
# ---------------------------------------------------------------------------
def test_a_block_is_divided_by_slope_inside_itself_only(client, db, slope_raster):
    headers, user = _owner(client, db)
    calc = _calc(db, user)
    parent = _block(db, calc, _MIDDLE)

    prev = client.post(
        _url(calc, parent, "preview"), headers=headers, json={"source": "slope"}
    )
    assert prev.status_code == 200, prev.text
    body = prev.json()
    feats = body["pieces"]["features"]
    assert len(feats) == 2  # band 1 and band 3, both inside the middle
    assert body["meta"]["child_layer"] == "sub_blocks"
    assert body["meta"]["parent_name"] == "Block-1"
    assert sorted(f["properties"]["name"] for f in feats) == [
        "Block-1-SB1",
        "Block-1-SB2",
    ]
    # every piece lies inside the parent -- nothing from the rest of the forest leaks in
    inside = to_shape(parent.geometry)
    assert all(
        Polygon(f["geometry"]["coordinates"][0]).difference(inside.buffer(1e-9)).area
        < 1e-12
        for f in feats
    )
    # nothing written by a preview
    assert _children(db, parent) == []

    done = client.post(
        _url(calc, parent, "commit"),
        headers=headers,
        json={"source": "slope", "blocks": _accept(body)},
    )
    assert done.status_code == 200, done.text
    assert done.json()["n_children"] == 2

    kids = _children(db, parent)
    assert [k.division_level for k in kids] == [2, 2]  # one level deeper on the block branch
    assert not any(k.is_compartment for k in kids)
    assert all(k.compartment_code is None for k in kids)
    assert {k.dominant_slope_band for k in kids} == {
        1,
        3,
    }  # each child's OWN class, not the parent's
    assert (
        unary_union([to_shape(k.geometry) for k in kids])
        .symmetric_difference(inside)
        .area
        < 1e-9
    )


def test_a_second_divide_of_the_same_block_is_refused(client, db, slope_raster):
    headers, user = _owner(client, db)
    calc = _calc(db, user)
    parent = _block(db, calc, _MIDDLE)
    prev = client.post(
        _url(calc, parent, "preview"), headers=headers, json={"source": "slope"}
    ).json()
    assert (
        client.post(
            _url(calc, parent, "commit"),
            headers=headers,
            json={"source": "slope", "blocks": _accept(prev)},
        ).status_code
        == 200
    )

    again = client.post(
        _url(calc, parent, "preview"), headers=headers, json={"source": "slope"}
    )
    assert again.status_code == 400
    assert again.json()["detail"]["code"] == "compartments.division_once_only"


def test_a_compartment_is_divided_into_sub_compartments(client, db, slope_raster):
    headers, user = _owner(client, db)
    calc = _calc(db, user)
    parent = _block(db, calc, _MIDDLE, name="C1", compartment=True, level=1)

    prev = client.post(
        _url(calc, parent, "preview"), headers=headers, json={"source": "slope"}
    )
    assert prev.status_code == 200, prev.text
    assert prev.json()["meta"]["child_layer"] == "sub_compartments"
    assert sorted(
        f["properties"]["name"] for f in prev.json()["pieces"]["features"]
    ) == ["C1-SC1", "C1-SC2"]

    done = client.post(
        _url(calc, parent, "commit"),
        headers=headers,
        json={"source": "slope", "blocks": _accept(prev.json())},
    )
    assert done.status_code == 200, done.text
    assert [k.division_level for k in _children(db, parent)] == [2, 2]


def test_private_land_stays_a_hole_in_the_children(client, db, slope_raster):
    private = Polygon(
        [(84.0006, 27.0005), (84.0009, 27.0005), (84.0009, 27.0015), (84.0006, 27.0015)]
    )
    headers, user = _owner(client, db)
    calc = _calc(
        db,
        user,
        result_data={
            "sub_areas": [{"category": "private_land", "geometry": mapping(private)}]
        },
    )
    parent = _block(db, calc, _MIDDLE)

    prev = client.post(
        _url(calc, parent, "preview"), headers=headers, json={"source": "slope"}
    ).json()
    kids_union = unary_union([shape(f["geometry"]) for f in prev["pieces"]["features"]])
    assert (
        kids_union.intersection(private).area < 1e-9
    )  # the same permanent hole the equal-area divide punches out
    assert (
        prev["meta"]["boundary_ha"] < svc._area_m2(to_shape(parent.geometry)) / 10000.0
    )  # the scope is smaller than the parent


def test_a_feature_of_another_forest_is_not_found(client, db, slope_raster):
    headers, user = _owner(client, db)
    calc = _calc(db, user)
    other = _calc(db, user)
    stranger = _block(db, other, _MIDDLE)

    r = client.post(
        _url(calc, stranger, "preview"), headers=headers, json={"source": "slope"}
    )
    assert r.status_code == 400
    assert "PARENT_NOT_FOUND" in str(r.json()["detail"])


def test_commit_never_trusts_the_client_to_stay_inside_the_feature(
    client, db, slope_raster
):
    headers, user = _owner(client, db)
    calc = _calc(db, user)
    parent = _block(db, calc, _MIDDLE)
    half_a = Polygon(
        [(84.0, 27.0), (84.001, 27.0), (84.001, 27.002), (84.0, 27.002)]
    )  # spills out to the west
    half_b = Polygon(
        [(84.001, 27.0), (84.002, 27.0), (84.002, 27.002), (84.001, 27.002)]
    )  # spills out to the east
    blocks = [
        {"index": 1, "geometry": mapping(half_a)},
        {"index": 2, "geometry": mapping(half_b)},
    ]

    done = client.post(
        _url(calc, parent, "commit"),
        headers=headers,
        json={"source": "slope", "blocks": blocks},
    )
    assert done.status_code == 200, done.text
    inside = to_shape(parent.geometry)
    for kid in _children(db, parent):
        assert to_shape(kid.geometry).difference(inside.buffer(1e-9)).area < 1e-12


def test_one_piece_is_not_a_division(client, db, slope_raster):
    headers, user = _owner(client, db)
    calc = _calc(db, user)
    parent = _block(db, calc, _MIDDLE)
    r = client.post(
        _url(calc, parent, "commit"),
        headers=headers,
        json={
            "source": "slope",
            "blocks": [{"index": 1, "geometry": mapping(_MIDDLE)}],
        },
    )
    assert r.status_code == 400
    assert _children(db, parent) == []


def test_a_bad_source_is_a_400(client, db, slope_raster):
    headers, user = _owner(client, db)
    calc = _calc(db, user)
    parent = _block(db, calc, _MIDDLE)
    r = client.post(
        _url(calc, parent, "preview"), headers=headers, json={"source": "moonlight"}
    )
    assert r.status_code == 400


def test_a_compartment_cannot_be_divided_twice_either(client, db, slope_raster):
    headers, user = _owner(client, db)
    calc = _calc(db, user)
    parent = _block(db, calc, _MIDDLE, name="C1", compartment=True, level=1)
    prev = client.post(
        _url(calc, parent, "preview"), headers=headers, json={"source": "slope"}
    ).json()
    assert (
        client.post(
            _url(calc, parent, "commit"),
            headers=headers,
            json={"source": "slope", "blocks": _accept(prev)},
        ).status_code
        == 200
    )

    again = client.post(
        _url(calc, parent, "preview"), headers=headers, json={"source": "slope"}
    )
    assert again.status_code == 400
    assert len(_children(db, parent)) == 2


def test_two_compartments_can_each_be_divided_on_a_different_basis(
    client, db, slope_raster
):
    """The point of the per-feature divide: one piece by slope, its neighbour by something else."""
    headers, user = _owner(client, db)
    calc = _calc(db, user)
    left = Polygon([(84.0, 27.0), (84.001, 27.0), (84.001, 27.002), (84.0, 27.002)])
    right = Polygon(
        [(84.001, 27.0), (84.002, 27.0), (84.002, 27.002), (84.001, 27.002)]
    )
    a = _block(db, calc, left, name="C1", compartment=True, level=1)
    b = _block(db, calc, right, name="C2", compartment=True, level=1)
    for parent in (a, b):
        prev = client.post(
            _url(calc, parent, "preview"),
            headers=headers,
            json={"source": "slope", "sliver_area_m2": 100},
        ).json()
        pieces = _accept(prev)
        if (
            len(pieces) < 2
        ):  # uniform slope: split the piece in two so the commit has something to save
            g = shape(pieces[0]["geometry"])
            minx, miny, maxx, maxy = g.bounds
            mid = (miny + maxy) / 2
            lower = g.intersection(
                Polygon([(minx, miny), (maxx, miny), (maxx, mid), (minx, mid)])
            )
            upper = g.intersection(
                Polygon([(minx, mid), (maxx, mid), (maxx, maxy), (minx, maxy)])
            )
            pieces = [
                {"index": 1, "geometry": mapping(lower)},
                {"index": 2, "geometry": mapping(upper)},
            ]
        assert (
            client.post(
                _url(calc, parent, "commit"),
                headers=headers,
                json={"source": "slope", "blocks": pieces},
            ).status_code
            == 200
        )
    assert len(_children(db, a)) == 2 and len(_children(db, b)) == 2


def _split_in_two(pieces):
    """A uniform-slope block gives one piece; cut it in half so the commit has two to save."""
    g = shape(pieces[0]["geometry"])
    minx, miny, maxx, maxy = g.bounds
    mid = (miny + maxy) / 2
    lower = g.intersection(
        Polygon([(minx, miny), (maxx, miny), (maxx, mid), (minx, mid)])
    )
    upper = g.intersection(
        Polygon([(minx, mid), (maxx, mid), (maxx, maxy), (minx, maxy)])
    )
    return [
        {"index": 1, "geometry": mapping(lower)},
        {"index": 2, "geometry": mapping(upper)},
    ]


def _divide_block(client, headers, calc, parent):
    prev = client.post(
        _url(calc, parent, "preview"),
        headers=headers,
        json={"source": "slope", "sliver_area_m2": 100},
    )
    assert prev.status_code == 200, prev.text
    pieces = _accept(prev.json())
    if len(pieces) < 2:
        pieces = _split_in_two(pieces)
    return client.post(
        _url(calc, parent, "commit"),
        headers=headers,
        json={"source": "slope", "blocks": pieces},
    )


def test_every_block_can_own_sub_blocks(client, db, slope_raster):
    """D3: a top-level block's natural divide always carves SUB-BLOCKS, and every
    block may be divided on its own basis (the chain-era one-block-only
    restriction is gone for the block branch too)."""
    headers, user = _owner(client, db)
    calc = _calc(db, user)
    left = Polygon([(84.0, 27.0), (84.001, 27.0), (84.001, 27.002), (84.0, 27.002)])
    right = Polygon(
        [(84.001, 27.0), (84.002, 27.0), (84.002, 27.002), (84.001, 27.002)]
    )
    a = _block(db, calc, left, name="Block-1")
    b = _block(db, calc, right, name="Block-2")

    first = _divide_block(client, headers, calc, a)
    assert first.status_code == 200, first.text
    assert first.json()["child_layer"] == "sub_blocks"

    second = _divide_block(client, headers, calc, b)
    assert second.status_code == 200, second.text  # never refused: each block on its own basis
    assert second.json()["child_layer"] == "sub_blocks"
    assert len(_children(db, a)) == 2 and len(_children(db, b)) == 2
    assert not any(
        k.is_compartment for parent in (a, b) for k in _children(db, parent)
    )


def test_a_compartment_division_reports_no_undivided_blocks(client, db, slope_raster):
    headers, user = _owner(client, db)
    calc = _calc(db, user)
    parent = _block(db, calc, _MIDDLE, name="C1", compartment=True, level=1)
    done = _divide_block(client, headers, calc, parent)
    assert done.status_code == 200, done.text
    assert (
        done.json()["undivided_blocks"] == 0
    )  # the warning is about blocks, not sub-compartments


def test_a_block_divide_is_not_blocked_by_sampling(client, db, slope_raster):
    """FS-4a.6: a block's natural divide carves SUB-BLOCKS, which never trip the
    compartment <-> sampling-design mutex (the mutex still guards the root
    auto-create's ``compartments`` level -- see test_auto_block_sampling_mutex)."""
    from app.models.sampling import SamplingDesign

    headers, user = _owner(client, db)
    calc = _calc(db, user)
    parent = _block(db, calc, _MIDDLE)
    db.add(SamplingDesign(calculation_id=calc.id, sampling_type="systematic"))
    db.commit()

    prev = client.post(
        _url(calc, parent, "preview"), headers=headers, json={"source": "slope"}
    )
    assert prev.status_code == 200, prev.text
    assert prev.json()["meta"]["child_layer"] == "sub_blocks"

    done = client.post(
        _url(calc, parent, "commit"),
        headers=headers,
        json={"source": "slope", "blocks": _accept(prev.json())},
    )
    assert done.status_code == 200, done.text
    kids = _children(db, parent)
    assert len(kids) == 2
    assert not any(k.is_compartment for k in kids)


def test_a_sub_block_divide_creates_sub_sub_blocks(client, db, slope_raster):
    """A1: deeper nesting stays allowed -- a sub-block may itself be natural-divided
    into sub-blocks (division_level 3, still never a compartment)."""
    headers, user = _owner(client, db)
    calc = _calc(db, user)
    top = _block(db, calc, _MIDDLE, name="Block-1")
    first = _divide_block(client, headers, calc, top)
    assert first.status_code == 200, first.text
    sub = _children(db, top)[0]
    assert sub.name == "Block-1-SB1"

    prev = client.post(
        _url(calc, sub, "preview"),
        headers=headers,
        json={"source": "slope", "sliver_area_m2": 100},
    )
    assert prev.status_code == 200, prev.text
    assert prev.json()["meta"]["child_layer"] == "sub_blocks"
    assert prev.json()["meta"]["parent_name"] == "Block-1-SB1"
    pieces = _accept(prev.json())
    if len(pieces) < 2:
        pieces = _split_in_two(pieces)
    again = client.post(
        _url(calc, sub, "commit"),
        headers=headers,
        json={"source": "slope", "blocks": pieces, "sliver_area_m2": 100},
    )
    assert again.status_code == 200, again.text
    subsub = _children(db, sub)
    assert len(subsub) == 2
    assert [k.division_level for k in subsub] == [3, 3]
    assert not any(k.is_compartment for k in subsub)
    # two levels only (top_unit_name): the pieces of a sub-block are named from the TOP unit, never "Block-1-SB1-SB1"
    assert all(k.name.startswith("Block-1-SB") and "-SB1-SB" not in k.name for k in subsub), [k.name for k in subsub]


def test_explicit_level_may_name_your_own_branch(client, db, slope_raster):
    """``level`` (FS-4a.6) names the children, but only the ones the parent's own
    branch infers -- the chain's block -> compartments is gone."""
    headers, user = _owner(client, db)
    calc = _calc(db, user)

    block = _block(db, calc, _MIDDLE, name="Block-1")
    prev = client.post(
        _url(calc, block, "preview"),
        headers=headers,
        json={"source": "slope", "level": "sub_blocks"},
    )
    assert prev.status_code == 200, prev.text
    assert prev.json()["meta"]["child_layer"] == "sub_blocks"

    comp = _block(db, calc, _FOREST, name="C1", compartment=True, level=1)
    comb = client.post(
        _url(calc, comp, "preview"),
        headers=headers,
        json={"source": "slope", "level": "sub_compartments"},
    )
    assert comb.status_code == 200, comb.text
    assert comb.json()["meta"]["child_layer"] == "sub_compartments"


def test_a_mismatched_level_is_a_400_bad_level(client, db, slope_raster):
    headers, user = _owner(client, db)
    calc = _calc(db, user)

    block = _block(db, calc, _MIDDLE, name="Block-1")
    r = client.post(
        _url(calc, block, "preview"),
        headers=headers,
        json={"source": "slope", "level": "sub_compartments"},
    )
    assert r.status_code == 400
    assert r.json()["detail"]["code"] == "blocks.bad_level"

    comp = _block(db, calc, _MIDDLE, name="C1", compartment=True, level=1)
    r2 = client.post(
        _url(calc, comp, "commit"),
        headers=headers,
        json={
            "source": "slope",
            "level": "sub_blocks",
            "blocks": [{"index": 1, "geometry": mapping(_MIDDLE)}],
        },
    )
    assert r2.status_code == 400
    assert r2.json()["detail"]["code"] == "blocks.bad_level"
    assert _children(db, comp) == []
