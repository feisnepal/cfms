"""0% per-unit intensity means "do not sample this unit" (owner, 2026-10-03)."""
from decimal import Decimal

import pytest

from app.schemas.sampling import BlockOverride, BlockSamplingInfo
from app.services.sampling import (
    _refuse_if_every_unit_excluded,
    _user_excluded_block_info,
)


def _info(excluded: bool) -> BlockSamplingInfo:
    if excluded:
        return _user_excluded_block_info(1, "B1", 10.0, "production", 2.0, 500)
    return BlockSamplingInfo(
        block_number=2, block_name="B2", block_area_hectares=Decimal("5"),
        samples_generated=5, minimum_enforced=True,
        actual_intensity_percent=Decimal("2"),
    )


def test_override_schema_accepts_zero_but_not_negative():
    assert BlockOverride(sampling_intensity_percent=0).sampling_intensity_percent == 0
    with pytest.raises(ValueError):
        BlockOverride(sampling_intensity_percent=-1)


def test_excluded_unit_info_has_no_plots_and_is_flagged():
    i = _info(True)
    assert i.user_excluded is True
    assert i.samples_generated == 0
    assert i.actual_intensity_percent == 0
    assert i.minimum_enforced is False


def test_normal_unit_is_not_flagged():
    assert _info(False).user_excluded is False


def test_refuses_only_when_every_unit_excluded():
    with pytest.raises(ValueError):
        _refuse_if_every_unit_excluded([_info(True), _info(True)])
    _refuse_if_every_unit_excluded([_info(True), _info(False)])  # no raise
    _refuse_if_every_unit_excluded([])  # no raise
