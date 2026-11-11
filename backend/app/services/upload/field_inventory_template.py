"""The field-inventory Excel template: the Tree Model / Field-inventory workbook, empty (owner, 2026-10-13).

It is built from the SAME column list (``tree_distribution.TREE_MODEL_COLUMNS``) and the SAME validation step (``excel_validator.add_validation_to_excel``) the
"Tree distribution" export uses, so the template and the export cannot drift apart. What the template adds:

* the coordinate columns of every Excel template (system, X, Y typed by the user; longitude / latitude / declared system calculated, hidden ``Convert`` sheet);
* a grey example row instead of data, header comments, and one ``Guideline`` sheet (procedure, columns, things to remember, saving, and the numeric limits
  that used to sit in ``VALIDATION_GUIDE``);
* the species list, read fresh from ``tree_species_coefficients`` each time (it changes; a copy in a file would go stale).

No trees, and no Volumes sheet: those belong to an export, not to a form to be filled.
"""
from __future__ import annotations

import io
import os
import tempfile
from typing import List

from openpyxl import Workbook, load_workbook
from openpyxl.formatting.rule import FormulaRule
from openpyxl.styles import Alignment, Font
from openpyxl.utils import get_column_letter

from . import excel_rules as xr
from . import utm_sheet as us
from .templates import (CRS_COLUMN, EXAMPLE_NOTE, _EXAMPLE, _HEADER, _REQUIRED, Col, Table, _coordinate_flags, _epsg_validation, _guideline_sheet,
                        _header_comment)

SHEET = "Data"
YIELD_COLUMNS = ("firewood_kg_per_100sqm_per_year", "grass_kg_per_100sqm_per_year", "bedding_material_kg_per_100sqm_per_year", "ntfp_kg_per_100sqm_per_year")
REQUIRED = {"block_name", "sample_plot_number", us.INPUT_EPSG, us.X_COL, us.Y_COL, *YIELD_COLUMNS}
CALCULATED = ("longitude", "latitude", CRS_COLUMN)
EXAMPLE = {
    "fid": 1, "block_name": "B1", "sample_plot_number": 1, us.INPUT_EPSG: 4326, us.X_COL: 85.56, us.Y_COL: 27.405,
    "regen_sn": 1, "regen_species_scientific": EXAMPLE_NOTE, "regen_dbh": 2.1, "regen_count": 3,
    "sapling_sn": 1, "sapling_species_scientific": "Bombax ceiba", "sapling_dbh_cm": 5.5, "sapling_count": 2,
    "pole_sn": 1, "pole_species_scientific": "Shorea robusta", "pole_dbh_cm": 18.5, "pole_height_m": 11, "pole_class": 2,
    "tree_sn": 1, "tree_species_scientific": 18, "tree_dbh_cm": 45.5, "tree_height_m": 18.5, "tree_class": 1,  # 18 = the species code of Shorea robusta
    YIELD_COLUMNS[0]: 50, YIELD_COLUMNS[1]: 50, YIELD_COLUMNS[2]: 50, YIELD_COLUMNS[3]: 1,
}


def columns() -> List[str]:
    """The Tree Model columns with longitude / latitude replaced by the typed system, X, Y and the calculated longitude, latitude, declared system."""
    from app.services.tree_distribution import TREE_MODEL_COLUMNS

    out: List[str] = []
    for name in TREE_MODEL_COLUMNS:
        if name == "longitude":
            out += [us.INPUT_EPSG, us.X_COL, us.Y_COL, "longitude", "latitude", CRS_COLUMN]
        elif name == "latitude":
            continue
        else:
            out.append(name)
    return out


def guideline_table(names: List[str]) -> Table:
    return Table(
        "03_Field_Inventory", "Field inventory", [Col(n, EXAMPLE.get(n), n in REQUIRED) for n in names],
        ["One row per measured plant. Rows of the same sample plot repeat the block, plot number and coordinates.",
         "Enter the four yield columns (firewood, grass, bedding material, NTFP) ONCE per sample plot, on its first row: they are used for demand and supply.",
         "Species: the scientific name is preferred; a local name or the species code (1-23) is also read, and shown as a scientific name after upload.",
         "Species cells turn GREEN when found in the list and RED when not; Excel asks 'keep it?' and lets you keep a name that is not in the list."],
        title_ne="क्षेत्र इन्भेन्टरी",
        purpose="Plot measurements: regeneration, sapling, pole and tree species, diameter, height and yields (the layout the Tree distribution model exports).",
        purpose_ne="प्लट मापन: पुनरुत्पादन, लाथ्रा, खाँवा र रुखको प्रजाति, व्यास, उचाइ र उत्पादन (ट्री डिस्ट्रिब्युसन मोडेलले निर्यात गर्ने ढाँचा)।",
    )


def build_field_inventory_workbook(db) -> bytes:
    from app.services.excel_validator import add_validation_to_excel

    names = columns()
    table = guideline_table(names)
    col_letter = {n: get_column_letter(i) for i, n in enumerate(names, start=1)}
    by_name = {c.name: c for c in table.columns}

    wb = Workbook()
    ws = wb.active
    ws.title = SHEET
    for i, n in enumerate(names, start=1):
        c = ws.cell(row=1, column=i, value=n)
        c.font, c.alignment = Font(bold=True, color="FFFFFFFF"), Alignment(horizontal="center", vertical="center")
        c.fill = _REQUIRED if n in REQUIRED else _HEADER
        c.comment = _header_comment(table, by_name[n])
        ws.column_dimensions[get_column_letter(i)].width = 15
        if n in EXAMPLE:
            cell = ws.cell(row=2, column=i, value=EXAMPLE[n])
            cell.fill, cell.font = _EXAMPLE, Font(italic=True, color="FF888888")
    ws.column_dimensions["A"].hidden = True  # fid, as in the export
    ws.freeze_panes = "D2"
    ws.cell(row=4, column=2, value="Row 2 is an example: delete it before you upload. / पङ्क्ति २ उदाहरण हो: अपलोड गर्नुअघि हटाउनुहोस्।").font = Font(
        italic=True, color="FFAA0000", size=9)

    fd, path = tempfile.mkstemp(suffix=".xlsx")
    os.close(fd)
    try:
        wb.save(path)
        add_validation_to_excel(path, db)  # numeric rules, class lists, species checks, SPECIES_DATABASE (fresh from the table), VALIDATION_GUIDE
        with open(path, "rb") as fh:
            wb = load_workbook(io.BytesIO(fh.read()))  # from memory: Windows will not delete a file a workbook still holds open
    finally:
        os.unlink(path)
    ws = wb[SHEET]

    # calculated columns, with the same grey fill and red flags as the other Excel templates
    last = xr.MIN_VALIDATED_ROWS
    lets = {n: col_letter[n] for n in (us.INPUT_EPSG, us.X_COL, us.Y_COL)}
    for r in range(2, us.ROWS + 2):
        f = us.data_formulas(r, lets)
        ws[f"{col_letter['longitude']}{r}"], ws[f"{col_letter['latitude']}{r}"] = f["longitude"], f["latitude"]
        ws[f"{col_letter[CRS_COLUMN]}{r}"] = f'=IF(ISNUMBER({col_letter["longitude"]}{r}),4326,"")'
        for n in CALCULATED:
            ws[f"{col_letter[n]}{r}"].fill = us.CALCULATED_FILL
    ws.add_data_validation(_epsg_validation(col_letter[us.INPUT_EPSG], last))
    _coordinate_flags(ws, col_letter["longitude"], col_letter["latitude"], col_letter[CRS_COLUMN], last)
    ws.conditional_formatting.add(
        f"{lets[us.INPUT_EPSG]}2:{lets[us.INPUT_EPSG]}{last}",
        FormulaRule(formula=[f"AND(ISNUMBER({lets[us.X_COL]}2),LEN({lets[us.INPUT_EPSG]}2)=0)"], fill=xr.RED))

    # one guideline: the template's, then the numeric limits that VALIDATION_GUIDE carried
    _guideline_sheet(wb, table)
    guide, limits = wb["Guideline"], wb["VALIDATION_GUIDE"]
    guide.append(["NUMERIC LIMITS AND COLOURS  /  संख्यात्मक सीमा र रङ", ""])
    guide.cell(row=guide.max_row, column=1).font = Font(bold=True, size=11, color="FF1B4D1F")
    for a, b in limits.iter_rows(min_row=2, values_only=True):
        if a or b:
            guide.append([a, b])
            for col in (1, 2):
                guide.cell(row=guide.max_row, column=col).alignment = Alignment(wrap_text=True, vertical="top")
    wb.remove(limits)
    us.add_convert_sheet(wb, lets)
    wb._sheets.sort(key=lambda s: {SHEET: 0, "Guideline": 1}.get(s.title, 2))  # visible sheets first, the hidden ones after
    wb["SPECIES_DATABASE"].sheet_state = "hidden"
    wb.active = 0
    bio = io.BytesIO()
    wb.save(bio)
    return bio.getvalue()
