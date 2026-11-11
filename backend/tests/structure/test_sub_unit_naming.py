"""Sub-unit naming pattern (FS-4a.2) - ``app.core.naming_strategies``."""

from __future__ import annotations

from app.core.naming_strategies import sub_unit_naming_pattern, sub_unit_serial


def test_sub_compartment_pattern_unchanged():
    """The compartment side's real default, already live in
    compartment_divide_service.py, must not change under this refactor."""
    assert sub_unit_naming_pattern(compartment=True) == "{parent_name}-SC{index}"


def test_sub_block_pattern_is_new():
    assert sub_unit_naming_pattern(compartment=False) == "{parent_name}-SB{index}"


def test_serial_renders_the_pattern():
    assert sub_unit_serial(compartment=False, parent_name="B1", index=1) == "B1-SB1"
    assert sub_unit_serial(compartment=True, parent_name="C1", index=2) == "C1-SC2"
