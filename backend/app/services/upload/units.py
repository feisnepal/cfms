"""Spot a measurement entered in the wrong unit (UPLOAD_EXPERIENCE_PLAN.md, UP-3.3).

Tree diameters are in centimetres. A column whose MEDIAN is above 150 is not a forest of 1.5 m trees; it is millimetres. One value like that can be a
typing slip (the existing range check reports it); a whole column like that is a unit, and importing it would make every volume and carbon figure
a hundred times too big, silently. So it stops the upload and says what to do (we do not divide by ten behind the user's back).
"""
from __future__ import annotations

from typing import Iterable, List, Optional, Tuple

import numpy as np
import pandas as pd

from app.services.upload.findings import UploadFinding, finding

DBH_MEDIAN_LIMIT_CM = 150.0  # no real stand has a median diameter of 1.5 m
MIN_VALUES = 3  # a median of one or two numbers says nothing


def dbh_unit_problem(values) -> Optional[Tuple[float, float]]:
    """(median as entered, median if it were millimetres) when the column looks like millimetres, else None."""
    v = pd.to_numeric(pd.Series(list(values)), errors="coerce").dropna()
    v = v[v > 0]
    if len(v) < MIN_VALUES:
        return None
    med = float(np.median(v))
    return (med, med / 10.0) if med > DBH_MEDIAN_LIMIT_CM else None


def dbh_unit_findings(columns: Iterable[Tuple[str, Iterable]], file: Optional[str] = None) -> List[UploadFinding]:
    """One finding per diameter column that looks like millimetres. ``columns`` = (label, values), e.g. ('tree diameters', series)."""
    out: List[UploadFinding] = []
    for label, values in columns:
        p = dbh_unit_problem(values)
        if p:
            out.append(finding("field_inventory.dbh_in_mm", found=f"{label} (median {p[0]:g})", expected=f"{p[1]:g}", file=file))
    return out


HEIGHT_MEDIAN_LIMIT_M = 45.0  # a median tree height above 45 m does not occur in Nepal's forests; it is feet (x3.28) far more often than not


def height_unit_problem(values) -> Optional[Tuple[float, float]]:
    """(median as entered, median if it were feet) when the column looks like feet, else None."""
    v = pd.to_numeric(pd.Series(list(values)), errors="coerce").dropna()
    v = v[v > 0]
    if len(v) < MIN_VALUES:
        return None
    med = float(np.median(v))
    return (med, med / 3.28084) if med > HEIGHT_MEDIAN_LIMIT_M else None


def height_unit_findings(columns: Iterable[Tuple[str, Iterable]], file: Optional[str] = None) -> List[UploadFinding]:
    """One WARNING per height column that looks like feet (we cannot be sure, so it does not stop the upload)."""
    out: List[UploadFinding] = []
    for label, values in columns:
        p = height_unit_problem(values)
        if p:
            out.append(finding("field_inventory.height_in_feet", found=f"{label} (median {p[0]:g})", expected=f"{p[1]:.1f}", file=file))
    return out
