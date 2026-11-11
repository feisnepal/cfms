"""The forest's identifying details from a one-row Excel / CSV table (the ``07_Forest_Metadata`` template).

Only the essentials: the eleven fields the forest-details form already edits. This module READS and CHECKS; the API merges the result into the saved row
(a detail the file leaves empty keeps its saved value - an import never clears what somebody typed) and the existing service validates and stores it.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

from app.services.forest_metadata_service import EDITABLE_FIELDS, FIELD_MAXLEN, _fy_sort_key
from app.utils.number_format import normalize_nepali_digits

from .column_synonyms import resolve_column
from .findings import UploadFinding, finding


def _text(value: Any) -> Optional[str]:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    if isinstance(value, float) and value.is_integer():
        value = int(value)  # a ward typed as 5 arrives as 5.0
    text = normalize_nepali_digits(str(value)).strip()
    return text or None


def read_metadata(df: pd.DataFrame, *, file: Optional[str] = None) -> Tuple[Dict[str, str], List[UploadFinding], List[UploadFinding]]:
    """``(values, errors, infos)``: the details found, what refuses the file, what to tell the user."""
    errors: List[UploadFinding] = []
    infos: List[UploadFinding] = []
    columns: Dict[str, str] = {}
    for header in df.columns:
        m = resolve_column(header, "forest_metadata")
        if m and m.canonical in EDITABLE_FIELDS and m.canonical not in columns:
            columns[m.canonical] = header
    rows = [i for i in df.index if any(_text(df.at[i, c]) for c in columns.values())] if columns else []
    # the template's grey example row is not a record
    rows = [i for i in rows if not any((_text(df.at[i, c]) or "").upper().startswith("EXAMPLE") for c in columns.values())]
    if not columns or not rows:
        errors.append(finding("forest_metadata.nothing_found", file=file))
        return {}, errors, infos
    if len(rows) > 1:
        infos.append(finding("forest_metadata.several_rows", count=len(rows), found=int(rows[0]) + 2, file=file))
    row = rows[0]
    values = {field: v for field, header in columns.items() if (v := _text(df.at[row, header]))}
    for f in [f for f, v in values.items() if len(v) > FIELD_MAXLEN.get(f, 255)]:
        errors.append(finding("forest_metadata.too_long", found=f, expected=FIELD_MAXLEN.get(f, 255), rows=[int(row) + 2], file=file))
    fy_start, fy_end = values.get("fy_start"), values.get("fy_end")
    if fy_start and fy_end and _fy_sort_key(fy_start) > _fy_sort_key(fy_end):
        errors.append(finding("forest_metadata.fy_order", found=f"{fy_start} → {fy_end}", file=file))
    infos.append(finding("forest_metadata.imported", count=len(values), found=", ".join(values), file=file))
    return values, errors, infos
