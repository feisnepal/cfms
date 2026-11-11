"""Sample plots prepared in another system, loaded from an Excel / CSV table (owner, 2026-10-13).

The table (``02_Sample_Plots`` in the template zip) becomes the forest's one sampling design, stored exactly as the generators store it, so the map layer, the
per-unit summary, the field book and the field inventory read it unchanged. This module only PREPARES the plots - it reads and checks the table and places
every plot in a forest unit; writing the design is the API's job.

What is checked, in plain words, with the rows named:
* the plot number: a whole number, unique. Plots are numbered by position everywhere in the sampling code (``plot_number = index + 1``) and field-inventory rows
  refer to plots by number, so the numbers must run 1..N; otherwise the import is refused, and with ``renumber=True`` they are renumbered in order and the old->new
  list is reported (never silently: a field-inventory file would no longer match);
* the coordinates: present on every row, in a stated system (the template's ``coordinate_system_epsg`` column, or the user's choice), inside the forest;
* the unit: found from where the plot lies, and compared with the ``block_name`` in the file when the file has one;
* the radius: one per design (the design stores one), so a file whose rows differ is told which value was used.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from .column_synonyms import resolve_column
from .coordinates import SYSTEM_LABELS, UTM_ZONES, apply_chosen_system, declared_system, point_kind, point_report
from .findings import UploadFinding, finding

DEFAULT_RADIUS_M = 12.62  # a 500 m2 circle: the plot the guideline uses
RADIUS_RANGE = (1.0, 50.0)
BOUNDARY_TOLERANCE_DEG = 0.0003  # about 30 m: a GPS fix on the edge of the boundary is not "outside"
UNIT_TOLERANCE_DEG = 0.0003


@dataclass
class Plot:
    number: int
    lon: float
    lat: float
    unit_index: int
    unit_name: str
    row: int  # spreadsheet row, for messages


@dataclass
class Prepared:
    plots: List[Plot] = field(default_factory=list)
    radius_m: float = DEFAULT_RADIUS_M
    errors: List[UploadFinding] = field(default_factory=list)
    infos: List[UploadFinding] = field(default_factory=list)
    renumbered: List[Tuple[int, int]] = field(default_factory=list)


def _normalise_columns(df: pd.DataFrame) -> Dict[str, str]:
    """{canonical sample-plot column: the user's header}; the first header that names a column wins, a plain longitude / latitude beats Easting / Northing."""
    from .column_synonyms import coordinate_columns

    found: Dict[str, str] = {}
    for header in df.columns:
        m = resolve_column(header, "sample_plots")
        if m and m.canonical not in found and m.canonical not in ("longitude", "latitude"):
            found[m.canonical] = header
    lon, lat = coordinate_columns(df.columns, "sample_plots")
    if lon is not None:
        found["longitude"] = lon
    if lat is not None:
        found["latitude"] = lat
    return found


def prepare_sample_plots(df: pd.DataFrame, db, *, units: Sequence[Dict[str, Any]], boundary_wkt: str, crs_epsg: Optional[int] = None,
                         renumber: bool = False, file: Optional[str] = None) -> Prepared:
    """Read and check the table. ``units`` are ``forest_units.sampling_units`` (name, wkt, area_ha), in the engines' order."""
    from shapely import wkt as _wkt
    from shapely.geometry import Point
    from shapely.strtree import STRtree

    out = Prepared()
    # the template's grey example row, if the user left it in, is not a plot (row numbers still count it)
    if len(df):
        is_example = df.apply(lambda r: any(isinstance(v, str) and v.strip().upper().startswith("EXAMPLE") for v in r), axis=1)
        df = df[~is_example.astype(bool)]
    cols = _normalise_columns(df)
    missing = [c for c in ("longitude", "latitude") if c not in cols]
    if missing:
        out.errors.append(finding("field_inventory.required_column_missing", found="longitude / latitude", file=file))
        return out
    if len(df) == 0:
        out.errors.append(finding("file.no_rows", file=file))
        return out

    work = pd.DataFrame({"longitude": df[cols["longitude"]], "latitude": df[cols["latitude"]]})
    if "plot_number" in cols:
        work["plot_number"] = df[cols["plot_number"]]
    if "block" in cols:
        work["block"] = df[cols["block"]]
    if "radius_m" in cols:
        work["radius_m"] = df[cols["radius_m"]]
    work.index = df.index
    rows = [int(i) + 2 for i in df.index]  # spreadsheet rows (row 1 is the header)

    # ── coordinate system: the user's choice, else the file's own declaration, else degrees as they are ──────────────────────
    decl = declared_system(df)
    if decl["mixed"]:
        out.errors.append(finding("coordinates.declared_mixed", found=", ".join(map(str, decl["values"])), file=file))
        return out
    if decl["unsupported"] and not crs_epsg:
        out.errors.append(finding("coordinates.declared_unsupported", found=decl["unsupported"][0], file=file))
        return out
    epsg = crs_epsg or decl["epsg"]
    work["longitude"] = pd.to_numeric(work["longitude"], errors="coerce")
    work["latitude"] = pd.to_numeric(work["latitude"], errors="coerce")
    report = point_report(work["longitude"], work["latitude"])
    if report["missing_rows"]:
        out.errors.append(finding("coordinates.rows_missing", rows=report["missing_rows"][:50], count=len(report["missing_rows"]), file=file))
        return out
    if epsg in UTM_ZONES:
        work, findings = apply_chosen_system(db, work, epsg, file=file)
        out.infos.extend(f for f in findings if f.code == "coordinates.utm_converted")
        out.errors.extend(f for f in findings if f.code == "coordinates.system_mismatch")
        if out.errors:
            return out
    else:
        kinds = [point_kind(a, b) for a, b in zip(work["longitude"], work["latitude"])]
        if any(k == "utm" for k in kinds):
            out.errors.append(finding("coordinates.looks_like_utm", found="44 or 45", expected="32644 or 32645", file=file))
            return out
        stray = [(r, k) for r, k in zip(rows, kinds) if k not in ("degrees",)]
        if stray:
            out.errors.append(finding("sample_plots.coordinates_not_degrees", rows=[r for r, _ in stray][:50], count=len(stray), file=file))
            return out

    # ── plot numbers ───────────────────────────────────────────────────────────────────────────────────────────────────────
    n = len(work)
    if "plot_number" in work.columns:
        numbers = pd.to_numeric(work["plot_number"], errors="coerce")
        bad = [r for r, v in zip(rows, numbers) if pd.isna(v) or v != int(v) or v < 1]
        if bad:
            out.errors.append(finding("sample_plots.number_invalid", rows=bad[:50], count=len(bad), file=file))
            return out
        numbers = numbers.astype(int)
        dup_values = sorted({int(v) for v in numbers[numbers.duplicated(keep=False)]})
        if dup_values:
            out.errors.append(finding("sample_plots.number_duplicated", found=", ".join(map(str, dup_values[:12])), rows=[r for r, v in zip(rows, numbers) if v in dup_values][:50], file=file))
            return out
    else:
        numbers = pd.Series(range(1, n + 1), index=work.index)
        out.infos.append(finding("sample_plots.numbered_in_file_order", count=n, file=file))
    order = list(np.argsort(numbers.to_numpy(), kind="stable"))
    sorted_numbers = [int(numbers.iloc[i]) for i in order]
    if sorted_numbers != list(range(1, n + 1)):
        if not renumber:
            gaps = sorted(set(range(1, max(sorted_numbers) + 1)) - set(sorted_numbers))[:10]
            out.errors.append(finding("sample_plots.numbers_not_consecutive", found=f"{sorted_numbers[0]}..{sorted_numbers[-1]}", expected=f"1..{n}",
                                      count=n, auto_fix="renumber_plots", file=file))
            return out
        out.renumbered = [(sorted_numbers[k], k + 1) for k in range(n) if sorted_numbers[k] != k + 1]
        out.infos.append(finding("sample_plots.renumbered", count=len(out.renumbered),
                                 found="; ".join(f"{a} → {b}" for a, b in out.renumbered[:12]) + (" …" if len(out.renumbered) > 12 else ""), file=file))

    # ── inside the forest, and which unit ──────────────────────────────────────────────────────────────────────────────────
    boundary = _wkt.loads(boundary_wkt)
    shapes = [_wkt.loads(u["wkt"]) if u.get("wkt") else None for u in units]
    tree_items = [(i, g) for i, g in enumerate(shapes) if g is not None]
    tree = STRtree([g for _, g in tree_items]) if tree_items else None
    outside, mismatched = [], []
    plots: List[Plot] = []
    for k, i in enumerate(order):
        lon, lat = float(work["longitude"].iloc[i]), float(work["latitude"].iloc[i])
        p = Point(lon, lat)
        if not boundary.buffer(BOUNDARY_TOLERANCE_DEG).contains(p):
            outside.append(rows[i])
            continue
        unit_index = None
        if tree is not None:
            for cand in tree.query(p.buffer(UNIT_TOLERANCE_DEG)):
                idx = tree_items[int(cand)][0]
                if shapes[idx].contains(p):
                    unit_index = idx
                    break
            if unit_index is None:  # on an edge or in a sliver: the nearest unit within the tolerance
                best = min(((shapes[tree_items[int(c)][0]].distance(p), tree_items[int(c)][0]) for c in tree.query(p.buffer(UNIT_TOLERANCE_DEG))), default=None)
                if best and best[0] <= UNIT_TOLERANCE_DEG:
                    unit_index = best[1]
        if unit_index is None:
            outside.append(rows[i])
            continue
        name = units[unit_index]["name"]
        if "block" in work.columns:
            stated = str(work["block"].iloc[i]).strip()
            if stated and stated.lower() not in ("nan", "none") and stated.lower() not in (name.lower(), str(units[unit_index].get("display_name", "")).lower()):
                mismatched.append((rows[i], stated, name))
        plots.append(Plot(number=k + 1, lon=lon, lat=lat, unit_index=unit_index, unit_name=name, row=rows[i]))
    if outside:
        out.errors.append(finding("sample_plots.outside_forest", rows=outside[:50], count=len(outside), file=file))
        return out
    if mismatched:
        out.infos.append(finding("sample_plots.block_differs", count=len(mismatched), rows=[r for r, _, _ in mismatched][:50],
                                 found="; ".join(f"row {r}: {s} → {u}" for r, s, u in mismatched[:6]), file=file))
    out.plots = plots

    # ── radius: the design stores one ──────────────────────────────────────────────────────────────────────────────────────
    if "radius_m" in work.columns:
        radii = pd.to_numeric(work["radius_m"], errors="coerce").dropna()
        if len(radii):
            bad_r = [r for r, v in zip(rows, pd.to_numeric(work["radius_m"], errors="coerce")) if pd.notna(v) and not (RADIUS_RANGE[0] <= v <= RADIUS_RANGE[1])]
            if bad_r:
                out.errors.append(finding("sample_plots.radius_invalid", rows=bad_r[:50], count=len(bad_r), file=file))
                out.plots = []
                return out
            out.radius_m = float(round(radii.mode().iloc[0] if radii.nunique() < len(radii) else radii.median(), 2))
            if radii.nunique() > 1:
                out.infos.append(finding("sample_plots.radius_differs", found=f"{out.radius_m:g}", expected=", ".join(f"{v:g}" for v in sorted(radii.unique())[:6]), file=file))
    return out


def plot_area_sqm(radius_m: float) -> float:
    return math.pi * radius_m * radius_m
