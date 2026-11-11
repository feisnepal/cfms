"""The NTFP field form: the Excel workbook a team takes to the plots, and the reader that checks it coming back (NTFP inventory, phase 3).

Pure: dicts and bytes in, dicts and bytes out. The database side is ``ntfp_records_service``.

The workbook is tailored to ONE design: it lists exactly the (plot, species) pairs the design assigned, with each species' own plot size and
method beside it, so a team cannot record a species where it was not meant to be sampled.

  Plots         one row per (plot, species): the grey columns are fixed; the team fills the date and the counts
  Weights       fresh and dry weight, one row per sampled individual (or part), in grams
  Species guide the method card of each species in the design: part, destructive or not, plot size, maturity sign, how many to lift
  Instructions  the rules below, in plain words

Rules the reader enforces (everything else is a warning):
  * a count cell that is EMPTY means "not surveyed yet"; ZERO means "surveyed, the species is absent": frequency needs the zeros;
  * the pair (plot, species) must be one the design assigned; a pair may appear once;
  * counts are whole numbers >= 0; mature + small may not exceed the total;
  * a weight needs a count of at least 1 for its pair; fresh weight > 0; dry weight >= 0 and not more than the fresh weight;
  * Devanagari digits are read as digits.
Any error refuses the whole file: nothing is half-imported.
"""
from __future__ import annotations

import io
import re
from datetime import date, datetime
from typing import Any, Dict, Iterable, List, Optional, Tuple

from openpyxl import Workbook, load_workbook
from openpyxl.comments import Comment
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation

from app.core.ntfp_schedule7 import GROUPS
from app.utils.number_format import normalize_nepali_digits

PLOTS = "Plots"
WEIGHTS = "Weights"
GUIDE = "Species guide"
INSTRUCTIONS = "Instructions"

PLOT_FIXED = ["plot_number", "stratum", "longitude", "latitude", "species_key", "nepali_name", "scientific_name", "plot_size_sqm"]
PLOT_ENTRY = ["visit_date", "count_total", "count_mature", "count_small", "clumps", "tillers", "notes"]
WEIGHT_COLS = ["plot_number", "species_key", "sample_no", "part", "fresh_weight_g", "dry_weight_g", "notes"]
WEIGHT_ROWS = 300  # blank rows offered; the reader takes any number of rows

COUNT_COLS = ["count_total", "count_mature", "count_small", "clumps", "tillers"]
MAX_COUNT = 1_000_000
MAX_WEIGHT_G = 5_000_000.0  # five tonnes in one sample is a typing error
MAX_ROWS = 20_000

_GREY = PatternFill("solid", fgColor="FFE7E7E7")
_HEAD = PatternFill("solid", fgColor="FF2E7D32")
_ENTRY = PatternFill("solid", fgColor="FFFFF4CC")

_COLUMN_HELP = {
    "plot_number": "Fixed. The plot's number on the map and in the design.",
    "species_key": "Fixed. The species' name key; do not change it.",
    "plot_size_sqm": "Fixed. The plot size for this species (m2).",
    "visit_date": "The day you surveyed this plot (a date, e.g. 2083-07-12 or 2026-10-29).",
    "count_total": "Number of plants (or stems, trees, fruiting bodies) of this species in the plot. Write 0 if you looked and found none; leave EMPTY only if not surveyed yet.",
    "count_mature": "How many of them are mature (the sign of maturity is on the Species guide).",
    "count_small": "How many are small / young.",
    "clumps": "Shrubs and herbs: number of clumps (bhuyad) in the plot.",
    "tillers": "Shrubs: number of tillers (stems from the base) counted.",
    "sample_no": "Number of the sampled individual in that plot (1, 2, 3...). Leave empty to number them in order.",
    "part": "The part you weighed. Leave empty for the species' usual part.",
    "fresh_weight_g": "Weight right after harvesting, in GRAMS.",
    "dry_weight_g": "Weight after drying, in GRAMS. Not more than the fresh weight. Leave empty until it is dry.",
}


# ── building ────────────────────────────────────────────────────────────────────────────────────────────────────────────────────

def _head(ws, names: List[str], entry_from: Optional[int] = None) -> None:
    for i, name in enumerate(names, 1):
        c = ws.cell(1, i, name)
        c.font = Font(bold=True, color="FFFFFFFF")
        c.fill = _HEAD
        c.alignment = Alignment(wrap_text=True, vertical="center")
        if name in _COLUMN_HELP:
            c.comment = Comment(_COLUMN_HELP[name], "NTFP")
    ws.freeze_panes = "A2"


def build_workbook(design: Dict[str, Any], species: List[Dict[str, Any]], forest_name: str = "") -> bytes:
    """``design`` is the stored design (``ntfp_design_service.load``); ``species`` the profile of each species in it, keyed ``species_key``."""
    by_key = {s["species_key"]: s for s in species}
    plot_size = {s["species_key"]: s.get("plot_sqm") for s in design.get("species", [])}
    wb = Workbook()

    ws = wb.active
    ws.title = PLOTS
    _head(ws, PLOT_FIXED + PLOT_ENTRY)
    n = 1
    for p in sorted(design["plots"], key=lambda p: p["plot_number"]):
        for key in sorted(p["species_keys"]):
            sp = by_key.get(key, {})
            n += 1
            for i, v in enumerate([p["plot_number"], p["stratum"], round(p["longitude"], 7), round(p["latitude"], 7), key,
                                   sp.get("nepali_name", ""), sp.get("scientific_name") or "", plot_size.get(key)], 1):
                c = ws.cell(n, i, v)
                c.fill = _GREY
            for i in range(len(PLOT_FIXED) + 1, len(PLOT_FIXED) + len(PLOT_ENTRY) + 1):
                ws.cell(n, i).fill = _ENTRY
    last = max(n, 2)
    col = {name: get_column_letter(i) for i, name in enumerate(PLOT_FIXED + PLOT_ENTRY, 1)}
    whole = DataValidation(type="whole", operator="between", formula1="0", formula2=str(MAX_COUNT), allow_blank=True,
                           errorTitle="Whole number", error="A count is a whole number, 0 or more.")
    ws.add_data_validation(whole)
    for name in COUNT_COLS:
        whole.add(f"{col[name]}2:{col[name]}{last}")
    dates = DataValidation(type="date", operator="greaterThan", formula1="36526", allow_blank=True, errorTitle="Date", error="Enter a date.")
    ws.add_data_validation(dates)
    dates.add(f"{col['visit_date']}2:{col['visit_date']}{last}")
    for name, w in zip(PLOT_FIXED + PLOT_ENTRY, [9, 14, 12, 12, 26, 18, 26, 10, 12, 10, 10, 10, 9, 9, 30]):
        ws.column_dimensions[col[name]].width = w
    for r in range(2, last + 1):
        ws[f"{col['visit_date']}{r}"].number_format = "yyyy-mm-dd"

    wsw = wb.create_sheet(WEIGHTS)
    _head(wsw, WEIGHT_COLS)
    wcol = {name: get_column_letter(i) for i, name in enumerate(WEIGHT_COLS, 1)}
    num = DataValidation(type="decimal", operator="greaterThanOrEqual", formula1="0", allow_blank=True, errorTitle="Weight", error="A weight in grams, 0 or more.")
    wsw.add_data_validation(num)
    num.add(f"{wcol['fresh_weight_g']}2:{wcol['dry_weight_g']}{WEIGHT_ROWS + 1}")
    parts = DataValidation(type="list", formula1='"' + ",".join(g[0] for g in GROUPS.values()) + '"', allow_blank=True)
    wsw.add_data_validation(parts)
    parts.add(f"{wcol['part']}2:{wcol['part']}{WEIGHT_ROWS + 1}")
    for name, w in zip(WEIGHT_COLS, [10, 28, 9, 20, 14, 14, 30]):
        wsw.column_dimensions[wcol[name]].width = w
    for r in range(2, WEIGHT_ROWS + 2):
        for c in range(1, len(WEIGHT_COLS) + 1):
            wsw.cell(r, c).fill = _ENTRY

    wg = wb.create_sheet(GUIDE)
    heads = ["species_key", "nepali_name", "scientific_name", "growth_class", "part_harvested", "method", "plot_size_sqm", "plots_assigned",
             "maturity_sign", "individuals_to_lift", "fraction_taken_pct", "conversion_factor_reference", "procedure"]
    _head(wg, heads)
    assigned = {}
    for p in design["plots"]:
        for key in p["species_keys"]:
            assigned[key] = assigned.get(key, 0) + 1
    for r, d in enumerate(design.get("species", []), 2):
        sp = by_key.get(d["species_key"], {})
        lo, hi = sp.get("n_individuals_min"), sp.get("n_individuals_max")
        wg.append([d["species_key"], sp.get("nepali_name", d.get("label", "")), sp.get("scientific_name") or "", d.get("growth_class", ""),
                   sp.get("part_ne") or "", (sp.get("sampling_method") or "").replace("_", " "), d.get("plot_sqm"), assigned.get(d["species_key"], 0),
                   sp.get("maturity_ne") or "", (f"{lo}" if lo == hi else f"{lo}-{hi}") if lo else "", sp.get("harvest_fraction_pct") or "",
                   sp.get("conversion_factor") or "", sp.get("procedure_en") or ""])
    for i, w in enumerate([26, 18, 26, 12, 22, 16, 10, 10, 40, 12, 10, 12, 80], 1):
        wg.column_dimensions[get_column_letter(i)].width = w

    wi = wb.create_sheet(INSTRUCTIONS)
    for line in [
        f"NTFP inventory form{(' - ' + forest_name) if forest_name else ''}",
        "",
        "1. Sheet 'Plots': one row for every plot and species the design assigned. Fill the YELLOW cells. The grey cells are fixed: do not change them.",
        "2. An EMPTY count means 'not surveyed yet'. If you surveyed the plot and the species was not there, write 0. The zeros matter: how often a species occurs depends on them.",
        "3. Sheet 'Weights': one row per sampled individual (or part). Plot number and species_key must be copied from the Plots sheet. Weights are in GRAMS.",
        "4. Weigh FRESH right after harvesting; weigh DRY after drying. The dry weight can never be more than the fresh weight.",
        "5. A weight row needs a count of at least 1 for that plot and species.",
        "6. 'Species guide' says, for each species, which part to harvest, whether the plant is lifted, the plot size and the sign that it is mature.",
        "7. Save as .xlsx and upload it in the NTFP inventory page. Uploading again replaces the rows you send; rows you leave out are kept.",
        "8. If any row has a mistake, nothing is imported and the page lists every mistake with its row.",
    ]:
        wi.append([line])
    wi["A1"].font = Font(bold=True, size=13)
    wi.column_dimensions["A"].width = 150
    wb.active = 0
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ── reading ───────────────────────────────────────────────────────────────────────────────────────────────────────────────────

def _finding(severity: str, sheet: str, row: Optional[int], column: Optional[str], code: str, message: str) -> Dict[str, Any]:
    return {"severity": severity, "sheet": sheet, "row": row, "column": column, "code": code, "message": message}


def _blank(v: Any) -> bool:
    return v is None or (isinstance(v, str) and not v.strip())


def _number(v: Any) -> Optional[float]:
    """A cell as a number: Devanagari digits and a decimal comma accepted; None when it is not one."""
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        t = normalize_nepali_digits(v).strip().replace(",", ".")
        try:
            return float(t)
        except ValueError:
            return None
    return None


def _whole(v: Any) -> Optional[int]:
    x = _number(v)
    return int(x) if x is not None and x == int(x) else None


def _date(v: Any) -> Optional[date]:
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    if isinstance(v, str):
        t = normalize_nepali_digits(v).strip()
        m = re.fullmatch(r"(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})", t)
        if m:
            try:
                return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            except ValueError:
                return None
    return None


def _rows(ws, names: List[str]) -> Tuple[Optional[Dict[str, int]], List[Tuple[int, Dict[str, Any]]]]:
    """(header positions or None when a column is missing, the data rows as {name: value} with their sheet row number)."""
    it = ws.iter_rows(values_only=True)
    header = next(it, None)
    if header is None:
        return None, []
    pos = {str(h).strip(): i for i, h in enumerate(header) if h is not None}
    if any(n not in pos for n in names):
        return None, []
    out = []
    for r, row in enumerate(it, 2):
        if r > MAX_ROWS + 1:
            break
        out.append((r, {n: (row[pos[n]] if pos[n] < len(row) else None) for n in names}))
    return pos, out


def read_workbook(data: bytes, assigned: Dict[Tuple[int, str], dict], existing_counts: Optional[Dict[Tuple[int, str], int]] = None,
                  parts_by_species: Optional[Dict[str, List[str]]] = None, today: Optional[date] = None) -> Dict[str, Any]:
    """Check an uploaded form against the design.

    ``assigned``: {(plot_number, species_key): anything} -- the pairs the design allows.
    ``existing_counts``: {(plot_number, species_key): count_total} already stored, so a weight can be entered in a later upload than its count.
    ``parts_by_species``: species_key -> its Schedule-7 group codes, for the default part of a weight.

    Returns ``{"observations": [...], "weights": [...], "findings": [...], "ok": bool}``. ``ok`` is False when there is any error.
    """
    today = today or date.today()
    existing_counts = existing_counts or {}
    parts_by_species = parts_by_species or {}
    findings: List[Dict[str, Any]] = []
    try:
        wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except Exception:  # noqa: BLE001 -- any reader failure is "not a workbook"; the user gets one plain finding
        return {"observations": [], "weights": [], "ok": False, "findings": [_finding("error", "", None, None, "file.corrupt", "The file is not a readable .xlsx workbook.")]}
    if PLOTS not in wb.sheetnames:
        return {"observations": [], "weights": [], "ok": False, "findings": [_finding("error", "", None, None, "sheet.missing", f"The sheet '{PLOTS}' is missing. Use the form from this page.")]}

    pos, rows = _rows(wb[PLOTS], ["plot_number", "species_key"] + PLOT_ENTRY)
    if pos is None:
        return {"observations": [], "weights": [], "ok": False, "findings": [_finding("error", PLOTS, 1, None, "columns.missing", "A column of the form is missing or renamed. Use the form from this page.")]}

    observations: List[Dict[str, Any]] = []
    seen: set = set()
    counts_in_file: Dict[Tuple[int, str], int] = {}
    for r, row in rows:
        entry = {k: row[k] for k in PLOT_ENTRY}
        if all(_blank(v) for v in entry.values()):
            continue  # not surveyed yet
        plot, key = _whole(row["plot_number"]), str(row["species_key"] or "").strip()
        if plot is None or (plot, key) not in assigned:
            findings.append(_finding("error", PLOTS, r, "species_key", "pair.unknown", f"Plot {row['plot_number']} with '{key}' is not in the design: do not change the grey cells."))
            continue
        if (plot, key) in seen:
            findings.append(_finding("error", PLOTS, r, "plot_number", "pair.duplicate", f"Plot {plot} and '{key}' appear twice."))
            continue
        seen.add((plot, key))
        obs: Dict[str, Any] = {"plot_number": plot, "species_key": key, "notes": None if _blank(entry["notes"]) else str(entry["notes"]).strip()[:500]}
        bad = False
        for name in COUNT_COLS:
            v = entry[name]
            if _blank(v):
                obs[name] = None
                continue
            n = _whole(v)
            if n is None or n < 0 or n > MAX_COUNT:
                findings.append(_finding("error", PLOTS, r, name, "count.invalid", f"'{v}' is not a whole number between 0 and {MAX_COUNT:,}."))
                bad = True
            else:
                obs[name] = n
        d = None
        if not _blank(entry["visit_date"]):
            d = _date(entry["visit_date"])
            if d is None:
                findings.append(_finding("error", PLOTS, r, "visit_date", "date.invalid", f"'{entry['visit_date']}' is not a date (use year-month-day)."))
                bad = True
            elif d > today:
                findings.append(_finding("error", PLOTS, r, "visit_date", "date.future", f"{d.isoformat()} is in the future."))
                bad = True
        obs["visit_date"] = d.isoformat() if d else None
        if not bad:
            tot, mat, sm = obs.get("count_total"), obs.get("count_mature"), obs.get("count_small")
            if tot is None:
                findings.append(_finding("error", PLOTS, r, "count_total", "count.total_missing", "A row with other entries needs the total count (0 if the species is absent)."))
                bad = True
            elif mat is not None and sm is not None and mat + sm > tot:
                findings.append(_finding("error", PLOTS, r, "count_mature", "count.parts_exceed_total", f"Mature ({mat}) + small ({sm}) is more than the total ({tot})."))
                bad = True
            elif (mat is not None and mat > tot) or (sm is not None and sm > tot):
                findings.append(_finding("error", PLOTS, r, "count_mature", "count.parts_exceed_total", "Mature or small is more than the total."))
                bad = True
            if not bad and obs.get("visit_date") is None:
                findings.append(_finding("warning", PLOTS, r, "visit_date", "date.missing", "No visit date."))
        if not bad:
            counts_in_file[(plot, key)] = obs["count_total"]
            observations.append(obs)

    weights: List[Dict[str, Any]] = []
    if WEIGHTS in wb.sheetnames:
        wpos, wrows = _rows(wb[WEIGHTS], WEIGHT_COLS)
        if wpos is None:
            findings.append(_finding("error", WEIGHTS, 1, None, "columns.missing", "A column of the Weights sheet is missing or renamed."))
        else:
            next_no: Dict[Tuple[int, str], int] = {}
            used: set = set()
            for r, row in wrows:
                if all(_blank(row[k]) for k in ("fresh_weight_g", "dry_weight_g", "sample_no", "notes")) and _blank(row["part"]):
                    continue
                plot, key = _whole(row["plot_number"]), str(row["species_key"] or "").strip()
                if plot is None or (plot, key) not in assigned:
                    findings.append(_finding("error", WEIGHTS, r, "species_key", "pair.unknown", f"Plot {row['plot_number']} with '{key}' is not in the design."))
                    continue
                count = counts_in_file.get((plot, key), existing_counts.get((plot, key)))
                if count is None:
                    findings.append(_finding("error", WEIGHTS, r, "plot_number", "weight.no_count", f"Plot {plot}, '{key}': enter the count on the Plots sheet before its weights."))
                    continue
                if count < 1:
                    findings.append(_finding("error", WEIGHTS, r, "plot_number", "weight.zero_count", f"Plot {plot}, '{key}' has a count of 0: there is nothing to weigh."))
                    continue
                fresh, dry = _number(row["fresh_weight_g"]), _number(row["dry_weight_g"])
                bad = False
                if _blank(row["fresh_weight_g"]) or fresh is None or fresh <= 0 or fresh > MAX_WEIGHT_G:
                    findings.append(_finding("error", WEIGHTS, r, "fresh_weight_g", "weight.fresh_invalid", f"The fresh weight '{row['fresh_weight_g']}' must be a number of grams above 0."))
                    bad = True
                if not _blank(row["dry_weight_g"]):
                    if dry is None or dry < 0 or dry > MAX_WEIGHT_G:
                        findings.append(_finding("error", WEIGHTS, r, "dry_weight_g", "weight.dry_invalid", f"The dry weight '{row['dry_weight_g']}' must be a number of grams, 0 or more."))
                        bad = True
                    elif fresh is not None and dry > fresh:
                        findings.append(_finding("error", WEIGHTS, r, "dry_weight_g", "weight.dry_exceeds_fresh", f"The dry weight ({dry:g} g) is more than the fresh weight ({fresh:g} g)."))
                        bad = True
                    elif fresh and dry / fresh < 0.02:
                        findings.append(_finding("warning", WEIGHTS, r, "dry_weight_g", "weight.dry_very_low", "Less than 2 % of the fresh weight is left after drying: check the weights."))
                part = None
                if not _blank(row["part"]):
                    part = next((g for g, (ne, _en) in GROUPS.items() if str(row["part"]).strip() in (g, ne, ne.replace(" जाति", ""))), None)
                    if part is None:
                        findings.append(_finding("error", WEIGHTS, r, "part", "part.unknown", f"'{row['part']}' is not a part (choose from the list)."))
                        bad = True
                else:
                    groups = parts_by_species.get(key) or []
                    part = groups[0] if groups else None
                no = _whole(row["sample_no"]) if not _blank(row["sample_no"]) else None
                if not _blank(row["sample_no"]) and (no is None or no < 1):
                    findings.append(_finding("error", WEIGHTS, r, "sample_no", "sample.invalid", "The sample number is a whole number from 1."))
                    bad = True
                if bad:
                    continue
                if no is None:
                    no = next_no.get((plot, key), 0) + 1
                next_no[(plot, key)] = max(next_no.get((plot, key), 0), no)
                if (plot, key, no) in used:
                    findings.append(_finding("error", WEIGHTS, r, "sample_no", "sample.duplicate", f"Sample {no} of plot {plot}, '{key}' appears twice."))
                    continue
                used.add((plot, key, no))
                weights.append({"plot_number": plot, "species_key": key, "sample_no": no, "part_group": part, "fresh_weight_g": fresh,
                                "dry_weight_g": dry, "notes": None if _blank(row["notes"]) else str(row["notes"]).strip()[:500]})
    wb.close()
    return {"observations": observations, "weights": weights, "findings": findings, "ok": not any(f["severity"] == "error" for f in findings)}
