"""Branch-aware unit labels (FS-4a.1) - ``app.services.forest_units.labels``."""

from __future__ import annotations

from app.services.forest_units.labels import (
    unit_abbreviation,
    unit_label,
    unit_label_plural,
    unit_name_header,
)
from app.services.forest_units.model import DEPTH_SUB, DEPTH_TOP_BLOCK, DEPTH_TOP_COMPARTMENT, Branch


def test_block_branch_labels():
    assert unit_label(Branch.BLOCK, DEPTH_TOP_BLOCK) == "Block"
    assert unit_label(Branch.BLOCK, DEPTH_SUB) == "Sub-Block"
    assert unit_label(Branch.BLOCK, DEPTH_TOP_BLOCK, nepali=True) == "ब्लक"
    assert unit_label(Branch.BLOCK, DEPTH_SUB, nepali=True) == "उप-ब्लक"


def test_compartment_branch_labels():
    assert unit_label(Branch.COMPARTMENT, DEPTH_TOP_COMPARTMENT) == "Compartment"
    assert unit_label(Branch.COMPARTMENT, DEPTH_SUB) == "Sub-Compartment"
    assert unit_label(Branch.COMPARTMENT, DEPTH_TOP_COMPARTMENT, nepali=True) == "कम्पार्टमेन्ट"
    assert unit_label(Branch.COMPARTMENT, DEPTH_SUB, nepali=True) == "उप-कम्पार्टमेन्ट"


def test_deep_nesting_stays_sub():
    """A sub-sub-unit (depth 3+) is still 'Sub-X', not a third tier of terms - the
    structure rule only recognises two levels below the boundary (D5)."""
    assert unit_label(Branch.BLOCK, 5) == "Sub-Block"
    assert unit_label(Branch.COMPARTMENT, 5) == "Sub-Compartment"


def test_plurals():
    assert unit_label_plural(Branch.BLOCK, DEPTH_TOP_BLOCK) == "Blocks"
    assert unit_label_plural(Branch.BLOCK, DEPTH_SUB) == "Sub-Blocks"
    assert unit_label_plural(Branch.COMPARTMENT, DEPTH_SUB, nepali=True) == "उप-कम्पार्टमेन्टहरू"


def test_name_headers():
    assert unit_name_header(Branch.BLOCK, DEPTH_TOP_BLOCK) == "Block Name"
    assert unit_name_header(Branch.BLOCK, DEPTH_SUB) == "Sub-Block Name"
    assert unit_name_header(Branch.BLOCK, DEPTH_SUB, nepali=True) == "उप-ब्लकको नाम"
    assert unit_name_header(Branch.COMPARTMENT, DEPTH_TOP_COMPARTMENT, nepali=True) == "कम्पार्टमेन्टको नाम"


def test_abbreviations():
    assert unit_abbreviation(Branch.BLOCK, DEPTH_TOP_BLOCK) == "Blk"
    assert unit_abbreviation(Branch.BLOCK, DEPTH_SUB) == "SBlk"
    assert unit_abbreviation(Branch.COMPARTMENT, DEPTH_TOP_COMPARTMENT) == "Cmp"
    assert unit_abbreviation(Branch.COMPARTMENT, DEPTH_SUB) == "SCmp"
