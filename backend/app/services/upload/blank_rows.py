"""Rows at the bottom of a sheet that hold nothing but empty text are not records.

A template's calculated columns are filled 5,000 rows down and show "" where there is no data, so a file saved from Excel can carry thousands of such rows.
Only the TRAILING ones are dropped, so the row numbers of everything above stay the spreadsheet's own.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def trim_blank_tail(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    blank = df.map(lambda v: v is None or (isinstance(v, float) and np.isnan(v)) or (isinstance(v, str) and not v.strip())).all(axis=1).to_numpy()
    filled = np.flatnonzero(~blank)
    return df.iloc[: int(filled[-1]) + 1] if len(filled) else df.iloc[:0]
