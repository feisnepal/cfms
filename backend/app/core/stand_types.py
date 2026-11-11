"""
Stand Type Enum — Replaces 30+ Raw SQL Strings
===============================================

Previously 'Pole', 'Tree', 'Regeneration', etc. were hardcoded in:
  - api/field_inventory.py
  - field_inventory_mgmt_data.py
  - field_inventory_dfo_export.py
  - field_inventory_service.py
  - excel_validator.py
  - diameter_classifier.py

Usage in Python:
    from app.core.stand_types import StandType
    stand = StandType.POLE
    sql_value = stand.sql_value        # 'Pole'
    np_label = stand.label_np          # 'खम्बा'

Usage in SQLAlchemy / raw SQL:
    CASE WHEN stand_type = :pole THEN ... END
    # bind parameter: {"pole": StandType.POLE.sql_value}
"""

from enum import Enum


class StandType(str, Enum):
    """Forest stand / size class enumeration."""

    REGENERATION = "Regeneration"
    SAPLING = "Sapling"
    POLE = "Pole"
    TREE = "Tree"

    @property
    def sql_value(self) -> str:
        """Value used in database columns and raw SQL."""
        return self.value

    @property
    def label_np(self) -> str:
        """Nepali label for UI display."""
        return _NP_LABELS[self]

    @property
    def label_en(self) -> str:
        """English label (same as value)."""
        return self.value

    @classmethod
    def from_string(cls, s: str) -> "StandType":
        """Case-insensitive lookup. Raises ValueError if unknown."""
        try:
            return cls(s.title())
        except ValueError:
            raise ValueError(f"Unknown stand type: {s!r}. Expected: {list(cls)}")

    @classmethod
    def all_sql_values(cls) -> list[str]:
        """All values for SQL IN (...) clauses."""
        return [m.sql_value for m in cls]


_NP_LABELS: dict[StandType, str] = {
    StandType.REGENERATION: "नयाँ उमार",
    StandType.SAPLING: "बिरुवा",
    StandType.POLE: "खम्बा",
    StandType.TREE: "रूख",
}


# ── Remark Types (for tree marking) ──────────────────────────

class RemarkType(str, Enum):
    """Tree remark / marking classification."""

    MOTHER_TREE = "Mother Tree"
    FELLING_TREE = "Felling Tree"
    SEEDLING = "Seedling"
    PROTECTION_TREE = "Protection Tree"

    @property
    def sql_value(self) -> str:
        return self.value

    @property
    def label_np(self) -> str:
        return _REMARK_NP_LABELS[self]


_REMARK_NP_LABELS: dict[RemarkType, str] = {
    RemarkType.MOTHER_TREE: "आमा रूख",
    RemarkType.FELLING_TREE: "कटान रूख",
    RemarkType.SEEDLING: "बिरुवा",
    RemarkType.PROTECTION_TREE: "संरक्षण रूख",
}
