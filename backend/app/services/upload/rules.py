"""One table of numeric limits for hand-typed inventory data (VALIDATION_TRACKER.md, step B).

The limits used to live in four places that disagreed or did not exist: the DBH classes in ``dbh_class_systems``, numbers typed by hand into the
tree-model Excel export, the unit checks, and nothing at all for heights and counts in the Python validator. Here each measurement has ONE rule:

* **hard** limits: impossible or outside the class a column belongs to -> an error, the file is not accepted until it is corrected;
* **soft** limits: possible but unusual -> a warning that asks the user to confirm, never a refusal.

The Excel templates (step D) are generated from this table, so what Excel stops at and what the server refuses are the same numbers.
DBH class bounds are NOT copied: ``hard_from_class`` reads them from the ``validation`` system of :class:`DbhClassRegistry` (the admin-editable table).

Owner decisions (2026-10-13): pole / tree DBH are strict; Nepal's trees do not exceed 100 cm, so a tree above that is a soft flag and 200 cm is the hard stop;
DBH and height accept decimals. Height and count limits below start from the numbers the Excel export already enforced for its users; their hard
ceilings are mine (physically impossible values) and are open to the owner's correction.

Pure apart from the class lookup: no database access.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import pandas as pd

STANDS = ("regeneration", "sapling", "pole", "tree")
_HARD_CEILING_HEIGHT_M = 70.0  # no tree on earth stands taller; a value above this is a typing error whatever the species
_HARD_CEILING_COUNT = 1000  # stems in one small circular plot: more than this is a typing error


@dataclass(frozen=True)
class NumberRule:
    key: str  # the validator's column key: 'pole_dbh', 'tree_height', 'regen_count' ...
    stand: str  # regeneration | sapling | pole | tree
    measure: str  # dbh | height | count
    unit: str  # cm | m | count
    integer: bool = False
    hard_min: Optional[float] = None
    hard_max: Optional[float] = None
    soft_min: Optional[float] = None
    soft_max: Optional[float] = None
    hard_from_class: bool = False  # take hard_min / hard_max from the DBH class definition
    hard_max_exclusive: bool = False  # a class is half-open, [lower, upper): a stem of exactly 30.0 cm is a tree, not a pole

    def hard_bounds(self) -> Tuple[Optional[float], Optional[float]]:
        if not self.hard_from_class:
            return self.hard_min, self.hard_max
        from app.core.dbh_classifier import DbhClassRegistry

        for c in DbhClassRegistry.get_system("validation"):
            if c.key == self.stand:
                return float(c.lower), float(c.upper) if c.upper is not None else 999.0
        return self.hard_min, self.hard_max


RULES: Dict[str, NumberRule] = {r.key: r for r in (
    # DBH: the class a column belongs to is the hard range (a pole of 50 cm is a tree, not a pole)
    NumberRule("regen_dbh", "regeneration", "dbh", "cm", hard_from_class=True, hard_max_exclusive=True),
    NumberRule("sapling_dbh", "sapling", "dbh", "cm", hard_from_class=True, hard_max_exclusive=True),
    NumberRule("pole_dbh", "pole", "dbh", "cm", hard_from_class=True, hard_max_exclusive=True),
    NumberRule("tree_dbh", "tree", "dbh", "cm", hard_from_class=True, soft_max=100.0),  # 200 cm is the safety hard stop and is allowed
    # heights: usual ranges are what the Excel export enforced; above the ceiling is impossible
    NumberRule("pole_height", "pole", "height", "m", hard_min=0.5, hard_max=_HARD_CEILING_HEIGHT_M, soft_min=5.0, soft_max=25.0),
    NumberRule("tree_height", "tree", "height", "m", hard_min=0.5, hard_max=_HARD_CEILING_HEIGHT_M, soft_min=7.0, soft_max=50.0),
    # counts in the small regeneration / sapling plots: whole numbers, at least 1
    NumberRule("regen_count", "regeneration", "count", "count", integer=True, hard_min=1, hard_max=_HARD_CEILING_COUNT, soft_max=15),
    NumberRule("sapling_count", "sapling", "count", "count", integer=True, hard_min=1, hard_max=_HARD_CEILING_COUNT, soft_max=10),
)}


# Stem mapping records individual stems, not stand classes (owner, 2026-10-13): one continuous range, whatever the size. A stem can measure from 1 to 200 cm;
# above 100 cm is unusual in Nepal and the user is asked to confirm it. Under 1 cm cannot be measured at breast height and above 200 cm is refused.
STEM_DBH = NumberRule("stem_dbh", "stem", "dbh", "cm", hard_min=1.0, hard_max=200.0, soft_max=100.0)


# Stem mapping heights: a stem shorter than breast height (1.3 m) cannot have a diameter measured, nothing in Nepal exceeds 50 m, and above 45 m is very tall.
STEM_HEIGHT = NumberRule("stem_height", "stem", "height", "m", hard_min=1.3, hard_max=50.0, soft_max=45.0)


@dataclass
class Evaluation:
    rule: NumberRule
    total: int  # numbers checked
    hard_rows: List[int]  # spreadsheet rows (row 1 is the header) outside the hard limits
    soft_rows: List[int]  # inside the hard limits but outside the soft ones
    not_whole_rows: List[int]  # a count with a fraction
    hard_min: Optional[float]
    hard_max: Optional[float]
    hard_max_exclusive: bool = False


def evaluate(rule: NumberRule, values: pd.Series) -> Evaluation:
    """Judge a column against its rule. Text and blanks are skipped here (the validator names them elsewhere); rows are spreadsheet rows."""
    v = pd.to_numeric(values, errors="coerce").dropna()
    lo, hi = rule.hard_bounds()
    hard = pd.Series(False, index=v.index)
    if lo is not None:
        hard |= v < lo
    if hi is not None:
        hard |= (v >= hi) if rule.hard_max_exclusive else (v > hi)
    soft = pd.Series(False, index=v.index)
    if rule.soft_min is not None:
        soft |= v < rule.soft_min
    if rule.soft_max is not None:
        soft |= v > rule.soft_max
    soft &= ~hard
    fractional = (v != v.round()) & ~hard if rule.integer else pd.Series(False, index=v.index)
    rows = lambda mask: [int(i) + 2 for i in v.index[mask]]  # noqa: E731 -- a one-line helper
    return Evaluation(rule, len(v), rows(hard), rows(soft & ~fractional), rows(fractional), lo, hi, rule.hard_max_exclusive)


def species_limits_sql() -> str:
    """The query that gives the per-species maximums used as a further soft limit (a species cannot exceed what is known of it)."""
    return (
        "SELECT lower(scientific_name) AS name, max_dbh_cm, max_height_m "
        "FROM tree_species_coefficients WHERE is_active = TRUE AND lower(scientific_name) = ANY(:names)"
    )


def range_text(rule: NumberRule) -> str:
    """The hard range in words that say what the edges mean, e.g. ``10 to under 30 cm`` or ``30 to 200 cm``."""
    lo, hi = rule.hard_bounds()
    unit = {"cm": " cm", "m": " m", "count": ""}[rule.unit]
    return f"{lo:g} to {'under ' if rule.hard_max_exclusive else ''}{hi:g}{unit}"


def stand_for_dbh(dbh: float) -> str:
    """The stand a DBH belongs to, from the ``validation`` DBH classes: regeneration | sapling | pole | tree.

    The classes are half-open ``[lower, upper)``, so 4.0 is a sapling, 10.0 a pole and 30.0 a tree. A value below the lowest class bound is still regeneration
    (a synthetic or measured seedling under 1 cm is not a different stand), and one above the tree class is a tree.
    """
    from app.core.dbh_classifier import DbhClassRegistry

    classes = {c.key: c for c in DbhClassRegistry.get_system("validation")}
    for stand in ("regeneration", "sapling", "pole", "tree"):
        c = classes.get(stand)
        if c is not None and c.contains(dbh):
            return stand
    return "regeneration" if dbh < classes["regeneration"].lower else "tree"
