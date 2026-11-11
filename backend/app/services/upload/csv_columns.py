"""Read a CSV/Excel file's columns, sample rows, and auto-detected lat/lon.

The user-group CSV column picker (UP-3.2) uses this when auto-detection does not
find the coordinate columns, so the user can name them instead of getting a
"CSV must have lat/lon columns" dead end. `POST /uploads/csv-columns` serves it.
"""

import io
from typing import Any, Dict, Optional, Tuple

import pandas as pd


def _detect_lat_lon(df: pd.DataFrame) -> Tuple[Optional[str], Optional[str]]:
    lat_col = None
    lon_col = None
    for col in df.columns:
        col_lower = str(col).lower().strip()
        if col_lower in ("lat", "latitude", "y", "अक्षांश"):
            lat_col = col
        if col_lower in ("lon", "long", "longitude", "x", "देशान्तर"):
            lon_col = col
    if lat_col is None or lon_col is None:  # other spellings (Lng, अक्षाँस, "Latitude (DD)" ...): the shared resolver
        from .column_synonyms import coordinate_columns

        lon_found, lat_found = coordinate_columns(df.columns, "trees", broad=False)  # plain names only: 'east' / 'north' are asked, not guessed
        lat_col = lat_col or lat_found
        lon_col = lon_col or lon_found
    return lat_col, lon_col


def read_csv_columns(file_bytes: bytes, filename: str, max_rows: int = 5) -> Dict[str, Any]:
    """Read a CSV/Excel file and return columns, sample rows, and auto-detected lat/lon.

    Returns:
        {
            "columns": ["col1", "col2", ...],
            "sample_rows": [["val1", "val2"], ...],
            "lat_col": "latitude" | None,
            "lon_col": "longitude" | None,
            "total_rows": int,
        }
    """
    ext = filename.lower().split(".")[-1] if "." in filename else ""
    is_excel = ext in ("xlsx", "xls")

    # A fresh BytesIO each time: pandas advances/closes the stream it is given.
    if is_excel:
        df = pd.read_excel(io.BytesIO(file_bytes), nrows=max_rows)
        total_rows = len(pd.read_excel(io.BytesIO(file_bytes)))
    else:
        df = pd.read_csv(io.BytesIO(file_bytes), nrows=max_rows)
        total_rows = len(pd.read_csv(io.BytesIO(file_bytes)))

    lat_col, lon_col = _detect_lat_lon(df)

    return {
        "columns": [str(c) for c in df.columns],
        "sample_rows": [
            ["" if pd.isna(v) else str(v) for v in row] for row in df.values.tolist()
        ],
        "lat_col": lat_col,
        "lon_col": lon_col,
        "total_rows": total_rows,
    }
