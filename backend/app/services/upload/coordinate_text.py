"""Hand-typed coordinates -> numbers (VALIDATION_TRACKER.md, step C5).

A field team types ``27°41'12"N``, ``२७.६९``, ``84,123`` or ``345,678.5`` into a longitude / latitude column. The meaning is not in doubt, so the value is
converted and nothing is reported (owner, 2026-10-13). Anything we cannot read with confidence is left exactly as typed, for the validator to flag.

Pure: no database, no I/O.
"""
from __future__ import annotations

import re
from typing import Any, Optional

from app.utils.number_format import normalize_nepali_digits

_NUM = r"\d+(?:\.\d+)?"
# degrees [° | d | : ] minutes [' | m | : ] [seconds ["| s]] [hemisphere]
_DMS = re.compile(
    rf"^\s*([+-]?{_NUM})\s*(?:°|º|˚|d(?:eg)?|:)\s*(?:({_NUM})\s*(?:'|′|’|m(?:in)?|:)?\s*)?(?:({_NUM})\s*(?:\"|″|”|''|’’|s(?:ec)?)?\s*)?([NSEWnsew])?\s*$"
)
_DMS_SPACED = re.compile(rf"^\s*([+-]?\d{{1,3}})\s+(\d{{1,2}}(?:\.\d+)?)\s+(\d{{1,2}}(?:\.\d+)?)\s*([NSEWnsew])?\s*$")
_THOUSANDS = re.compile(r"^[+-]?\d{1,3}(?:,\d{3})+(?:\.\d+)?$")
_DECIMAL_COMMA = re.compile(r"^[+-]?\d+,\d+$")
_HEMISPHERE_NE = {"उ": "N", "पू": "E", "द": "S", "प": "W"}


def _plausible(v: float) -> bool:
    """Could this be a coordinate in Nepal: degrees (lat 26-31, lon 80-89) or UTM metres (easting 6 digits, northing 7 digits)."""
    a = abs(v)
    return 26 <= a <= 31 or 80 <= a <= 89 or 100_000 <= a <= 1_000_000 or 2_500_000 <= a <= 3_800_000


def _dms_value(deg: str, minutes: Optional[str], seconds: Optional[str], hemi: Optional[str]) -> Optional[float]:
    d, m, s = float(deg), float(minutes or 0), float(seconds or 0)
    if m >= 60 or s >= 60 or abs(d) > 180:
        return None
    v = abs(d) + m / 60 + s / 3600
    negative = str(deg).strip().startswith("-") or (hemi or "").upper() in ("S", "W")
    return -v if negative else v


def parse_coordinate(value: Any) -> Optional[float]:
    """The number a typed coordinate means, or None when it cannot be read with confidence (leave the cell as typed)."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = normalize_nepali_digits(value).strip()
    for ne, en in _HEMISPHERE_NE.items():  # a trailing Nepali hemisphere letter, e.g. the "उ" of ``२७°४१'१२"उ``
        if text.endswith(ne) and len(text) > len(ne):
            text = text[: -len(ne)].rstrip() + en
    text = text.replace(" ", " ").replace("​", "")
    if not text:
        return None
    # a plain number, possibly with a trailing degree sign: 27.69  /  27.69°  /  +84.1
    plain = re.sub(r"\s*(?:°|º|˚)\s*$", "", text)
    if re.fullmatch(r"[+-]?\d+(?:\.\d+)?", plain):
        return float(plain)
    # thousands separators (UTM metres): 345,678.5  /  3,065,000
    if _THOUSANDS.match(plain):
        thousands = float(plain.replace(",", ""))
        if plain.count(",") == 1 and "." not in plain:
            decimal = float(plain.replace(",", "."))  # "28,123" is 28.123 as often as 28123: the one that is a coordinate wins
            return decimal if _plausible(decimal) or not _plausible(thousands) else thousands
        return thousands
    # decimal comma: 84,123 / 27,69
    if _DECIMAL_COMMA.match(plain):
        return float(plain.replace(",", "."))
    # degrees minutes seconds
    m = _DMS.match(text)
    if m:
        deg, minutes, seconds, hemi = m.groups()
        if minutes is not None or seconds is not None or hemi is not None:
            return _dms_value(deg, minutes, seconds, hemi)
    m = _DMS_SPACED.match(text)
    if m:
        return _dms_value(m.group(1), m.group(2), m.group(3), m.group(4))
    return None


def clean_coordinate_columns(df, columns=("longitude", "latitude")):
    """A copy of ``df`` where text in the coordinate columns is replaced by the number it means. Cells we cannot read, and numbers, are untouched."""
    import pandas as pd

    out = df
    for col in columns:
        if col not in df.columns:
            continue
        series = df[col]
        if series.dtype != object:  # already numbers
            continue
        parsed = series.map(lambda v: parse_coordinate(v) if isinstance(v, str) else v)
        if out is df:
            out = df.copy()
        out[col] = parsed.where(parsed.notna(), series)
        numeric = pd.to_numeric(out[col], errors="coerce")
        if numeric.notna().sum() == out[col].notna().sum():  # all numbers now: make the column numeric for the checks that follow
            out[col] = numeric
    return out
