"""Tests for forest dimension mode detection."""

from uuid import uuid4

import pytest

from tests._purge import purge_calculations

from app.utils.forest_dimension import (
    ForestDimension,
    get_forest_dimension,
    NarrationContext,
    dimension_label,
    dimension_label_plural,
    dimension_label_lower,
    dimension_label_plural_lower,
    dimension_label_for_level,
    dimension_label_for_level_plural,
    dimension_name_header_np,
    dimension_name_header_np_plural,
    dimension_name_header_en,
    dimension_abbreviation,
)


def _forest(db, result_data=None, unit_rows=()):
    """A scratch forest in the test database. ``unit_rows`` = ((name, is_compartment), ...)."""
    from geoalchemy2.shape import from_shape
    from shapely.geometry import box

    from app.models.calculation import Calculation
    from app.models.forest_block import ForestBlock
    from app.models.user import User, UserRole

    user = User(
        email=f"dim-{uuid4().hex[:8]}@test.com",
        full_name="Dimension test",
        role=UserRole.USER,
        hashed_password="not-a-real-hash",
    )
    db.add(user)
    db.flush()
    calc = Calculation(
        id=str(uuid4()),
        user_id=user.id,
        uploaded_filename="dim.csv",
        is_draft=False,
        result_data=result_data,
    )
    db.add(calc)
    db.flush()
    for i, (name, is_comp) in enumerate(unit_rows):
        db.add(
            ForestBlock(
                calculation_id=calc.id,
                name=name,
                block_name=name,
                geometry=from_shape(box(84.0 + i / 100, 27.0, 84.01 + i / 100, 27.01), srid=4326),
                area_hectares=100.0,
                index=i,
                is_compartment=is_comp,
                division_level=1,
            )
        )
    db.commit()
    return calc.id


@pytest.fixture()
def dim_forests(db):
    made = []

    def make(**kw):
        cid = _forest(db, **kw)
        made.append(cid)
        return cid

    yield make
    purge_calculations(db, made)


class TestGetForestDimension:
    """Mode detection, against the real database (it delegates to forest_units.mode.forest_stream)."""

    def test_detects_upload_compartments_from_result_data(self, db, dim_forests):
        cid = dim_forests(result_data={"compartments": [{"name": "C1", "geometry": "..."}]})
        assert get_forest_dimension(db, cid) == ForestDimension.COMPARTMENT

    def test_detects_split_compartments_from_fb_table(self, db, dim_forests):
        cid = dim_forests(result_data={}, unit_rows=(("C1", True),))
        assert get_forest_dimension(db, cid) == ForestDimension.COMPARTMENT

    def test_block_rows_are_a_block_forest(self, db, dim_forests):
        cid = dim_forests(result_data={}, unit_rows=(("B1", False),))
        assert get_forest_dimension(db, cid) == ForestDimension.BLOCK

    def test_defaults_to_block_when_no_compartments(self, db, dim_forests):
        cid = dim_forests(result_data={})
        assert get_forest_dimension(db, cid) == ForestDimension.BLOCK

    def test_detects_polygon_type_flag(self, db, dim_forests):
        cid = dim_forests(result_data={"polygon_type": "compartment"})
        assert get_forest_dimension(db, cid) == ForestDimension.COMPARTMENT

    def test_no_calculation_found_defaults_to_block(self, db):
        assert get_forest_dimension(db, uuid4()) == ForestDimension.BLOCK

    def test_result_data_is_none_defaults_to_block(self, db, dim_forests):
        cid = dim_forests(result_data=None)
        assert get_forest_dimension(db, cid) == ForestDimension.BLOCK

    def test_unit_rows_beat_a_stale_result_data_snapshot(self, db, dim_forests):
        """The rows are authoritative: a stale ``compartments`` snapshot on a block forest does not win."""
        cid = dim_forests(
            result_data={"compartments": [{"name": "old"}]}, unit_rows=(("B1", False),)
        )
        assert get_forest_dimension(db, cid) == ForestDimension.BLOCK


class TestEnglishLabels:
    def test_block_labels(self):
        assert dimension_label(ForestDimension.BLOCK) == "Block"
        assert dimension_label_plural(ForestDimension.BLOCK) == "Blocks"
        assert dimension_label_lower(ForestDimension.BLOCK) == "block"
        assert dimension_label_plural_lower(ForestDimension.BLOCK) == "blocks"

    def test_compartment_labels(self):
        assert dimension_label(ForestDimension.COMPARTMENT) == "Compartment"
        assert dimension_label_plural(ForestDimension.COMPARTMENT) == "Compartments"
        assert dimension_label_lower(ForestDimension.COMPARTMENT) == "compartment"
        assert dimension_label_plural_lower(ForestDimension.COMPARTMENT) == "compartments"

    def test_column_headers(self):
        assert dimension_name_header_en(ForestDimension.BLOCK) == "Block Name"
        assert dimension_name_header_en(ForestDimension.COMPARTMENT) == "Compartment Name"

    def test_abbreviations(self):
        assert dimension_abbreviation(ForestDimension.BLOCK) == "Blk"
        assert dimension_abbreviation(ForestDimension.COMPARTMENT) == "Cmp"


class TestNepaliLabels:
    def test_block_nepali(self):
        assert dimension_label(ForestDimension.BLOCK, nepali=True) == "ब्लक"
        assert dimension_label_plural(ForestDimension.BLOCK, nepali=True) == "ब्लकहरू"
        assert dimension_name_header_np(ForestDimension.BLOCK) == "ब्लकको नाम"
        assert dimension_name_header_np_plural(ForestDimension.BLOCK) == "ब्लकको नामहरू"

    def test_compartment_nepali(self):
        assert dimension_label(ForestDimension.COMPARTMENT, nepali=True) == "कम्पार्टमेन्ट"
        assert dimension_label_plural(ForestDimension.COMPARTMENT, nepali=True) == "कम्पार्टमेन्टहरू"
        assert dimension_name_header_np(ForestDimension.COMPARTMENT) == "कम्पार्टमेन्टको नाम"
        assert dimension_name_header_np_plural(ForestDimension.COMPARTMENT) == "कम्पार्टमेन्टको नामहरू"


class TestLevelSpecificLabels:
    def test_block_mode_level_labels(self):
        assert dimension_label_for_level(ForestDimension.BLOCK, 0) == "Block"
        assert dimension_label_for_level(ForestDimension.BLOCK, 0, True) == "ब्लक"
        assert dimension_label_for_level(ForestDimension.BLOCK, 1) == "Block"
        # FS-4a.1: a sub-block now gets its own term -- block mode used to read "Block"
        # at every depth (the compartment side already branched here; block did not).
        assert dimension_label_for_level(ForestDimension.BLOCK, 2) == "Sub-Block"
        assert dimension_label_for_level(ForestDimension.BLOCK, 999) == "Sub-Block"
        assert dimension_label_for_level(ForestDimension.BLOCK, 2, True) == "उप-ब्लक"

    def test_compartment_mode_level_labels(self):
        assert dimension_label_for_level(ForestDimension.COMPARTMENT, 1) == "Compartment"
        assert dimension_label_for_level(ForestDimension.COMPARTMENT, 2) == "Sub-Compartment"
        assert dimension_label_for_level(ForestDimension.COMPARTMENT, 3) == "Sub-Compartment"
        assert dimension_label_for_level(ForestDimension.COMPARTMENT, 1, True) == "कम्पार्टमेन्ट"
        assert dimension_label_for_level(ForestDimension.COMPARTMENT, 2, True) == "उप-कम्पार्टमेन्ट"

    def test_level_plural_labels(self):
        assert dimension_label_for_level_plural(ForestDimension.BLOCK, 0) == "Blocks"
        assert dimension_label_for_level_plural(ForestDimension.BLOCK, 2) == "Sub-Blocks"
        assert dimension_label_for_level_plural(ForestDimension.COMPARTMENT, 1) == "Compartments"
        assert dimension_label_for_level_plural(ForestDimension.COMPARTMENT, 2) == "Sub-Compartments"
        assert dimension_label_for_level_plural(ForestDimension.COMPARTMENT, 2, True) == "उप-कम्पार्टमेन्टहरू"


class TestNarrationContext:
    def test_compartment_context(self):
        ctx = NarrationContext(dimension=ForestDimension.COMPARTMENT)
        assert ctx.unit_label_np == "कम्पार्टमेन्ट"
        assert ctx.unit_label_en == "Compartment"
        assert ctx.unit_label_plural_np == "कम्पार्टमेन्टहरू"
        assert ctx.unit_name_header_np == "कम्पार्टमेन्टको नाम"

    def test_block_context(self):
        ctx = NarrationContext(dimension=ForestDimension.BLOCK)
        assert ctx.unit_label_np == "ब्लक"
        assert ctx.unit_label_en == "Block"
        assert ctx.unit_label_plural_np == "ब्लकहरू"
        assert ctx.unit_name_header_np == "ब्लकको नाम"

    def test_level_aware_methods_compartment(self):
        ctx = NarrationContext(dimension=ForestDimension.COMPARTMENT)
        assert ctx.unit_label_np_for_level(1) == "कम्पार्टमेन्ट"
        assert ctx.unit_label_np_for_level(2) == "उप-कम्पार्टमेन्ट"
        assert ctx.unit_label_en_for_level(1) == "Compartment"
        assert ctx.unit_label_en_for_level(3) == "Sub-Compartment"
        assert ctx.unit_label_plural_np_for_level(2) == "उप-कम्पार्टमेन्टहरू"

    def test_level_aware_methods_block(self):
        ctx = NarrationContext(dimension=ForestDimension.BLOCK)
        assert ctx.unit_label_np_for_level(1) == "ब्लक"
        # FS-4a.1: level 2 is a sub-block, matching the compartment side's own branch.
        assert ctx.unit_label_en_for_level(2) == "Sub-Block"
        assert ctx.unit_label_plural_np_for_level(0) == "ब्लकहरू"
