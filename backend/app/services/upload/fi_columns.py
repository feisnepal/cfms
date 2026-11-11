"""Field inventory column names we can read even when they are not the template's (UPLOAD_EXPERIENCE_PLAN.md, UP-3.2).

The validator wants exact names (``longitude``, ``sample_plot_number``, ``tree_dbh_cm`` ...). A file that says ``Lon``, ``Plot No`` or
``longtitude`` used to be refused with "required column missing". :func:`normalise_columns` renames such columns to the template names -
only when the target is not already present and the match is unambiguous - and returns what it did, so the user is told (never silent).
Applied to the upload AND the later processing read, so both see the same names.
"""
from __future__ import annotations

import difflib
import re
from typing import Dict, List, Optional, Tuple

from app.services.upload.column_synonyms import resolve_column
from app.services.upload.coordinate_text import clean_coordinate_columns

# normalised alias (lowercase, non-alphanumerics -> '_') -> template name
SYNONYMS: Dict[str, str] = {
    **{k: "longitude" for k in ("lon", "long", "lng", "longitude_dd", "x_longitude", "देशान्तर")},
    **{k: "latitude" for k in ("lat", "latitude_dd", "y_latitude", "अक्षांश")},
    **{k: "block_name" for k in ("block", "block_no", "block_id", "compartment", "compartment_no", "compartment_id", "ब्लक", "कम्पार्टमेन्ट")},
    **{k: "sample_plot_number" for k in ("plot", "plot_no", "plot_number", "plot_id", "sample_plot", "sample_plot_no", "sp_no", "sp", "plot_num",
                                         "नमुना_प्लट", "प्लट_नं")},
    **{k: "tree_species_scientific" for k in ("tree_species", "tree_species_name", "tree_scientific_name")},
    **{k: "pole_species_scientific" for k in ("pole_species", "pole_species_name", "pole_scientific_name")},
    **{k: "sapling_species_scientific" for k in ("sapling_species", "sapling_species_name", "sapling_scientific_name")},
    **{k: "regen_species_scientific" for k in ("regen_species", "regeneration_species", "regen_species_name")},
    **{k: "tree_dbh" for k in ("tree_diameter", "tree_dbh_cm_", "tree_dbh_in_cm")},
    **{k: "tree_height" for k in ("tree_ht", "tree_height_in_m")},
}
_FUZZY_TARGETS = [
    "block_name", "sample_plot_number", "longitude", "latitude",
    "regen_species_scientific", "regen_dbh", "regen_count",
    "sapling_species_scientific", "sapling_dbh", "sapling_count",
    "pole_species_scientific", "pole_dbh", "pole_height",
    "tree_species_scientific", "tree_dbh", "tree_height",
]
# names the validator already accepts: never renamed, and they satisfy their target
_ALREADY_OK = {
    "compartment_name": "block_name",
    "sapling_dbh_cm": "sapling_dbh", "pole_dbh_cm": "pole_dbh", "tree_dbh_cm": "tree_dbh",
    "pole_height_m": "pole_height", "tree_height_m": "tree_height",
}
_FUZZY_CUTOFF = 0.88


def _norm(name: object) -> str:
    return re.sub(r"[^\w]+", "_", str(name).strip().lower(), flags=re.UNICODE).strip("_")


def _plan(columns) -> List[Tuple[str, str]]:
    """``[(original column, template name)]`` for the columns that can safely be renamed."""
    return [(c, t) for c, t, _ in _plan_with_units(columns)]


def _plan_with_units(columns) -> List[Tuple[str, str, Optional[str]]]:
    """``[(original column, template name, unit written in its header or None)]``."""
    present = {_norm(c) for c in columns}
    satisfied = set(present) | {t for a, t in _ALREADY_OK.items() if a in present}
    taken = set(satisfied)
    plan: List[Tuple[str, str, Optional[str]]] = []
    for col in columns:
        n = _norm(col)
        exact = str(col).strip().lower()  # the validator's own test: lower-case, trimmed, spaces NOT folded
        if exact in _FUZZY_TARGETS or exact in _ALREADY_OK:
            continue
        # the shared resolver first (Nepali spellings, stand x measure names, units in brackets); then this module's older table, then fuzzy
        match = resolve_column(col, "field_inventory")
        target = match.canonical if match and match.canonical in _FUZZY_TARGETS else None
        unit = match.unit if target else None
        if target is None:
            target = SYNONYMS.get(n)
        if target is None:
            m = difflib.get_close_matches(n, _FUZZY_TARGETS, n=2, cutoff=_FUZZY_CUTOFF)
            # two near candidates means we are guessing: leave it to the user
            if len(m) == 1 or (len(m) == 2 and difflib.SequenceMatcher(None, n, m[0]).ratio() - difflib.SequenceMatcher(None, n, m[1]).ratio() > 0.08):
                target = m[0]
        if target and target not in taken:
            plan.append((col, target, unit))
            taken.add(target)
    return plan


# Declared units only: a unit written in the header is a statement, so the column is converted (and the user told); a unit nobody wrote is
# never guessed here - the value checks in upload/units.py look at that case. Diameters end up in cm, heights in m.
_TO_CM = {"mm": 0.1, "m": 100.0, "in": 2.54}
_TO_M = {"cm": 0.01, "ft": 1 / 3.28084, "in": 0.0254}


def _factor(target: str, unit: Optional[str]) -> Optional[float]:
    if not unit:
        return None
    if target.endswith("_dbh"):
        return _TO_CM.get(unit)
    if target.endswith("_height"):
        return _TO_M.get(unit)
    return None


def normalise_columns_with_units(df) -> Tuple[object, List[Tuple[str, str]], List[Tuple[str, str, float]]]:
    """``(df, renames [(was, now)], conversions [(was, unit written, factor applied)])``. The input frame is not modified.

    Only numeric cells are scaled; text a user typed into a number column is left exactly as it was for the validator to report.
    """
    import pandas as pd

    plan = _plan_with_units(list(df.columns))
    if not plan:
        return clean_coordinate_columns(df), [], []
    out = df.rename(columns={c: t for c, t, _ in plan})
    conversions: List[Tuple[str, str, float]] = []
    for was, now, unit in plan:
        factor = _factor(now, unit)
        if factor is None or now not in out.columns:
            continue
        num = pd.to_numeric(out[now], errors="coerce")
        out[now] = (num * factor).where(num.notna(), out[now])
        conversions.append((was, unit, factor))
    return clean_coordinate_columns(out), [(c, t) for c, t, _ in plan], conversions  # typed formats (DMS, Nepali digits, comma decimals) become numbers


def normalise_columns(df) -> Tuple[object, List[Tuple[str, str]]]:
    """Return ``(df with template column names and declared units, [(was, now)])``. The input frame is not modified."""
    out, renames, _ = normalise_columns_with_units(df)
    return out, renames
