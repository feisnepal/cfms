"""Proposed corrections for values the rules refuse (VALIDATION_TRACKER.md, step E).

A pole recorded as 50 cm is refused. The system says which row it is, what class the value really belongs to, and PROPOSES a replacement: a random value
inside the usual range of the column's own class (owner, 2026-10-13). Safeguards agreed with the owner:

* nothing changes until the user applies the proposal (the report shows old -> proposed for every row);
* the draw is seeded from the row, the column and the old value, so the same file always gets the same proposal;
* the proposal stays inside the *usual* range, so it cannot create a new "unusual" flag;
* the server applies a correction only to a cell the rules already refuse - it can never be used to rewrite a valid measurement.

Pure: no database access.
"""
from __future__ import annotations

import random
from typing import Any, Dict, List, Optional

import pandas as pd

from .rules import RULES, NumberRule, evaluate, range_text

_STEP = 0.1  # field diameters and heights are recorded to a tenth


def usual_range(rule: NumberRule) -> Optional[tuple]:
    """The range a proposal is drawn from: the usual range if there is one, else the hard range (the upper edge of a class excluded)."""
    lo, hi = rule.hard_bounds()
    lo = rule.soft_min if rule.soft_min is not None else lo
    hi = rule.soft_max if rule.soft_max is not None else hi
    if lo is None or hi is None:
        return None
    if rule.hard_max_exclusive and rule.soft_max is None:
        hi = hi - _STEP
    return float(lo), float(hi)


def propose_value(rule: NumberRule, column: str, row: int, old: Any) -> Optional[float]:
    """A repeatable random value inside the column's usual range (None for a count, which is not a measurement to invent)."""
    if rule.measure == "count":
        return None
    rng = usual_range(rule)
    if rng is None:
        return None
    lo, hi = rng
    seed = random.Random(f"{column}|{row}|{old}")
    return round(seed.uniform(lo, hi) / _STEP) * _STEP if hi > lo else lo


def belongs_to(rule: NumberRule, value: float) -> Optional[str]:
    """The size class a DBH really belongs to (``'tree'`` for a pole of 50 cm), or None when it is not a DBH or fits no class."""
    if rule.measure != "dbh":
        return None
    from app.core.dbh_classifier import DbhClassRegistry

    for c in DbhClassRegistry.get_system("validation"):
        if c.contains(value):
            return c.key if c.key != rule.stand else None
    return None


def propose_corrections(rule: NumberRule, column: str, values: pd.Series) -> List[Dict[str, Any]]:
    """One proposal per value the rule refuses, with its spreadsheet row, the old value and (for a measurement) a replacement."""
    ev = evaluate(rule, values)
    out: List[Dict[str, Any]] = []
    numeric = pd.to_numeric(values, errors="coerce")
    for row in ev.hard_rows:
        old = float(numeric.iloc[row - 2]) if (row - 2) < len(numeric) and pd.notna(numeric.iloc[row - 2]) else None
        if old is None:
            continue
        new = propose_value(rule, column, row, old)
        out.append({
            "row": row, "column": column, "stand": rule.stand, "measure": rule.measure, "old": old, "new": None if new is None else round(new, 1),
            "range": range_text(rule), "belongs_to": belongs_to(rule, old),
        })
    return out


def apply_corrections(df: pd.DataFrame, corrections: List[Dict[str, Any]], columns: Dict[str, str]):
    """``(df, applied, ignored)``. Replaces ``df[column]`` at ``row`` with ``value`` - but only where the rules refuse the current value.

    ``columns`` is the validator's ``{rule key: column name}`` map. Anything that does not match a refused cell is returned in ``ignored`` with a reason,
    not applied: a valid measurement is never rewritten.
    """
    out = df.copy()
    applied: List[Dict[str, Any]] = []
    ignored: List[Dict[str, Any]] = []
    key_for = {col: key for key, col in columns.items() if key in RULES}
    for c in corrections or []:
        try:
            row, col, value = int(c["row"]), str(c["column"]), float(c["value"])
        except (KeyError, TypeError, ValueError):
            ignored.append({**c, "reason": "malformed"})
            continue
        key = key_for.get(col)
        idx = row - 2
        if key is None or col not in out.columns or not (0 <= idx < len(out)):
            ignored.append({**c, "reason": "no such cell"})
            continue
        before = pd.to_numeric(pd.Series([out.iloc[idx][col]]), errors="coerce")
        if before.isna().iloc[0] or not evaluate(RULES[key], before).hard_rows:
            ignored.append({**c, "reason": "the current value is not refused by the rules"})
            continue
        if evaluate(RULES[key], pd.Series([value])).hard_rows:
            ignored.append({**c, "reason": "the new value is still refused by the rules"})
            continue
        applied.append({"row": row, "column": col, "old": float(before.iloc[0]), "new": value})
        out.iat[idx, out.columns.get_loc(col)] = value
    return out, applied, ignored


def apply_accepted_corrections(db, df: pd.DataFrame, corrections_json: Optional[str], *, file: Optional[str] = None):
    """``(df, findings)``: apply the corrections the user accepted (a JSON list) and say what was replaced. No input = nothing changes."""
    import json

    from app.services.field_inventory_validator import FieldInventoryValidator
    from app.services.upload.findings import finding

    if not corrections_json:
        return df, []
    try:
        wanted = json.loads(corrections_json)
        if not isinstance(wanted, list):
            raise ValueError("not a list")
    except ValueError:
        return df, []
    columns = FieldInventoryValidator(db)._detect_columns(df)["columns"]
    out, applied, ignored = apply_corrections(df, wanted, columns)
    if ignored:  # not applied, and said so: a correction can never touch a cell the rules accept
        import logging

        logging.getLogger(__name__).info("corrections not applied (%s): %s", file, ignored[:5])
    if not applied:
        return df, []
    shown = "; ".join(f"row {a['row']} {a['column']}: {a['old']:g} → {a['new']:g}" for a in applied[:8]) + (" …" if len(applied) > 8 else "")
    return out, [finding("field_inventory.corrections_applied", rows=[a["row"] for a in applied][:50], count=len(applied), found=shown, file=file)]
