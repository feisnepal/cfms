"""The forest / regeneration condition rule (Forest Regulation 2075/2079) as one pure function.

Used by the field-inventory service when it assesses a stand, and by the roll-up that gives a DIVIDED parent unit the condition of
its sub-units' totals -- so the two can never apply different rules.

A) Regeneration condition: seedlings (regeneration, 0-4 cm) AND saplings (4-10 cm) per hectare, both limits must be met.
B) Forest condition: growing stock band x regeneration condition (3 x 3 matrix).
"""
from __future__ import annotations

from typing import Tuple

from . import constants as c


def assess_conditions(regen_per_ha: float, sapling_per_ha: float, growing_stock_m3_per_ha: float) -> Tuple[str, str]:
    """``(regeneration_condition, forest_condition)``, each ``"Good"`` | ``"Moderate"`` | ``"Weak"``."""
    regen, sap, gs = float(regen_per_ha or 0), float(sapling_per_ha or 0), float(growing_stock_m3_per_ha or 0)

    if regen >= c.REGEN_GOOD_PER_HA and sap >= c.SAPLING_GOOD_PER_HA:
        rc = "Good"
    elif regen >= c.REGEN_MODERATE_PER_HA and sap >= c.SAPLING_MODERATE_PER_HA:
        rc = "Moderate"
    else:
        rc = "Weak"

    if gs > c.GS_GOOD_M3_PER_HA:
        fc = {"Good": "Good", "Moderate": "Good", "Weak": "Moderate"}[rc]
    elif gs >= c.GS_MODERATE_M3_PER_HA:
        fc = {"Good": "Good", "Moderate": "Moderate", "Weak": "Weak"}[rc]
    else:
        fc = {"Good": "Moderate", "Moderate": "Weak", "Weak": "Weak"}[rc]
    return rc, fc
