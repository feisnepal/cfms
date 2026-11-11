"""What a person can be asked to decide about a forest, and the choices allowed.

Definitions live here (not in the database) so adding a question never needs a migration; only the answers are stored
(``models/forest_decision.py``). Titles and explanations are translation keys the frontend renders
(``forestSummary.decisions.<key>.title`` / ``.text``), so an admin can reword them on the translation page.

Two decisions are forest-wide; ``orientation`` is asked once per block and its open/answered state is derived from the
block's own columns (the stored row is only the audit record), so a later attribute-table edit cannot leave a stale answer.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple

from app.services.forest_units.write import MANAGEMENT_ORIENTATIONS

LANDSLIDE_METHOD = "landslide_method"
ORIENTATION = "orientation"
HOUSEHOLD_PLACEMENT = "household_placement"

ACCEPT_SUGGESTED = "accept_suggested"
CUSTOM = "custom"


@dataclass(frozen=True)
class DecisionDef:
    key: str
    choices: Tuple[str, ...]
    per_block: bool
    who: str  # who is expected to decide (a translation key suffix, for display only)
    step: int  # the workflow step the decision belongs to


REGISTRY: dict[str, DecisionDef] = {
    LANDSLIDE_METHOD: DecisionDef(LANDSLIDE_METHOD, ("relative", "needs_calibration"), False, "committee_dfo", 11),
    ORIENTATION: DecisionDef(ORIENTATION, (ACCEPT_SUGGESTED, CUSTOM), True, "committee", 12),
    HOUSEHOLD_PLACEMENT: DecisionDef(HOUSEHOLD_PLACEMENT, ("building_footprints",), False, "facilitator", 11),
}


class DecisionError(ValueError):
    """A request that names an unknown question, an unknown choice, or a missing/invalid scope or value."""


def validate(key: str, choice: str, scope: Optional[str], value: Optional[str]) -> DecisionDef:
    definition = REGISTRY.get(key)
    if definition is None:
        raise DecisionError(f"Unknown decision: {key}")
    if choice not in definition.choices:
        raise DecisionError(f"Unknown choice '{choice}' for decision '{key}'")
    if definition.per_block and not scope:
        raise DecisionError(f"Decision '{key}' needs a block (scope)")
    if not definition.per_block and scope:
        raise DecisionError(f"Decision '{key}' is forest-wide and takes no scope")
    if key == ORIENTATION and choice == CUSTOM and value not in MANAGEMENT_ORIENTATIONS:
        raise DecisionError(f"A custom orientation must be one of {', '.join(MANAGEMENT_ORIENTATIONS)}")
    return definition
