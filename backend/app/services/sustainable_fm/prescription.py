"""Resolve the दिगो वन व्यवस्थापन प्रिस्क्रिप्सन card for a block (P3).

``SUSTAINABLE_FOREST_MANAGEMENT_PLAN.md`` §5 P3.

For an ``effective_type_no`` + a regeneration branch (क / ख, chosen per felling
series), read the ``sfm_forest_type_prescriptions`` row and build a flat card:
silvicultural system, felling / rotation cycle, regeneration method + period,
mother-tree target, and the yield rule. Pure lookup — no maths (that is
``yield_regulation``), no DB beyond loading the 14 rows once.
"""

from __future__ import annotations

from typing import Any, Optional

from sqlalchemy.orm import Session

from app.models.sfm_prescription import SfmForestTypePrescription
from app.services.sustainable_fm.sfm_config import SfmParams


def load_prescriptions(db: Session) -> dict[int, SfmForestTypePrescription]:
    """The 14 rows, keyed by ``type_no``."""
    return {
        row.type_no: row
        for row in db.query(SfmForestTypePrescription)
        .filter(SfmForestTypePrescription.is_active.is_(True))
        .all()
    }


def _branch_of(row: SfmForestTypePrescription, branch: str) -> dict[str, Any]:
    branches = row.branches or {}
    return (
        branches.get(branch)
        or branches.get("default")
        or next(iter(branches.values()), {})
    )


def pick_branch(group_blocks: list[dict[str, Any]], params: SfmParams) -> str:
    """``"adequate"`` iff every block whose regeneration state is *known* is
    adequate **and** at least 60 % of the group area carries an inventory.
    Ties, unknowns and prior-only groups → ``"inadequate"`` (conservative — the
    guideline's (ख) branch is the lower-percentage / shelterwood path).
    """
    total = sum(b.get("area_ha", 0.0) for b in group_blocks) or 1.0
    inventoried = sum(
        b.get("area_ha", 0.0)
        for b in group_blocks
        if (b.get("inputs") or {}).get("source") in ("stem_mapping", "field_inventory")
    )
    if inventoried / total < 0.6:
        return "inadequate"
    states = [(b.get("inputs") or {}).get("regen_adequate") for b in group_blocks]
    known = [s for s in states if s is not None]
    if known and all(known):
        return "adequate"
    return "inadequate"


def build_card(
    row: Optional[SfmForestTypePrescription],
    branch: str,
    *,
    gs_ge40_m3_per_ha: Optional[float],
    pct: Optional[float],
    params: SfmParams,
) -> dict[str, Any]:
    """Flatten the row's branch into the card the SFM tab + the OP section
    render. ``row`` may be ``None`` (a type_no with no seed row) — then a stub."""
    if row is None:
        return {
            "type_no": None,
            "branch": branch,
            "system_ne": "—",
            "system_en": "—",
            "note_ne": "यस वन प्रकारको प्रिस्क्रिप्सन उपलब्ध छैन।",
            "note_en": "No prescription row for this forest type.",
        }
    b = _branch_of(row, branch)
    yr = b.get("yield_rules") or {}
    mother = b.get("mother_trees_per_ha")
    if mother is None and (b.get("method") == "shelterwood_periodic_block"):
        mother = [params.mother_tree_target_min, params.mother_tree_target_max]
    return {
        "type_no": row.type_no,
        "type_name_ne": row.name_ne,
        "type_name_en": row.name_en,
        "branch": branch,
        "method": b.get("method"),
        "orientation": row.orientation,
        "system_ne": b.get("system_ne", "—"),
        "system_en": b.get("system_en", "—"),
        "felling_cycle_years": b.get("felling_cycle_years"),
        "regeneration_period_years": b.get("regeneration_period_years"),
        "rotation_years": b.get("rotation_years"),
        "regen_method_ne": b.get("regen_method_ne"),
        "regen_method_en": b.get("regen_method_en"),
        "mother_tree_target": mother,
        "yield_basis": yr.get("basis"),
        "yield_pct": pct,
        "gs_ge40_m3_per_ha": (
            round(gs_ge40_m3_per_ha, 2) if gs_ge40_m3_per_ha is not None else None
        ),
        "yield_note_ne": yr.get("note_ne", ""),
        "yield_note_en": yr.get("note_en", ""),
        "target_stems_per_ha": yr.get("target_stems_per_ha"),
        "note_ne": b.get("note_ne") or (row.notes_ne or ""),
        "note_en": b.get("note_en") or (row.notes_en or ""),
    }


__all__ = ["load_prescriptions", "pick_branch", "build_card"]
