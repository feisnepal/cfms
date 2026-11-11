"""Why a NASA compartment has no class (RS-2.14).

Owner report, 2026-09-30: "In preview I only see primary class in one polygon.
other do not have any class. It should be considerd as only one polygon has the
data but other has no data and actuallly is wrong. why other polygon data is
missing in preview?"

Nothing was missing. NASA code 0 is non-forest ground -- grassland, bare, urban
-- which the plan carves as geometry but deliberately never reports as a class
(RS-2.5 / D41). So `dominant_code` returned ``None`` for *every* absence:

* the raster classified the compartment as mostly non-forest,
* the raster never covered the compartment,
* the query raised and was swallowed by a bare ``except``.

Measured on calc 62352bc1 (186.3 ha) by hand with `ST_ValueCount`: 5 of the 7
substantial blocks are 0-dominated (Block-2 66.8% code 0, Block-4 46.4%,
Block-5 50.3%, Block-6 55.3%, Block-7 47.2%), so 16 of 18 preview pieces rendered
as an empty cell. `dominant_class` now says which of the three it was, and the
raw code survives to the database as `dominant_nasa_code` (migration 106).

Most of this file is the pure decision table, because that decision *is* the bug:
synthesising a code-0 PostGIS raster to prove "0 is anonymous" needs nodata set
correctly (this PostGIS has no 10-arg `ST_MakeEmptyRaster`, and its 9-arg default
makes 0 the nodata value, which would make a non-forest raster report as *no
coverage* instead) and only proves the thing the pure function already states.
"""
import pytest

# The raster fixture is not rebuilt here: this PostGIS has no 10-arg
# ST_MakeEmptyRaster and its 9-arg default makes 0 the nodata value, so a
# code-0 raster cannot be synthesised the obvious way. The sibling module's
# fixture is proven against this exact PostGIS, so it is borrowed as-is.
from tests.services.test_auto_block_class_passthrough import (  # noqa: F401
    nasa_raster,
)

from app.models.forest_block import ForestBlock
from app.services import auto_block_service as svc
from app.services.raster_class_vectorize import (
    DOMINANT_ANONYMOUS,
    DOMINANT_FAILED,
    DOMINANT_NO_COVERAGE,
    DOMINANT_NO_GEOMETRY,
    DOMINANT_OK,
    NASA_QUALITY,
    classify_dominant,
)

# a box over a column of the fixture raster that is all code 1
BOX_CLASS_1 = (
    "POLYGON((84.0005 27.0005, 84.0010 27.0005, "
    "84.0010 27.0010, 84.0005 27.0010, 84.0005 27.0005))"
)
# a box over a column that is all code 3 (the fixture grid switches at column 11)
BOX_CLASS_3 = (
    "POLYGON((84.0015 27.0005, 84.0020 27.0005, "
    "84.0020 27.0010, 84.0015 27.0010, 84.0015 27.0005))"
)


# ---------------------------------------------------------------------------
# the decision table: the bug in one place
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw,code,reason",
    [
        (1, 1, DOMINANT_OK),
        (2, 2, DOMINANT_OK),
        (3, 3, DOMINANT_OK),
        # THE REPORTED BUG: 0 is a real, mappable class that this vocabulary
        # refuses to call a class. `code` is empty, `raw_code` is 0, and the
        # reason says why -- which is what lets the UI print "Non-forest (0)".
        (0, None, DOMINANT_ANONYMOUS),
        # ... and that is nothing like not knowing.
        (None, None, DOMINANT_NO_COVERAGE),
    ],
)
def test_a_raw_code_becomes_the_right_answer_and_reason(raw, code, reason):
    dom = classify_dominant(raw, NASA_QUALITY)
    assert (dom.code, dom.raw_code, dom.reason) == (code, raw, reason)


def test_the_two_absences_are_never_the_same_answer():
    """If a future edit collapses 'anonymous' into 'no_coverage' the blank cell
    comes back and the user cannot tell non-forest from unmeasured."""
    assert classify_dominant(0, NASA_QUALITY).reason == DOMINANT_ANONYMOUS
    assert classify_dominant(None, NASA_QUALITY).reason == DOMINANT_NO_COVERAGE
    assert DOMINANT_ANONYMOUS != DOMINANT_NO_COVERAGE
    assert DOMINANT_FAILED != DOMINANT_NO_COVERAGE
    assert DOMINANT_NO_GEOMETRY != DOMINANT_FAILED


def test_a_grouped_code_is_reported_as_its_group():
    """Unchanged from before RS-2.14: a compartment dominated by ESA 20 belongs
    to the same reported class as one dominated by 10."""
    spec = type(NASA_QUALITY)(
        **{**NASA_QUALITY.__dict__, "group_codes": {20: 10}, "anonymous_codes": ()}
    )
    assert classify_dominant(20, spec).code == 10


# ---------------------------------------------------------------------------
# the raw code reaches the database, and 0 survives the trip
# ---------------------------------------------------------------------------


def test_a_zero_raw_code_is_not_lost_on_the_way_to_the_column():
    """`req.get` returning 0 must not be mistaken for 'absent'. The value is the
    whole point of the column, so `_dominant_class` must hand back a real 0."""
    assert svc._dominant_class({"dominant_nasa_code": 0}, "dominant_nasa_code") == 0
    assert svc._dominant_class({}, "dominant_nasa_code") is None


def test_the_raw_code_column_exists_and_is_nullable():
    cols = ForestBlock.__table__.columns
    assert "dominant_nasa_code" in cols
    assert cols["dominant_nasa_code"].nullable


def test_the_preview_key_and_the_column_are_the_same_spelling():
    """The preview emits `dominant_nasa_code` and the column is named the same,
    so the RS-2.10 reader finds it without translation -- and both RS-2.10 guards
    (the AST one and the column-coverage one) stay satisfied."""
    assert svc._PREVIEW_CLASS_KEYS["dominant_nasa_code"] == "dominant_nasa_code"


# ---------------------------------------------------------------------------
# end-to-end against a real PostGIS raster (the sibling module's proven fixture)
# ---------------------------------------------------------------------------


def test_a_forest_class_survives_the_real_query(db, nasa_raster):  # noqa: F811
    """Borrowed fixture from test_auto_block_class_passthrough.py so the raster is
    built the way that module's green tests build it. Guards against the pure
    table drifting away from what the SQL actually returns."""
    from app.services.raster_class_vectorize import dominant_class

    dom = dominant_class(BOX_CLASS_3, db, NASA_QUALITY)
    assert dom.reason == DOMINANT_OK
    assert dom.code == 3
    assert dom.raw_code == 3
