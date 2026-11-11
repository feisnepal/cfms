"""The expert review sheet of the provisional method cards: build it, and read the reviewer's answers back (NTFP inventory, owner requirement 2026-10-22).

The sheet lists every card that is not yet expert-confirmed, with the values the system derived and how it derived them, a Yes/No column ("these are right") and
empty columns for corrections. ``read_sheet`` turns the filled sheet into the rows ``ntfp_card_service.apply_review`` takes. Pure: dicts and bytes.
"""
from __future__ import annotations

import io
import re
from typing import Any, Dict, List

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation

CARDS = "Cards"
FIXED = ["species_key", "nepali_name", "scientific_name", "card_status", "parts_harvested", "growth_class_now", "how_growth_class_was_found", "method_now", "plot_m2_now", "individuals_now"]
REVIEW = ["confirmed", "growth_class", "sampling_method", "plot_min_sqm", "plot_max_sqm", "n_individuals_min", "n_individuals_max", "maturity", "conversion_factor",
          "sample_fraction_pct", "aah_pct_min", "aah_pct_max", "procedure"]
GROWTH = ["tree", "shrub", "climber", "herb", "fungus", "lichen"]
METHODS = ["destructive", "semi_destructive", "non_destructive"]
_GREY = PatternFill("solid", fgColor="FFE7E7E7")
_YELLOW = PatternFill("solid", fgColor="FFFFF4CC")
_HEAD = PatternFill("solid", fgColor="FF2E7D32")

HELP = {
    "confirmed": "Yes if the grey values are right for this species as they stand. Leave empty if you correct something (the corrected cells are then confirmed).",
    "growth_class": "tree, shrub, climber, herb, fungus or lichen. Fill only to correct.", "sampling_method": "destructive (the plant is lifted), semi_destructive (part is taken from the living plant) or non_destructive.",
    "plot_min_sqm": "Smallest sample plot, m2.", "plot_max_sqm": "Largest sample plot, m2.", "n_individuals_min": "Fewest individuals to weigh.", "n_individuals_max": "Most individuals to weigh.",
    "maturity": "The sign that the plant (or part) is ready to harvest.", "conversion_factor": "Dry weight / fresh weight, between 0 and 1.",
    "sample_fraction_pct": "Share of the part taken from a sampled plant to weigh it (not a harvest limit).", "aah_pct_min": "Annual allowable harvest, % of the stock (lower end).",
    "aah_pct_max": "Annual allowable harvest, % (upper end, if a range).", "procedure": "One or two sentences for the field team.",
}


def build_sheet(cards: List[Dict[str, Any]], sources: List[Dict[str, Any]]) -> bytes:
    """``cards``: ``[{species_key, nepali_name, scientific_name, card_status, parts_harvested, growth_class, growth_how, sampling_method, plot, individuals}]``."""
    wb = Workbook()
    ws = wb.active
    ws.title = CARDS
    ws.append(FIXED + REVIEW)
    for i, name in enumerate(FIXED + REVIEW, 1):
        c = ws.cell(1, i)
        c.font, c.fill, c.alignment = Font(bold=True, color="FFFFFFFF"), _HEAD, Alignment(wrap_text=True, vertical="center")
        ws.column_dimensions[get_column_letter(i)].width = 16
    for c in cards:
        ws.append([c["species_key"], c["nepali_name"], c["scientific_name"], c["card_status"], c.get("parts_harvested", ""), c["growth_class"], c.get("growth_how", ""),
                   c["sampling_method"], c.get("plot", ""), c.get("individuals", "")] + [None] * len(REVIEW))
    for r in range(2, ws.max_row + 1):
        for i in range(1, len(FIXED) + 1):
            ws.cell(r, i).fill = _GREY
        for i in range(len(FIXED) + 1, len(FIXED) + len(REVIEW) + 1):
            ws.cell(r, i).fill = _YELLOW
    col = {n: get_column_letter(i) for i, n in enumerate(FIXED + REVIEW, 1)}
    last = max(ws.max_row, 2)
    for name, options in (("confirmed", ["Yes", "No"]), ("growth_class", GROWTH), ("sampling_method", METHODS)):
        dv = DataValidation(type="list", formula1='"' + ",".join(options) + '"', allow_blank=True)
        ws.add_data_validation(dv)
        dv.add(f"{col[name]}2:{col[name]}{last}")
    for name in REVIEW:
        if name in HELP:
            from openpyxl.comments import Comment

            ws[f"{col[name]}1"].comment = Comment(HELP[name], "NTFP")
    ws.freeze_panes = "C2"
    ws.column_dimensions[col["how_growth_class_was_found"]].width = 46
    ws.column_dimensions[col["procedure"]].width = 50
    ws.auto_filter.ref = ws.dimensions

    wsrc = wb.create_sheet("Sources")
    wsrc.append(["key", "title", "publisher", "year", "read_status", "url", "licence"])
    for s in sources:
        wsrc.append([s["key"], s["title"], s["publisher"], s["year"], s["read_status"], s["url"], s["licence"]])
    for i, w in enumerate([16, 70, 36, 12, 11, 60, 40], 1):
        wsrc.column_dimensions[get_column_letter(i)].width = w

    wh = wb.create_sheet("How to review")
    for line in [
        "NTFP method cards: expert review", "",
        "Every card here was made by rules from the growth form and the part harvested, not from a document about that species. A reviewer who knows the plant",
        "confirms it or corrects it. The grey columns are what the system derived and how; the yellow columns are yours.", "",
        "1. Row right as it stands: write Yes in 'confirmed' and leave the rest empty.",
        "2. Something wrong: fill only the cells you correct (leave 'confirmed' empty). Corrected cells become expert-confirmed values; the rest stay as derived.",
        "3. Leave a row empty if you cannot judge it: it stays provisional.", "",
        "The 'how_growth_class_was_found' column matters most: 'guessed from the part harvested' means the system had no better information.",
        "Return the file to the person who runs scripts/import_ntfp_card_review.py with your name; your name is recorded on every value you confirmed.",
    ]:
        wh.append([line])
    wh["A1"].font = Font(bold=True, size=13)
    wh.column_dimensions["A"].width = 150
    wb.active = 0
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def read_sheet(data: bytes) -> List[Dict[str, Any]]:
    """The reviewer's rows: only rows with a 'confirmed' answer or any correction. Raises ValueError for a file that is not the review sheet."""
    try:
        wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except Exception as exc:  # noqa: BLE001 -- any reader failure means "not a workbook"
        raise ValueError("The file is not a readable .xlsx workbook.") from exc
    if CARDS not in wb.sheetnames:
        raise ValueError(f"The sheet '{CARDS}' is missing.")
    it = wb[CARDS].iter_rows(values_only=True)
    header = [str(h).strip() if h is not None else "" for h in next(it, [])]
    need = ["species_key"] + REVIEW
    if any(n not in header for n in need):
        raise ValueError("A column of the review sheet is missing or renamed.")
    pos = {n: header.index(n) for n in need}
    rows: List[Dict[str, Any]] = []
    for r in it:
        row = {n: (r[i] if i < len(r) else None) for n, i in pos.items()}
        if not row["species_key"]:
            continue
        row = {k: (v.strip() if isinstance(v, str) else v) for k, v in row.items()}
        if any(row[n] not in (None, "") for n in REVIEW):
            rows.append(row)
    return rows


def card_rows(profiles: List[Any], values_by_key: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    """The sheet rows for the PROVISIONAL cards (documented cards come from a document; confirmed ones are done), the least certain growth class first."""
    out = []
    for p in profiles:
        if not p.has_method_card or p.card_status != "provisional":
            continue
        how = (values_by_key.get(p.species_key) or {}).get("growth_class") or ""
        lo, hi = p.plot_min_sqm, p.plot_max_sqm
        n_lo, n_hi = p.n_individuals_min, p.n_individuals_max
        out.append({
            "species_key": p.species_key, "nepali_name": p.nepali_name, "scientific_name": p.scientific_name, "card_status": p.card_status, "parts_harvested": p.part_ne or "",
            "growth_class": p.growth_class, "growth_how": how, "sampling_method": p.sampling_method,
            "plot": (f"{float(lo):g}" if lo == hi else f"{float(lo):g}-{float(hi):g}") if lo is not None and hi is not None else "",
            "individuals": (f"{n_lo}" if n_lo == n_hi or n_hi is None else f"{n_lo}-{n_hi}") if n_lo is not None else "",
        })
    out.sort(key=lambda c: (("guessed" not in c["growth_how"]), c["species_key"]))
    return out
