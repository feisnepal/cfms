"""Management orientation → working-circle proposal (P3).

``SUSTAINABLE_FOREST_MANAGEMENT_PLAN.md`` §4.8 / §5 P3.

The forest type's orientation (Production / Conservation / Protection /
Restoration / Multi-use), upgraded to Conservation by slope in two tiers
(owner decision, 2026-09-14 — "always treat high slope as more erosion
sensitive unless the user overrides it"):

- **band 4 (> 45°), every type.** अनुसूची-१ names this trigger explicitly for
  four hill/conifer types (8, 9, 10, 13; corrected from "Protection" to
  "Conservation" 2026-09-12); it is now a general policy extending the same
  erosion-sensitivity logic to all 14 types. A type already Protection-
  oriented is never downgraded.
- **band 3 (31-45°), only types in** ``AMBIGUOUS_ORIENTATION_TYPES`` **(none,
  currently).** The mechanism exists for a type whose अनुसूची-१ objective
  cell reads as self-contradictory in the source scan and hasn't been
  resolved another way. सि.नं. 12 was the original candidate (Nepali text
  "erosion-sensitive, संरक्षणलाई प्राथमिकता" next to a mismatched
  "(Production Oriented)" tag) but is **resolved, not ambiguous**: the owner
  consulted the responsible official directly (2026-09-15), who confirmed
  सि.नं. 12 is Production Oriented, matching its own harvest table and the
  parenthetical tag. It now carries a plain, unconditional Production base
  like any other type (only the general band-4 rule above still applies to
  it) — do not re-add it here without an equally concrete resolution.

Either a true-Protection base orientation or a slope upgrade yields a
**proposal** to move the unit into the protection working circle — surfaced
with a bilingual justification, applied only on one click (P9 wires the
effect); the prescribed behaviour (salvage-only) is the same regardless of
which trigger fired (mirrored in ``yield_regulation.py``'s felling-series
exclusion). This changes only the **suggested** orientation the SFM pipeline
computes fresh each build — a block's persisted, user-editable
``management_orientation`` is untouched by this change and always wins once
a human has set it.

Every call also returns a plain-language, always-populated bilingual
``justification`` naming the सि.नं. reference this orientation came from —
whether or not a slope trigger or a working-circle proposal fired (owner
request, 2026-09-15, so a read-only UI column can explain a Production vs
Conservation split even when nothing was "overridden"). Pure.
"""

from __future__ import annotations

from typing import Any, Optional

from app.services.sustainable_fm.forest_type_classifier import (
    AMBIGUOUS_ORIENTATION_TYPES,
    SLOPE45_PROTECTION_TYPES,
)
from app.services.sustainable_fm.sfm_config import SfmParams

_PROTECTION = "Protection"
_CONSERVATION = "Conservation"

ORIENTATION_LABEL_NE = {
    "Production": "उत्पादनमुखी",
    "Conservation": "संरक्षणमुखी",
    "Protection": "संरक्षण",
    "Restoration": "पुनःस्थापनामुखी",
    "Multi-use": "बहुउपयोगी",
}


def _base_reason(type_no: int, base: str) -> tuple[str, str]:
    """Justification for a base orientation that no slope trigger touched."""
    if type_no in AMBIGUOUS_ORIENTATION_TYPES:
        return (
            f"सि.नं. {type_no} · अनुसूची-१ स्क्यानमा उद्देश्य अस्पष्ट; हाल {base} "
            f"(भिरालो ≥ ३१° भए Conservation हुन्छ)",
            f"type {type_no} · अनुसूची-१ objective is ambiguous in the source scan; "
            f"currently {base} (becomes Conservation at slope >= 31°)",
        )
    label_ne = ORIENTATION_LABEL_NE.get(base, base)
    return (
        f"सि.नं. {type_no} · अनुसूची-१ अनुसार {label_ne} वन प्रकार",
        f"type {type_no} · {base}-oriented per अनुसूची-१",
    )


def propose(
    type_no: int,
    zone: dict[str, Any],
    prescription_row,
    params: SfmParams,
) -> tuple[str, Optional[dict[str, Any]], dict[str, str]]:
    """Returns ``(orientation, working_circle_proposal | None, justification)``.

    ``justification`` is always ``{"justification_ne": ..., "justification_en": ...}``
    — unlike ``working_circle_proposal``, which is only populated when a move
    to the protection working circle is actually being proposed.
    """
    base = getattr(prescription_row, "orientation", None) or "Production"
    band = zone.get("slope_band")
    orientation = base
    reason_ne = ""
    reason_en = ""
    propose_working_circle = False

    if band == params.protection_slope_band and orientation != _PROTECTION:
        # >45° now reads as erosion-sensitive for every type, not only the
        # four (8/9/10/13) अनुसूची-१ names by number for this exact
        # threshold. The reason text says which case it is, honestly: a
        # guideline-named type vs a system-policy extension.
        orientation = _CONSERVATION
        propose_working_circle = True
        if type_no in SLOPE45_PROTECTION_TYPES:
            reason_ne = f"सि.नं. {type_no} · > ४५° भिरालो · भू-क्षय संवेदनशील"
            reason_en = f"type {type_no} · slope > 45° · erosion-sensitive"
        else:
            reason_ne = f"सि.नं. {type_no} · > ४५° भिरालो · भू-क्षय संवेदनशील (सामान्य नीति)"
            reason_en = (
                f"type {type_no} · slope > 45° · erosion-sensitive (general policy)"
            )
    elif (
        band == params.conservation_slope_band
        and type_no in AMBIGUOUS_ORIENTATION_TYPES
        and orientation != _PROTECTION
    ):
        # 31-45° resolves सि.नं. 12's self-contradictory objective toward
        # Conservation; no other type is affected at this threshold.
        orientation = _CONSERVATION
        propose_working_circle = True
        reason_ne = f"सि.नं. {type_no} · ३१-४५° भिरालो · अस्पष्ट उद्देश्यको समाधान"
        reason_en = (
            f"type {type_no} · slope 31-45° · resolves an ambiguous अनुसूची-१ objective"
        )
    elif base == _PROTECTION:
        propose_working_circle = True
        reason_ne = f"सि.नं. {type_no} · संरक्षणमुखी वन प्रकार"
        reason_en = f"type {type_no} · protection-oriented forest type"
    else:
        # No slope trigger fired and the base isn't Protection -- still name
        # the सि.नं. reference the orientation came from (D7 follow-up,
        # 2026-09-15): a plain Production/Conservation/Restoration/Multi-use
        # type deserves a visible reason too, not just the override cases.
        reason_ne, reason_en = _base_reason(type_no, base)

    justification = {
        "justification_ne": reason_ne,
        "justification_en": reason_en,
    }

    if propose_working_circle:
        return (
            orientation,
            {
                "target": "protection",
                "justification_ne": f"{reason_ne} → संरक्षण कार्य वृत्त",
                "justification_en": f"{reason_en} → protection working circle",
            },
            justification,
        )
    return orientation, None, justification


__all__ = ["propose", "ORIENTATION_LABEL_NE"]
