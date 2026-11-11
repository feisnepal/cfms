"""Preview -> commit class pass-through (RS-2.10).

The previews emit **bare** class keys (`slope_band`, `aspect_code`,
`canopy_class`, `nasa_quality`) because that is what the source registry calls
them, while `commit_blocks` stores them into `dominant_*` columns. The two halves
of the service disagreed on the name and only the frontend bridged it, by
renaming the key when it builds the payload (`AutoBlockDesigner.tsx:378-381`).

That went unnoticed for two reasons, both of which this file exists to remove:

1. Every test that exercised commit -> persist did the rename **in the test
   body** (`"dominant_canopy_class": f["properties"]["canopy_class"]`), so the
   suite encoded the workaround instead of the contract.
2. No test ever handed a *raw* preview feature collection to `commit_blocks`.
   The NASA tests never called `commit_blocks` at all.

So a caller that did the natural thing -- preview, then commit the output -- got
NULL for **every** block, with no error and no warning. Found by the P2 dry run
on live data, not by any test.

`aspect_code` is why the mapping is an explicit table: it cannot be derived by
stripping the `dominant_` prefix.
"""

from __future__ import annotations

import ast
import uuid
from pathlib import Path

import pytest
from geoalchemy2.shape import from_shape
from shapely.geometry import Polygon
from sqlalchemy import text

from app.models.calculation import Calculation
from app.models.forest_block import ForestBlock
from app.models.user import User, UserRole
from app.services import auto_block_service as svc

SERVICE = Path(svc.__file__)

# Props keys that are NOT dominant classes, so the AST guard can tell a new
# class key from ordinary metadata.
_NOT_CLASS = {
    "index",
    "name",
    "block_name",
    "natural_name",
    "area_hectares",
    # Preview-only diagnostic (RS-2.14): says *why* `nasa_quality` is what it is
    # ("anonymous" / "no_coverage" / "failed"). Deliberately not persisted -- it
    # explains a NULL, it is not a classification, and the fact it explains
    # (`dominant_nasa_code`) is stored instead.
    "nasa_quality_reason",
}

# Every preview that emits a dominant class today.
_PREVIEWS_WITH_CLASSES = (
    "preview_slope_blocks",
    "preview_aspect_blocks",
    "preview_canopy_blocks",
    "preview_nasa_quality_blocks",
)


# ---------------------------------------------------------------------------
# the reader itself
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "field,bare,value",
    [
        ("dominant_slope_band", "slope_band", 3),
        ("dominant_aspect", "aspect_code", 7),
        ("dominant_canopy_class", "canopy_class", 1),
        ("dominant_nasa_quality", "nasa_quality", 2),
        # 0 is a real answer here (non-forest), and it must survive the read --
        # a falsy check here would silently turn "classified as non-forest" back
        # into the NULL this column exists to explain (RS-2.14).
        ("dominant_nasa_code", "dominant_nasa_code", 0),
        ("dominant_health_class", "health_class", 4),
        ("dominant_landcover", "landcover", 5),
        # RS-9.3/9.5: NOT dominant_elevation_zone -- that column deliberately
        # has no preview bare-key (RS-2.19 computes it post-hoc for every
        # source; see _PREVIEW_CLASS_KEYS's own comment).
        ("dominant_contour_band", "contour_band", 2),
        ("dominant_forest_type", "forest_type", 9),
    ],
)
def test_dominant_class_reads_the_bare_key_a_preview_emits(field, bare, value):
    """The whole point: a payload carrying only the preview's own key still
    yields the class instead of None."""
    assert svc._dominant_class({bare: value}, field) == value


def test_dominant_class_prefers_the_explicit_dominant_key():
    """The frontend's spelling wins when both are present, so the reader can
    only ever add a value the caller meant to supply -- never override one."""
    both = {"dominant_nasa_quality": 3, "nasa_quality": 1}
    assert svc._dominant_class(both, "dominant_nasa_quality") == 3


def test_dominant_class_returns_none_when_absent():
    assert svc._dominant_class({}, "dominant_nasa_quality") is None
    assert svc._dominant_class({"index": 1}, "dominant_canopy_class") is None


def test_dominant_class_ignores_an_unmapped_field():
    """An unmapped field must not blow up -- `get("")` returns None, and a
    class-0 / anonymous piece legitimately has no value at all."""
    assert svc._dominant_class({"nasa_quality": 2}, "dominant_unknown") is None


# ---------------------------------------------------------------------------
# the guard that stops a NEW source from being silently unhandled
# ---------------------------------------------------------------------------


def _props_keys_in(func_name):
    tree = ast.parse(SERVICE.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == func_name:
            keys = set()
            for sub in ast.walk(node):
                if (
                    isinstance(sub, ast.Assign)
                    and any(
                        isinstance(t, ast.Name) and t.id == "props"
                        for t in sub.targets
                    )
                    and isinstance(sub.value, ast.Dict)
                ):
                    for k in sub.value.keys:
                        if isinstance(k, ast.Constant) and isinstance(k.value, str):
                            keys.add(k.value)
            return keys
    raise AssertionError("preview function not found: %s" % func_name)


def test_every_class_key_a_preview_emits_is_handled_by_the_reader():
    """A new source that emits a class key the reader does not know about would
    persist NULL for every block, silently -- exactly the bug this row closes.
    So any non-metadata key a preview emits must appear in the map."""
    handled = set(svc._PREVIEW_CLASS_KEYS.values())
    for fn in _PREVIEWS_WITH_CLASSES:
        keys = _props_keys_in(fn)
        assert keys, "no props dict found in %s" % fn
        unhandled = {
            k
            for k in keys
            if k not in _NOT_CLASS
            and not k.endswith("_label")
            and not k.endswith("_label_en")
            and not k.endswith("_label_ne")
            and k not in handled
        }
        assert not unhandled, (
            "%s emits class key(s) the commit reader does not accept: %s -- add "
            "them to _PREVIEW_CLASS_KEYS or they will persist as NULL"
            % (fn, sorted(unhandled))
        )


def test_the_map_covers_every_dominant_class_column_the_model_has():
    """Belt and braces: every class column that a PREVIEW populates must be
    reachable from some preview key, so a column cannot be added and then
    never populated.

    `dominant_elevation_zone` is the one deliberate exception: RS-2.19
    computes it post-hoc, for every source, in `commit_blocks` itself
    (`assign_relative_elevation_zones`) rather than from a preview payload --
    it is not missing a key, it was never meant to have one."""
    cols = {
        "dominant_slope_band",
        "dominant_aspect",
        "dominant_canopy_class",
        "dominant_health_class",
        "dominant_nasa_quality",
        "dominant_nasa_code",
        "dominant_landcover",
        "dominant_forest_type",
        "dominant_contour_band",
    }
    assert cols <= set(svc._PREVIEW_CLASS_KEYS), (
        "columns with no preview key: %s" % sorted(cols - set(svc._PREVIEW_CLASS_KEYS))
    )
    assert "dominant_elevation_zone" not in svc._PREVIEW_CLASS_KEYS


# ---------------------------------------------------------------------------
# the end-to-end round-trip that was never tested
# ---------------------------------------------------------------------------

_GRID = [[3 if c >= 11 else 1 for c in range(1, 21)] for _r in range(1, 21)]
_GRID[4][4] = 2
_ARR = (
    "ARRAY["
    + ",".join("ARRAY[" + ",".join(str(v) for v in row) + "]" for row in _GRID)
    + "]::double precision[][]"
)
_BBOX = Polygon([(84.0, 27.0), (84.002, 27.0), (84.002, 27.002), (84.0, 27.002)])


@pytest.fixture()
def nasa_raster(db):
    db.execute(text("CREATE SCHEMA IF NOT EXISTS rasters"))
    db.execute(
        text(
            "CREATE TABLE IF NOT EXISTS rasters.nasa_forest_2020 "
            "(rid serial PRIMARY KEY, rast raster)"
        )
    )
    db.execute(text("DELETE FROM rasters.nasa_forest_2020"))
    db.execute(
        text(
            "INSERT INTO rasters.nasa_forest_2020 (rast) SELECT ST_SetValues("
            "  ST_AddBand("
            "    ST_MakeEmptyRaster(20, 20, 84.0, 27.002, 0.0001, -0.0001, 0, 0, 4326),"
            "    '8BUI'::text, 0, 0),"
            f"  1, 1, 1, {_ARR})"
        )
    )
    db.commit()
    yield
    db.execute(text("DROP TABLE IF EXISTS rasters.nasa_forest_2020"))
    db.commit()


def _make_calc(db):
    user = User(
        email=f"passthru{uuid.uuid4().hex[:8]}@test.com",
        full_name="Pass-through Tester",
        hashed_password="not-a-real-hash",
        role=UserRole.USER,
    )
    db.add(user)
    db.flush()
    calc = Calculation(
        id=str(uuid.uuid4()),
        user_id=user.id,
        uploaded_filename="passthru-test.csv",
        is_draft=False,
        structure_locked=False,
        boundary_geom=from_shape(_BBOX, srid=4326),
    )
    db.add(calc)
    db.commit()
    db.refresh(calc)
    return calc


def test_raw_nasa_preview_features_persist_their_class(db, nasa_raster):
    """Preview -> commit with the features passed through **unchanged**.

    No rename, no hand-built payload: the natural service-level round-trip. This
    is the test whose absence let RS-2.10 ship. Before the fix every block came
    back NULL; the frontend masked it by renaming the key client-side.
    """
    calc = _make_calc(db)
    res = svc.preview_nasa_quality_blocks(db, calc, level="blocks")
    feats = res["pieces"]["features"]
    assert feats, "preview produced no features"

    expected = {f["properties"]["nasa_quality"] for f in feats}
    assert None not in expected, "fixture should yield at least one labelled piece"
    assert expected, "no classes at all"

    # The features go in EXACTLY as the preview emitted them.
    payload = [dict(f["properties"], geometry=f["geometry"]) for f in feats]
    created = svc.commit_blocks(db, calc, payload, level="blocks")
    assert created, "commit created nothing"

    rows = db.query(ForestBlock).filter(ForestBlock.calculation_id == calc.id).all()
    assert rows
    persisted = {r.dominant_nasa_quality for r in rows}
    assert None not in persisted, (
        "at least one block persisted NULL -- the preview's own class key was "
        "dropped again"
    )
    assert persisted <= expected, "persisted a class the preview never emitted"
    assert persisted, "every block persisted NULL"
