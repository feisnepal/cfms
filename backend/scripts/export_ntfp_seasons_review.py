"""Write the DRAFT NTFP harvest-season review sheet (NTFP_seasons_review_DRAFT.xlsx) from ``app.core.ntfp_seasons``.

The reviewer confirms or corrects the season words (the one thing a machine cannot check); the altitude and Latin-name columns are already
checked against the guideline's text layer and are there for orientation.

    python scripts/export_ntfp_seasons_review.py [output.xlsx]
"""
import glob
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from openpyxl import Workbook  # noqa: E402
from openpyxl.styles import Alignment, Font, PatternFill  # noqa: E402
from openpyxl.worksheet.datavalidation import DataValidation  # noqa: E402

from app.core import ntfp_seasons as ns  # noqa: E402
from app.core.ntfp_methods import profiles  # noqa: E402
from app.core.ntfp_schedule7 import GROUPS, designated_entries  # noqa: E402

PDF = r"D:\forest_management\testData\Document\NTFP_survey.pdf"
DEFAULT_OUT = r"D:\forest_management\NTFP_seasons_review_DRAFT.xlsx"
_DIGITS = str.maketrans(")!@#$%^&*(", "0123456789")
TABLE_TITLES = {
    "T5": "Table 5: roots, tubers and rhizomes (pp. 19-20)", "T7": "Table 7: leaf (p. 24)",
    "T10": "Table 10: bark (p. 28)", "T13": "Table 13: fruit, flower, seed, fluff (pp. 31-32)",
}
PAGES = {"T5": (29, 30), "T7": (34,), "T10": (38,), "T13": (41, 42)}  # pdf page = printed + 10


def _altitude_checks() -> dict:
    """table -> set of (min, max) ranges found in the PDF text layer; empty when the PDF cannot be read."""
    if not os.path.exists(PDF):
        return {}
    from pypdf import PdfReader

    pages = [p.extract_text() or "" for p in PdfReader(PDF).pages]
    out = {}
    for table, nums in PAGES.items():
        found = set()
        for n in nums:
            text = pages[n - 1].translate(_DIGITS)
            found |= {(int(a), int(b)) for a, b in re.findall(r"(?<!\d)(\d{3,4})\s*[\u2013\u2014\-\ufffd]\s*(\d{3,4})(?!\d)", text)}
        out[table] = found
    return out


def main(out_path: str) -> None:
    keys = {p["species_key"] for p in profiles()}
    alt = _altitude_checks()
    wb = Workbook()
    ws = wb.active
    ws.title = "Seasons"
    head = ["Table", "Page", "No.", "Nepali name", "Scientific name", "Altitude from (m)", "Altitude to (m)", "Altitude checked against the PDF",
            "Life form", "Part", "Schedule-7 group", "Season AS PRINTED", "Read as: from (month no.)", "to", "2nd season from", "2nd to",
            "Months covered", "In the system's NTFP profiles?", "On Schedule-7?", "REVIEW: season correct? (Yes / No)", "REVIEW: correct season, or comment"]
    ws.append(head)
    for c in ws[1]:
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor="2F5D50")
        c.alignment = Alignment(wrap_text=True, vertical="center")
    for r in ns.seasons():
        rng = r["ranges"]
        second = rng[1] if len(rng) > 1 else (None, None)
        covered = ", ".join(ns.MONTHS_EN[m - 1] for m in r["months"])
        in_alt = (r["altitude_min_m"], r["altitude_max_m"]) in alt.get(r["table"], set()) if alt else None
        sci = re.sub(r"\s+sp\.?$", " spp.", r["scientific_name"])
        ws.append([
            TABLE_TITLES[r["table"]], r["page"], r["serial"], r["nepali_name"], r["scientific_name"], r["altitude_min_m"], r["altitude_max_m"],
            "yes" if in_alt else ("NO: check" if in_alt is False else "PDF not available"), r["life_form_ne"], r["part_ne"],
            f"{r['part_group']} ({GROUPS[r['part_group']][1]})", r["season_ne"], rng[0][0], rng[0][1], second[0], second[1], covered,
            "yes" if r["species_key"] in keys else "no (a profile can be added)", "yes" if designated_entries(sci) else "no", None, None,
        ])
    widths = [34, 6, 5, 22, 32, 10, 10, 16, 16, 18, 22, 22, 11, 6, 11, 6, 30, 22, 12, 22, 40]
    for i, w in enumerate(widths, 1):
        ws.column_dimensions[ws.cell(1, i).column_letter].width = w
    ws.row_dimensions[1].height = 48
    ws.freeze_panes = "E2"
    ws.auto_filter.ref = ws.dimensions
    dv = DataValidation(type="list", formula1='"Yes,No"', allow_blank=True)
    ws.add_data_validation(dv)
    dv.add(f"T2:T{ws.max_row}")
    for row in ws.iter_rows(min_row=2, min_col=20, max_col=21):
        for c in row:
            c.fill = PatternFill("solid", fgColor="FFF4CC")

    guide = wb.create_sheet("How to review")
    for line in [
        "NTFP harvest seasons: DRAFT for review (not used by the system yet)",
        "",
        "Source: NTFP Resource Survey Guideline 2069 (Department of Forests), the season tables 5, 7, 10 and 13. 47 rows.",
        "",
        "What to do",
        "1. Open each page of the guideline named in column B (printed page number; the PDF page is 10 higher).",
        "2. Compare the 'Season AS PRINTED' column (L) with the guideline's season column for that species.",
        "3. Check 'Read as': months are Bikram Sambat numbers, 1 = Baishakh ... 12 = Chaitra. A range that passes Chaitra wraps (Magh-Baishakh = 10 to 1).",
        "4. In column T choose Yes if the season is right, or No and write the correct season (as printed words) in column U.",
        "",
        "Already machine-checked (no need to review): the altitude ranges and the scientific names, against the guideline's text.",
        "Not checked by a machine: the season words themselves. That is the whole purpose of this sheet.",
        "",
        "Spelling variants found in the guideline (all mean the same month): Asoj / Aaswin / Asoj; Bhadau / Bhadra; Shrawan / Saun; Jeth / Jestha;",
        "Baishakh / Waishakh; Poush / Pus; Chait / Chaitra.",
        "",
        "Note: the guideline's Table 7 gives Gaultheria fragrantissima two seasons (Chait-Jeth and Bhadau-Kartik): they are columns M-P.",
        "Species with 'no' in column R have no NTFP profile yet; the season is kept so a profile can be added later.",
    ]:
        guide.append([line])
    guide["A1"].font = Font(bold=True, size=13)
    guide["A5"].font = Font(bold=True)
    guide.column_dimensions["A"].width = 130
    wb.save(out_path)
    print(f"wrote {out_path}: {ws.max_row - 1} rows")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else DEFAULT_OUT)
