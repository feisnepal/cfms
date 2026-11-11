"""UTM -> WGS 84 inside the Excel templates (owner, 2026-10-13).

A team that surveyed in UTM types its easting / northing and names the zone; the sheet itself turns them into the longitude / latitude the system stores.
Nothing is typed twice and nothing has to be converted by hand.

Layout of a coordinate template (Excel only; the CSV templates keep their plain columns and the declared-system check):

* ``input_coordinate_system_epsg`` (4326 / 32644 / 32645), ``x_easting`` and ``y_northing`` are typed by the user (degrees or metres, as the system says);
* ``longitude`` and ``latitude`` are FORMULAS: the typed numbers for 4326, otherwise the answer of the hidden ``Convert`` sheet;
* ``coordinate_system_epsg`` is a formula, always 4326 once there is a point: what the importer reads is therefore always degrees, declared as such.

The ``Convert`` sheet (hidden) holds the constants of the inverse transverse-Mercator series (Kruger, third order: well under a millimetre inside a UTM zone)
and one row of working per data row. Rows are looked up with ``INDEX(..., ROW())`` and never by fixed address, so deleting the example row does not break
a single reference. Only functions every spreadsheet has are used (SIN, COS, SINH, COSH, ASIN, ATAN, DEGREES), so it also works in LibreOffice and Google Sheets.
"""
from __future__ import annotations

import math
from typing import Dict

from openpyxl.styles import Font, PatternFill

SHEET = "Convert"
INPUT_EPSG = "input_coordinate_system_epsg"
X_COL, Y_COL = "x_easting", "y_northing"
ZONE_CENTRAL_MERIDIAN = {32644: 81, 32645: 87}  # degrees east
ROWS = 5000  # data rows served; the same depth as the validation

_A = 6378137.0
_F = 1 / 298.257223563
_N = _F / (2 - _F)
K0 = 0.9996
AHAT = _A / (1 + _N) * (1 + _N ** 2 / 4 + _N ** 4 / 64)
BETA = (_N / 2 - 2 * _N ** 2 / 3 + 37 * _N ** 3 / 96, _N ** 2 / 48 + _N ** 3 / 15, 17 * _N ** 3 / 480)
DELTA = (2 * _N - 2 * _N ** 2 / 3 - 2 * _N ** 3, 7 * _N ** 2 / 3 - 8 * _N ** 3 / 5, 56 * _N ** 3 / 15)

# constants live in Convert!N1:N8
_CONSTANTS = [("k0", K0), ("Ahat", AHAT), ("beta1", BETA[0]), ("beta2", BETA[1]), ("beta3", BETA[2]), ("delta1", DELTA[0]), ("delta2", DELTA[1]), ("delta3", DELTA[2])]


def row_formulas(r: int) -> Dict[str, str]:
    """The working of one Convert row, as Excel formulas (column letter -> formula). A-D read the Data sheet; E-K are pure arithmetic."""
    return {
        "E": f"=C{r}/($N$1*$N$2)",
        "F": f"=(B{r}-500000)/($N$1*$N$2)",
        "G": f"=E{r}-($N$3*SIN(2*E{r})*COSH(2*F{r})+$N$4*SIN(4*E{r})*COSH(4*F{r})+$N$5*SIN(6*E{r})*COSH(6*F{r}))",
        "H": f"=F{r}-($N$3*COS(2*E{r})*SINH(2*F{r})+$N$4*COS(4*E{r})*SINH(4*F{r})+$N$5*COS(6*E{r})*SINH(6*F{r}))",
        "I": f"=ASIN(SIN(G{r})/COSH(H{r}))",
        "J": f"=DEGREES(I{r}+$N$6*SIN(2*I{r})+$N$7*SIN(4*I{r})+$N$8*SIN(6*I{r}))",
        "K": f"=D{r}+DEGREES(ATAN(SINH(H{r})/COS(G{r})))",
    }


def add_convert_sheet(wb, letters: Dict[str, str]) -> None:
    """Add the hidden sheet. ``letters`` maps the Data column names (INPUT_EPSG, X_COL, Y_COL) to their letters."""
    ws = wb.create_sheet(SHEET)
    head = Font(bold=True)
    for col, text in zip("ABCDEFGHIJK", ("input epsg", "x", "y", "central meridian", "xi", "eta", "xi'", "eta'", "chi", "latitude", "longitude")):
        ws[f"{col}1"] = text
        ws[f"{col}1"].font = head
    for i, (name, value) in enumerate(_CONSTANTS, start=1):  # the formulas address the values at N1:N8; the names sit beside them
        ws[f"N{i}"] = value
        ws[f"O{i}"] = name
    ws["Q1"] = "Working sheet for the Data sheet (WGS 84 / UTM, inverse transverse Mercator). Do not edit."
    ex, ey, ep = letters[X_COL], letters[Y_COL], letters[INPUT_EPSG]
    for r in range(2, ROWS + 2):
        ws[f"A{r}"] = f"=INDEX(Data!${ep}:${ep},ROW())"
        ws[f"B{r}"] = f"=INDEX(Data!${ex}:${ex},ROW())"
        ws[f"C{r}"] = f"=INDEX(Data!${ey}:${ey},ROW())"
        ws[f"D{r}"] = f"=IF(A{r}=32644,{ZONE_CENTRAL_MERIDIAN[32644]},{ZONE_CENTRAL_MERIDIAN[32645]})"
        for col, formula in row_formulas(r).items():
            ws[f"{col}{r}"] = formula
    ws.sheet_state = "hidden"


def data_formulas(r: int, letters: Dict[str, str]) -> Dict[str, str]:
    """The Data-sheet formulas of one row: longitude, latitude, coordinate_system_epsg."""
    e, x, y = letters[INPUT_EPSG], letters[X_COL], letters[Y_COL]
    both = f"AND(ISNUMBER({x}{r}),ISNUMBER({y}{r}))"
    lon = f'=IF({both},IF({e}{r}=4326,{x}{r},IFERROR(INDEX({SHEET}!$K:$K,ROW()),"")),"")'
    lat = f'=IF({both},IF({e}{r}=4326,{y}{r},IFERROR(INDEX({SHEET}!$J:$J,ROW()),"")),"")'
    return {"longitude": lon, "latitude": lat}


CALCULATED_FILL = PatternFill("solid", fgColor="FFE3E3E3")


def reference(easting: float, northing: float, epsg: int) -> tuple:
    """(longitude, latitude) by the SAME series, in Python: what the sheet is meant to compute (the tests compare it with PROJ)."""
    xi, eta = northing / (K0 * AHAT), (easting - 500000) / (K0 * AHAT)
    xi2 = xi - sum(b * math.sin(2 * j * xi) * math.cosh(2 * j * eta) for j, b in enumerate(BETA, start=1))
    eta2 = eta - sum(b * math.cos(2 * j * xi) * math.sinh(2 * j * eta) for j, b in enumerate(BETA, start=1))
    chi = math.asin(math.sin(xi2) / math.cosh(eta2))
    phi = chi + sum(d * math.sin(2 * j * chi) for j, d in enumerate(DELTA, start=1))
    lam = ZONE_CENTRAL_MERIDIAN[epsg] + math.degrees(math.atan(math.sinh(eta2) / math.cos(xi2)))
    return lam, math.degrees(phi)
