"""The "Download data template" zip (owner, 2026-10-13): every data type the system reads from Excel or CSV, in one download.

* Excel only (owner, 2026-10-13): dropdowns, limits, red / amber highlighting generated from the shared rule table, a guideline sheet and the UTM conversion.
  The importers still read a plain CSV with the same column names; ``csv_bytes`` gives that header for tests and tools, but no CSV is shipped.
* **Every table with coordinates has a required ``coordinate_system_epsg`` column** (4326 degrees, 32644 UTM 44N, 32645 UTM 45N). The upload reads the
  declared system and checks it against where the numbers actually land (``coordinates.declared_system`` / ``detect_systems``).
* Generic: no forest needed; the household workbook defaults to ropani.
* Nothing is shipped that the system cannot read yet (metadata, biodiversity and unit-vertex templates follow their importers).

Pure openpyxl / csv / zipfile: no database access.
"""
from __future__ import annotations

import csv
import io
import zipfile
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from typing import Callable, Dict, List, Optional, Sequence

from openpyxl import Workbook
from openpyxl.comments import Comment
from openpyxl.formatting.rule import FormulaRule
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation

from . import excel_rules as xr
from . import utm_sheet as us
from .rules import RULES, STEM_DBH, STEM_HEIGHT, range_text

CRS_COLUMN = "coordinate_system_epsg"
SUPPORTED_EPSG = (4326, 32644, 32645)
EXAMPLE_NOTE = "EXAMPLE - delete this row"  # a row left in is flagged by the species / name checks instead of passing silently

_HEADER = PatternFill("solid", fgColor="FF2E7D32")
_REQUIRED = PatternFill("solid", fgColor="FF1B4D1F")
_EXAMPLE = PatternFill("solid", fgColor="FFEEEEEE")


@dataclass
class Col:
    name: str
    example: object = None
    required: bool = False
    note: str = ""


@dataclass
class Table:
    """One template: a data sheet (first, because the importers read the first sheet) and an Instructions sheet."""
    file_stem: str  # e.g. 03_Field_Inventory
    title: str
    columns: List[Col]
    instructions: List[str] = field(default_factory=list)
    lon: Optional[str] = None  # the longitude / easting column, if the table has coordinates
    lat: Optional[str] = None
    numeric: Optional[Callable] = None  # (ws, col_map, last_row) -> adds this table's own validation
    title_ne: str = ""
    purpose: str = ""  # what this file is for, in a sentence (English / Nepali)
    purpose_ne: str = ""

    @property
    def has_coordinates(self) -> bool:
        return self.lon is not None and self.lat is not None


def _epsg_validation(letter: str, last_row: int) -> DataValidation:
    dv = DataValidation(type="list", formula1='"' + ",".join(str(e) for e in SUPPORTED_EPSG) + '"', allow_blank=True, showErrorMessage=True,
                        errorStyle="stop", errorTitle="Coordinate system",
                        error="Enter 4326 (degrees, WGS 84), 32644 (UTM zone 44N) or 32645 (UTM zone 45N).", showInputMessage=True,
                        promptTitle="Coordinate system", prompt="4326 = degrees (WGS 84); 32644 = UTM zone 44N; 32645 = UTM zone 45N. Required on every row.")
    dv.add(f"{letter}2:{letter}{last_row}")
    return dv


def _coordinate_flags(ws, lon: str, lat: str, epsg: str, last_row: int) -> None:
    """RED when the numbers cannot be what the row declares: degrees outside Nepal, metres that are not 6 / 7 digits, or coordinates with no system declared."""
    cells = lambda col: f"{col}2"  # noqa: E731 -- a one-line helper
    rng = lambda col: f"{col}2:{col}{last_row}"  # noqa: E731
    lo, la, ep = cells(lon), cells(lat), f"${epsg}2"
    rules = (
        (lon, f"AND(ISNUMBER({lo}),{ep}=4326,OR({lo}<80,{lo}>88.3))"),
        (lat, f"AND(ISNUMBER({la}),{ep}=4326,OR({la}<26.3,{la}>30.6))"),
        (lon, f"AND(ISNUMBER({lo}),{ep}<>4326,LEN({ep})>0,OR({lo}<100000,{lo}>1000000))"),
        (lat, f"AND(ISNUMBER({la}),{ep}<>4326,LEN({ep})>0,OR({la}<2500000,{la}>3800000))"),
        (lon, f"AND(ISNUMBER({lo}),LEN({ep})=0)"),
        (lat, f"AND(ISNUMBER({la}),LEN({ep})=0)"),
        (epsg, f"AND(ISNUMBER({lo}),LEN({ep})=0)"),
    )
    for col, formula in rules:
        ws.conditional_formatting.add(rng(col), FormulaRule(formula=[formula], fill=xr.RED))


# ── the tables ─────────────────────────────────────────────────────────────────────────────────────────────────────────

def _fi_numeric(ws, col_map: Dict[str, str], last_row: int) -> None:
    xr.apply_numeric_rules(ws, col_map, last_row)


def _stem_numeric(ws, col_map: Dict[str, str], last_row: int) -> None:
    """Stem mapping has one continuous DBH range (1-200 cm, amber above 100) and its own height limits - not the stand classes."""
    for header, rule in (("dia_cm", STEM_DBH), ("height_m", STEM_HEIGHT)):
        letter = col_map.get(header)
        if letter:
            ws.add_data_validation(xr.hard_validation(rule, letter, 2, last_row))
            xr.add_highlighting(ws, letter, rule, 2, last_row)


def _sample_plot_numeric(ws, col_map: Dict[str, str], last_row: int) -> None:
    for header, lo, hi, kind in (("plot_number", 1, 100000, "whole"), ("radius_m", 1, 50, "decimal")):
        letter = col_map.get(header)
        if letter:
            dv = DataValidation(type=kind, operator="between", formula1=str(lo), formula2=str(hi), allow_blank=True, showErrorMessage=True, errorStyle="stop",
                                errorTitle="Not allowed", error=f"{header} must be between {lo} and {hi}.")
            dv.add(f"{letter}2:{letter}{last_row}")
            ws.add_data_validation(dv)


def tables() -> List[Table]:
    walking = ("List the stations in the order you walked them: the system checks each station against the one before and the one after, "
               "and points out one whose digits look mistyped.")
    return [
        Table("01_Forest_Boundary_Stations", "Forest boundary stations",
              [Col("station_no", 1, True), Col("longitude", 85.55, True, "or easting, in the system named in the last column"),
               Col("latitude", 27.41, True, "or northing"), Col(CRS_COLUMN, 4326, True), Col("remark", EXAMPLE_NOTE)],
              [walking, "One row per station. Do not repeat the first station at the end."], lon="longitude", lat="latitude", title_ne="वन सिमानाका स्टेसन", purpose="The boundary of the community forest as a list of survey stations.", purpose_ne="सामुदायिक वनको सिमाना सर्वेक्षण स्टेसनको सूचीका रूपमा।"),
        Table("02_Sample_Plots", "Sample plots",
              [Col("plot_number", 1, True), Col("block_name", "B1", True), Col("longitude", 85.56, True), Col("latitude", 27.405, True),
               Col(CRS_COLUMN, 4326, True), Col("radius_m", 12.62), Col("remark", EXAMPLE_NOTE)],
              ["Use this when the sample plots were prepared in another system and only need to be loaded here.",
               "A field inventory file also carries the plot number and coordinates of every plot; you do not need both."],
              lon="longitude", lat="latitude", numeric=_sample_plot_numeric, title_ne="नमुना प्लट", purpose="The sample plots, when they were prepared in another system and only need to be loaded here.", purpose_ne="अर्को प्रणालीमा तयार पारिएका नमुना प्लट, जुन यहाँ अपलोड मात्र गर्नुपर्छ।"),
        Table("03_Field_Inventory", "Field inventory",
              [Col("block_name", "B1", True), Col("sample_plot_number", 1, True), Col("longitude", 85.56, True), Col("latitude", 27.405, True),
               Col(CRS_COLUMN, 4326, True),
               Col("regen_species_scientific"), Col("regen_dbh"), Col("regen_count"),
               Col("sapling_species_scientific"), Col("sapling_dbh_cm"), Col("sapling_count"),
               Col("pole_species_scientific"), Col("pole_dbh_cm"), Col("pole_height_m"), Col("pole_class"),
               Col("tree_species_scientific", EXAMPLE_NOTE), Col("tree_dbh_cm", 45.5), Col("tree_height_m", 18.5), Col("tree_class", "A"),
               Col("firewood_kg_per_100sqm_per_year", 50, True), Col("grass_kg_per_100sqm_per_year", 50, True),
               Col("bedding_material_kg_per_100sqm_per_year", 50, True), Col("ntfp_kg_per_100sqm_per_year", 1, True)],
              ["One stem (or one regeneration / sapling count) per row; fill only the columns of its stand: regeneration, sapling, pole or tree.",
               "The size classes are fixed: a stem of exactly 30.0 cm is a tree, 10.0 cm a pole. A value in the wrong stand is refused and the system proposes a fix."],
              lon="longitude", lat="latitude", numeric=_fi_numeric, title_ne="क्षेत्र सर्वेक्षण (फिल्ड इन्भेन्टरी)", purpose="The field inventory: regeneration, sapling, pole and tree measurements in each sample plot.", purpose_ne="क्षेत्र सर्वेक्षण: प्रत्येक नमुना प्लटमा पुनरुत्पादन, लाथ्रा, खाँवा र रुखको नाप।"),
        Table("04_Stem_Mapping", "Stem mapping (individual trees)",
              [Col("species", EXAMPLE_NOTE, True), Col("dia_cm", 45.5, True), Col("height_m", 18.5), Col("class", "A"),
               Col("longitude", 85.56, True), Col("latitude", 27.405, True), Col(CRS_COLUMN, 4326, True)],
              [f"Diameter at breast height in cm: {range_text(STEM_DBH)}; the system asks 'is it correct?' above {STEM_DBH.soft_max:g} cm.",
               f"Height in m: {range_text(STEM_HEIGHT)}. Stem mapping does not use the stand classes: any diameter from 1 to 200 cm is a stem."],
              lon="longitude", lat="latitude", numeric=_stem_numeric, title_ne="रुख नक्साङ्कन (स्टेम म्यापिङ)", purpose="Individual trees with their position, diameter and species.", purpose_ne="व्यक्तिगत रुखको स्थान, व्यास र प्रजाति।"),
        Table("06_User_Group_Points", "User group boundary points",
              [Col("point_no", 1, True), Col("longitude", 85.55, True), Col("latitude", 27.41, True), Col(CRS_COLUMN, 4326, True), Col("remark", EXAMPLE_NOTE)],
              [walking, "Only needed when the user group's area is given as points; a GIS file can be loaded with 'Import Layer' instead."],
              lon="longitude", lat="latitude", title_ne="उपभोक्ता समूहका बिन्दु", purpose="The area of the user group as a list of points, when it is not available as a GIS file.", purpose_ne="उपभोक्ता समूहको क्षेत्र GIS फाइलका रूपमा नभए बिन्दुको सूचीका रूपमा।"),
        Table("07_Forest_Metadata", "Forest details",
              [Col("forest_name", EXAMPLE_NOTE, True), Col("group_name", "Example Community Forest User Group"), Col("province", "Bagmati"), Col("district", "Kavrepalanchok"),
               Col("palika", "Example Municipality"), Col("ward", 5), Col("division", "Division Forest Office"), Col("sub_division", "Ilaka Forest Office"),
               Col("cf_national_code", "001/002/03/04/005"), Col("fy_start", "2083/84"), Col("fy_end", "2092/93")],
              ["One row only: a forest has one set of details.", "A detail you leave empty keeps the value already saved; importing never clears one."],
              title_ne="वनको विवरण", purpose="The essentials the plan cover prints: names, location, offices, national code and plan years.",
              purpose_ne="योजनाको आवरणमा छापिने मुख्य विवरण: नाम, ठेगाना, कार्यालय, राष्ट्रिय कोड र योजना वर्ष।"),
    ]


# ── what a user needs to know (English + Nepali), shared by the Guideline sheet, the cell comments and the README ──────────

PROCEDURE = [
    ("Keep the first sheet named 'Data'. Do not rename, move, merge or delete columns, and do not insert new ones.",
     "पहिलो पानाको नाम 'Data' नै राख्नुहोस्। स्तम्भको नाम नफेर्नुहोस्, नसार्नुहोस्, नमिलाउनुहोस् वा नहटाउनुहोस्; नयाँ स्तम्भ नथप्नुहोस्।"),
    ("Delete the grey example row (row 2) and the red note (row 4) before you upload.",
     "अपलोड गर्नुअघि खैरो उदाहरण पङ्क्ति (पङ्क्ति २) र रातो टिप्पणी (पङ्क्ति ४) हटाउनुहोस्।"),
    ("Enter one record per row, starting at row 2 (row 1 is the header). Required columns have a darker header.",
     "प्रत्येक पङ्क्तिमा एउटा अभिलेख, पङ्क्ति २ बाट सुरु (पङ्क्ति १ शीर्षक हो)। अनिवार्य स्तम्भको शीर्षक गाढा हुन्छ।"),
    ("Leave a cell empty when there is no data. Do not type 0, -, NA or N/A for missing data.",
     "तथ्याङ्क नभए कोठा खाली राख्नुहोस्। नभएको तथ्याङ्कका लागि ०, -, NA वा N/A नलेख्नुहोस्।"),
    ("Watch the colours: a RED cell is wrong (outside the allowed range) and will be refused; an AMBER cell is unusual - check it.",
     "रङ हेर्नुहोस्: रातो कोठा गलत हो (अनुमति परिसर बाहिर) र अस्वीकृत हुन्छ; सुन रङ (एम्बर) कोठा असामान्य हो - जाँच्नुहोस्।"),
    ("Save the file (see SAVING THE FILE below), close it in Excel, then drop it into 'Add data'.",
     "फाइल सुरक्षित गर्नुहोस् (तल 'फाइल सुरक्षित गर्ने' हेर्नुहोस्), Excel मा बन्द गर्नुहोस्, अनि 'Add data' मा राख्नुहोस्।"),
    ("If a row is refused, the report names the row. Correct it in your file and upload again.",
     "कुनै पङ्क्ति अस्वीकृत भए रिपोर्टले पङ्क्ति नम्बर देखाउँछ। फाइलमा सच्याएर फेरि अपलोड गर्नुहोस्।"),
]

REMEMBER = [
    ("FILE NAME", "फाइलको नाम",
     "Use letters, digits and underscores only - no spaces or symbols ( / \\ : * ? \" < > | ). Suggested pattern: ForestName_Module_Type_YYYYMMDD, "
     "for example Rambhadevi_FieldInventory_Data_20261015.xlsx (the system names its own exports the same way). Do not change the extension (.xlsx).",
     "अक्षर, अङ्क र अन्डरस्कोर (_) मात्र प्रयोग गर्नुहोस् - खाली ठाउँ वा चिन्ह नराख्नुहोस्। सुझाव गरिएको ढाँचा: वनकोनाम_मोड्युल_प्रकार_वर्षमहिनादिन, "
     "जस्तै Rambhadevi_FieldInventory_Data_20261015.xlsx। एक्सटेन्सन (.xlsx) नफेर्नुहोस्।"),
    ("NUMBERS", "सङ्ख्या",
     "Write numbers with digits only. English digits (123) and Nepali digits (१२३) are both accepted - the system converts them. Do not type units (write 45, not "
     "45 cm) and do not mix letters into a number. Use a point as the decimal mark (27.4105); a decimal comma is read too, but a point is safer. No thousands "
     "separators (write 345678, not 345,678).",
     "सङ्ख्या अङ्कमा मात्र लेख्नुहोस्। अङ्ग्रेजी (123) र नेपाली (१२३) दुवै अङ्क स्वीकार्य छन् - प्रणालीले बदल्छ। एकाइ नलेख्नुहोस् (४५ से.मी. होइन, ४५) र सङ्ख्यामा "
     "अक्षर नमिसाउनुहोस्। दशमलवका लागि बिन्दु (27.4105) प्रयोग गर्नुहोस्। हजार छुट्याउने कमा नराख्नुहोस् (345678)।"),
    ("COORDINATES", "निर्देशाङ्क",
     "Degrees as decimal numbers (27.4105); degrees-minutes-seconds text such as 27°41'12\"N is also read. UTM easting and northing as plain numbers in metres. "
     "Format those cells as Number (not General or Text) so Excel does not show 3.03E+06 or drop digits. Fill the coordinate system on EVERY row.",
     "डिग्री दशमलवमा (27.4105); 27°41'12\"N जस्तो डिग्री-मिनेट-सेकेन्ड पनि पढिन्छ। UTM पूर्वी र उत्तरी निर्देशाङ्क मिटरमा सामान्य सङ्ख्या। ती कोठा 'Number' ढाँचामा "
     "राख्नुहोस् ताकि Excel ले 3.03E+06 नदेखाओस् वा अङ्क नझारोस्। निर्देशाङ्क प्रणाली प्रत्येक पङ्क्तिमा भर्नुहोस्।"),
    ("VALUES, NOT FORMULAS", "सूत्र होइन, मान",
     "Type values, not formulas. When you copy from another file use Paste Special > Values. Do not use colours or merged cells to carry information.",
     "सूत्र होइन, मान लेख्नुहोस्। अर्को फाइलबाट सार्दा Paste Special > Values प्रयोग गर्नुहोस्। जानकारी बोक्न रङ वा मिलाइएका कोठा प्रयोग नगर्नुहोस्।"),
]

SAVING = [
    ("As Excel", "Excel को रूपमा",
     "File > Save As > type 'Excel Workbook (*.xlsx)'. Do not choose .xls (old format) or .xlsm (macros).",
     "File > Save As > 'Excel Workbook (*.xlsx)' छान्नुहोस्। .xls (पुरानो) वा .xlsm (म्याक्रो) नछान्नुहोस्।"),
    ("After saving", "सुरक्षित गरेपछि",
     "Close the file in Excel before you upload it.",
     "अपलोड गर्नुअघि फाइल Excel मा बन्द गर्नुहोस्।"),
]

# what to enter in each column: (English, Nepali). Anything not listed is described from its header.
_STAND_NE = {"regen": "पुनरुत्पादन", "sapling": "लाथ्रा", "pole": "खाँवा", "tree": "रुख"}
COLUMN_HELP: Dict[str, tuple] = {
    "station_no": ("Station number, 1, 2, 3 ... in the order walked.", "स्टेसन नम्बर १, २, ३ ... हिँडेको क्रमअनुसार।"),
    "point_no": ("Point number, 1, 2, 3 ... in the order walked.", "बिन्दु नम्बर १, २, ३ ... हिँडेको क्रमअनुसार।"),
    us.INPUT_EPSG: ("REQUIRED on every row: the system your X and Y are in - 4326 = degrees (WGS 84), 32644 = UTM zone 44N, 32645 = UTM zone 45N.",
                    "प्रत्येक पङ्क्तिमा अनिवार्य: तपाईंका X र Y कुन प्रणालीमा छन् - 4326 = डिग्री (WGS 84), 32644 = UTM क्षेत्र ४४उ, 32645 = UTM क्षेत्र ४५उ।"),
    us.X_COL: ("Longitude in degrees (4326) or easting in metres (UTM), as named in the first column. Type it here; the sheet converts it.",
               "देशान्तर डिग्रीमा (4326) वा पूर्वी निर्देशाङ्क मिटरमा (UTM), पहिलो स्तम्भमा लेखिएअनुसार। यहाँ लेख्नुहोस्; पानाले बदल्छ।"),
    us.Y_COL: ("Latitude in degrees (4326) or northing in metres (UTM). Type it here; the sheet converts it.",
               "अक्षांश डिग्रीमा (4326) वा उत्तरी निर्देशाङ्क मिटरमा (UTM)। यहाँ लेख्नुहोस्; पानाले बदल्छ।"),
    "longitude": ("CALCULATED - do not type. Longitude in degrees (WGS 84), worked out from X and the coordinate system. This is what the system reads.",
                  "गणना गरिएको - नलेख्नुहोस्। देशान्तर डिग्रीमा (WGS 84), X र निर्देशाङ्क प्रणालीबाट निकालिएको। प्रणालीले यही पढ्छ।"),
    "latitude": ("CALCULATED - do not type. Latitude in degrees (WGS 84), worked out from Y and the coordinate system. This is what the system reads.",
                 "गणना गरिएको - नलेख्नुहोस्। अक्षांश डिग्रीमा (WGS 84), Y र निर्देशाङ्क प्रणालीबाट निकालिएको। प्रणालीले यही पढ्छ।"),
    CRS_COLUMN: ("CALCULATED - do not type. Always 4326 (degrees): longitude and latitude are already converted. The system checks they fall inside Nepal.",
                 "गणना गरिएको - नलेख्नुहोस्। सधैँ 4326 (डिग्री): देशान्तर र अक्षांश पहिले नै बदलिएका छन्। नेपालभित्र पर्छ कि प्रणालीले जाँच्छ।"),
    "remark": ("Free text. Not used in calculations.", "खुला पाठ। गणनामा प्रयोग हुँदैन।"),
    "plot_number": ("Sample plot number (a whole number, 1 or more).", "नमुना प्लट नम्बर (पूर्ण सङ्ख्या, १ वा बढी)।"),
    "sample_plot_number": ("Sample plot number (a whole number). Every stem or count measured in the same plot repeats it.",
                           "नमुना प्लट नम्बर (पूर्ण सङ्ख्या)। एउटै प्लटमा नापिएका प्रत्येक रुख वा गणनामा दोहोर्याउनुहोस्।"),
    "block_name": ("Name of the block or compartment the plot lies in, exactly as in the map.", "प्लट पर्ने ब्लक वा कम्पार्टमेन्टको नाम, नक्सामा जस्तै।"),
    "radius_m": ("Plot radius in metres (1 to 50).", "प्लटको अर्धव्यास मिटरमा (१ देखि ५०)।"),
    "species": ("Scientific name of the tree, e.g. Shorea robusta.", "रुखको वैज्ञानिक नाम, जस्तै Shorea robusta।"),
    "dia_cm": ("Diameter at breast height in cm.", "छातीको उचाइमा व्यास सेन्टिमिटरमा।"),
    "height_m": ("Tree height in metres (optional).", "रुखको उचाइ मिटरमा (ऐच्छिक)।"),
    "class": ("Tree class (A-D, a-d, 1-4 or I-IV) (optional).", "रुखको वर्ग (A-D, a-d, 1-4 वा I-IV) (ऐच्छिक)।"),
    "regen_dbh": ("Diameter of the seedling in cm.", "बिरुवाको व्यास सेन्टिमिटरमा।"),
    "regen_count": ("Number of seedlings of this species in the plot (a whole number).", "प्लटमा यो प्रजातिका बिरुवाको सङ्ख्या (पूर्ण सङ्ख्या)।"),
    "sapling_count": ("Number of saplings of this species in the plot (a whole number).", "प्लटमा यो प्रजातिका लाथ्राको सङ्ख्या (पूर्ण सङ्ख्या)।"),
    "pole_class": ("Pole class (A-D, a-d, 1-4 or I-IV) (optional).", "खाँवाको वर्ग (A-D, a-d, 1-4 वा I-IV) (ऐच्छिक)।"),
    "tree_class": ("Tree class (A-D, a-d, 1-4 or I-IV) (optional).", "रुखको वर्ग (A-D, a-d, 1-4 वा I-IV) (ऐच्छिक)।"),
}


def column_help(name: str) -> tuple:
    """(English, Nepali) text for a column; stand columns are described from their header (regen / sapling / pole / tree + species / dbh / height)."""
    if name in COLUMN_HELP:
        return COLUMN_HELP[name]
    for stand in ("regen", "sapling", "pole", "tree"):
        if name.startswith(stand + "_"):
            what = name[len(stand) + 1:]
            ne = _STAND_NE[stand]
            if what.startswith("species"):
                return (f"Scientific name of the {stand}, e.g. Shorea robusta.", f"{ne}को वैज्ञानिक नाम, जस्तै Shorea robusta।")
            if what.startswith("dbh"):
                return (f"Diameter at breast height of the {stand} in cm.", f"{ne}को छातीको उचाइमा व्यास सेन्टिमिटरमा।")
            if what.startswith("height"):
                return (f"Height of the {stand} in metres.", f"{ne}को उचाइ मिटरमा।")
    return (name.replace("_", " ").capitalize() + ".", name.replace("_", " ") + "।")


def allowed_text(name: str) -> str:
    """The allowed values / range of a column, from the shared rule table where there is one."""
    key = xr.rule_key_for(name)
    if key:
        r = RULES[key]
        usual = ""
        if r.soft_min is not None and r.soft_max is not None:
            usual = f"; usual {r.soft_min:g} to {r.soft_max:g}"
        elif r.soft_max is not None:
            usual = f"; usual up to {r.soft_max:g}"
        return f"{range_text(r)}{'; whole numbers' if r.integer else ''}{usual}"
    if name == "dia_cm":
        return f"{range_text(STEM_DBH)}; asks 'is it correct?' above {STEM_DBH.soft_max:g}"
    if name == "height_m":
        return f"{range_text(STEM_HEIGHT)}; usual up to {STEM_HEIGHT.soft_max:g}"
    if name == CRS_COLUMN:
        return "4326, 32644 or 32645"
    if name == "radius_m":
        return "1 to 50"
    if name == "plot_number":
        return "whole number, 1 or more"
    return ""


# ── building ───────────────────────────────────────────────────────────────────────────────────────────────────────────

def _style_header(ws, table: Table) -> Dict[str, str]:
    col_map: Dict[str, str] = {}
    for i, c in enumerate(table.columns, start=1):
        cell = ws.cell(row=1, column=i, value=c.name)
        cell.font = Font(bold=True, color="FFFFFFFF", size=11)
        cell.fill = _REQUIRED if c.required else _HEADER
        cell.alignment = Alignment(horizontal="center", vertical="center")
        ws.column_dimensions[get_column_letter(i)].width = max(14, len(c.name) + 4)
        col_map[c.name] = get_column_letter(i)
    return col_map


def _header_comment(table: Table, c: Col) -> Comment:
    en, ne = column_help(c.name)
    allowed = allowed_text(c.name)
    lines = [f"{'REQUIRED' if c.required else 'Optional'}  /  {'अनिवार्य' if c.required else 'ऐच्छिक'}", en, ne]
    if allowed:
        lines.append(f"Allowed / अनुमति: {allowed}")
    if c.example is not None and c.example != EXAMPLE_NOTE:
        lines.append(f"Example / उदाहरण: {c.example}")
    comment = Comment("\n".join(lines), "Forest Data Template")
    comment.width, comment.height = 380, 170 + 15 * len(lines)
    return comment


def _guideline_sheet(wb: Workbook, table: Table) -> None:
    ws = wb.create_sheet("Guideline")
    title_font, head_font = Font(bold=True, size=14), Font(bold=True, size=11, color="FF1B4D1F")
    wrap = Alignment(wrap_text=True, vertical="top")
    rows: List[tuple] = []  # (kind, a, b)

    def section(en: str, ne: str) -> None:
        rows.append(("head", f"{en}  /  {ne}", ""))

    def pair(label: str, en: str, ne: str) -> None:
        rows.append(("row", label, f"{en}\n{ne}"))

    rows.append(("title", f"{table.title}  /  {table.title_ne}", ""))
    rows.append(("row", "", f"{table.purpose}\n{table.purpose_ne}"))
    section("HOW TO FILL THIS TEMPLATE", "यो टेम्प्लेट कसरी भर्ने")
    for i, (en, ne) in enumerate(PROCEDURE, start=1):
        pair(str(i), en, ne)
    for note in table.instructions:
        rows.append(("row", "•", note))

    section("COLUMNS", "स्तम्भहरू")
    rows.append(("sub", "Column / स्तम्भ", "What to enter  |  Allowed  |  Example"))
    for c in table.columns:
        en, ne = column_help(c.name)
        allowed = allowed_text(c.name)
        ex = "" if c.example is None or c.example == EXAMPLE_NOTE else f"   Example: {c.example}"
        rows.append(("row", f"{c.name}{'  *' if c.required else ''}", f"{en}\n{ne}" + (f"\nAllowed: {allowed}" if allowed else "") + ex))
    rows.append(("row", "*", "required / अनिवार्य"))

    section("THINGS TO REMEMBER", "सम्झनुपर्ने कुरा")
    for label_en, label_ne, en, ne in REMEMBER:
        pair(f"{label_en}\n{label_ne}", en, ne)

    section("SAVING THE FILE ('Save as...')", "फाइल सुरक्षित गर्ने ('Save as...')")
    for label_en, label_ne, en, ne in SAVING:
        pair(f"{label_en}\n{label_ne}", en, ne)

    for kind, a, b in rows:
        ws.append([a, b])
        r = ws.max_row
        ws.cell(row=r, column=1).alignment = wrap
        ws.cell(row=r, column=2).alignment = wrap
        if kind == "title":
            ws.cell(row=r, column=1).font = title_font
        elif kind == "head":
            ws.cell(row=r, column=1).font = head_font
            ws.cell(row=r, column=1).fill = PatternFill("solid", fgColor="FFE8F5E9")
            ws.cell(row=r, column=2).fill = PatternFill("solid", fgColor="FFE8F5E9")
        elif kind == "sub":
            ws.cell(row=r, column=1).font = Font(bold=True)
            ws.cell(row=r, column=2).font = Font(bold=True)
    ws.column_dimensions["A"].width = 34
    ws.column_dimensions["B"].width = 120
    ws.sheet_view.showGridLines = False


def _excel_columns(table: Table) -> List[Col]:
    """The Excel form of a coordinate table: the user types a coordinate system, X and Y; longitude, latitude and the declared system are calculated."""
    out: List[Col] = []
    lon = next(c for c in table.columns if c.name == table.lon)
    lat = next(c for c in table.columns if c.name == table.lat)
    for c in table.columns:
        if c.name == table.lon:
            out += [Col(us.INPUT_EPSG, 4326, True), Col(us.X_COL, lon.example, lon.required), Col(us.Y_COL, lat.example, lat.required),
                    Col(table.lon, lon.example), Col(table.lat, lat.example)]
        elif c.name == table.lat:
            continue
        elif c.name == CRS_COLUMN:
            out.append(Col(CRS_COLUMN, 4326))
        else:
            out.append(c)
    return out


def _calculated_columns(ws, table: Table, col_map: Dict[str, str]) -> None:
    """Write the longitude / latitude / system formulas down the sheet and the hidden Convert sheet behind them."""
    letters = {n: col_map[n] for n in (us.INPUT_EPSG, us.X_COL, us.Y_COL)}
    lon_l, lat_l, crs_l = col_map[table.lon], col_map[table.lat], col_map[CRS_COLUMN]
    for r in range(2, us.ROWS + 2):
        f = us.data_formulas(r, letters)
        ws[f"{lon_l}{r}"], ws[f"{lat_l}{r}"] = f["longitude"], f["latitude"]
        ws[f"{crs_l}{r}"] = f'=IF(ISNUMBER({lon_l}{r}),4326,"")'
        for letter in (lon_l, lat_l, crs_l):
            ws[f"{letter}{r}"].fill = us.CALCULATED_FILL


def build_workbook(table: Table) -> Workbook:
    wb = Workbook()
    ws = wb.active
    ws.title = "Data"  # first sheet: the importers read it
    table = replace(table, columns=_excel_columns(table)) if table.has_coordinates else table
    col_map = _style_header(ws, table)
    last_row = xr.MIN_VALIDATED_ROWS
    calculated = {table.lon, table.lat, CRS_COLUMN} if table.has_coordinates else set()
    for i, c in enumerate(table.columns, start=1):  # the grey example row, and a comment on every header saying what to enter
        ws.cell(row=1, column=i).comment = _header_comment(table, c)
        if c.name in calculated:
            continue  # a formula goes here
        cell = ws.cell(row=2, column=i, value=c.example if c.example is not None else None)
        cell.fill = _EXAMPLE
        cell.font = Font(italic=True, color="FF888888")
    ws.freeze_panes = "A2"
    ws.cell(row=4, column=1, value="Row 2 is an example: delete it before you upload. / पङ्क्ति २ उदाहरण हो: अपलोड गर्नुअघि हटाउनुहोस्।").font = Font(italic=True, color="FFAA0000", size=9)
    if table.numeric:
        table.numeric(ws, col_map, last_row)
    if table.has_coordinates:
        ws.add_data_validation(_epsg_validation(col_map[us.INPUT_EPSG], last_row))
        _calculated_columns(ws, table, col_map)
        _coordinate_flags(ws, col_map[table.lon], col_map[table.lat], col_map[CRS_COLUMN], last_row)
        ws.conditional_formatting.add(f"{col_map[us.INPUT_EPSG]}2:{col_map[us.INPUT_EPSG]}{last_row}",
                                      FormulaRule(formula=[f"AND(ISNUMBER({col_map[us.X_COL]}2),LEN({col_map[us.INPUT_EPSG]}2)=0)"], fill=xr.RED))
    _guideline_sheet(wb, table)
    if table.has_coordinates:
        us.add_convert_sheet(wb, {n: col_map[n] for n in (us.INPUT_EPSG, us.X_COL, us.Y_COL)})  # hidden, after the Guideline
    return wb


def workbook_bytes(wb: Workbook) -> bytes:
    bio = io.BytesIO()
    wb.save(bio)
    return bio.getvalue()


def csv_bytes(table: Table) -> bytes:
    """Header row only: a CSV cannot show a grey example, and an example left in would be imported as data. UTF-8 with a BOM so Excel opens it."""
    out = io.StringIO()
    csv.writer(out, lineterminator="\r\n").writerow([c.name for c in table.columns])
    return b"\xef\xbb\xbf" + out.getvalue().encode("utf-8")


def readme_text() -> str:
    from app.core import constants as c  # noqa: F401 -- kept for the tree-class thresholds below

    def line(key: str) -> str:
        r = RULES[key]
        usual = ""
        if r.soft_min is not None and r.soft_max is not None:
            usual = f"  (usual {r.soft_min:g} to {r.soft_max:g})"
        elif r.soft_max is not None:
            usual = f"  (usual up to {r.soft_max:g})"
        return f"  {key:<14} {range_text(r)}{usual}"

    rows = [
        "FOREST DATA TEMPLATES / वन तथ्याङ्क टेम्प्लेट",
        "=" * 70,
        "",
        "Fill the template for the data you have, delete the grey example row, save, and load it with 'Add data'.",
        "आफ्नो तथ्याङ्कको टेम्प्लेट भर्नुहोस्, खैरो उदाहरण पङ्क्ति हटाउनुहोस्, सुरक्षित गर्नुहोस्, अनि 'Add data' बाट अपलोड गर्नुहोस्।",
        "",
        "FILES / फाइल",
        "  excel/   Excel templates with dropdowns, limits, highlighting, a guideline sheet and automatic UTM conversion.",
        "  The system also reads a plain CSV with the same column names, but only the Excel templates carry the limits, dropdowns, guideline and conversion.",
        "",
        "  01 Forest boundary stations     the boundary, as points in walking order",
        "  02 Sample plots                 plots prepared in another system",
        "  03 Field inventory              regeneration, sapling, pole and tree measurements per plot",
        "  04 Stem mapping                 individual trees with coordinates",
        "  05 Households and committees    household list and the user, advisory and finance committees (Excel only)",
        "  06 User group points            the user group area as points (optional)",
        "  07 Forest details               name, group, location, offices, national code, plan years (one row)",
        "  Building footprints, roads, rivers and other maps are loaded as GIS layers with 'Import Layer'.",
        "",
        "COORDINATE SYSTEM / निर्देशाङ्क प्रणाली  (REQUIRED / अनिवार्य)",
        "  Every table with coordinates has a column  " + CRS_COLUMN + "  that must be filled on EVERY row:",
        "    4326   degrees (WGS 84)        32644  UTM zone 44N        32645  UTM zone 45N",
        "  The system compares your numbers with the system you name and reports the row if they do not fit.",
        "  Nepal Modified UTM (MUTM) is not supported yet.",
        "  In the EXCEL templates you type the system, X and Y exactly as your team recorded them (degrees, or UTM easting / northing in metres); the grey",
        "  longitude and latitude columns are calculated for you (a hidden 'Convert' sheet does the maths) and are what the system reads. Do not type in them.",
        "  If you ever load a plain CSV instead, put degrees in longitude / latitude, or UTM numbers with the matching system on every row.",
        "  Longitude / easting goes in the longitude column, latitude / northing in the latitude column.",
        "",
        "UNITS AND LIMITS / एकाइ र सीमा",
        "  Diameter at breast height (DBH) in cm, height in m. Decimals are allowed.",
        "  A value in red is outside the allowed range and is refused on upload; amber is unusual - please confirm it.",
        line("regen_dbh"), line("sapling_dbh"), line("pole_dbh"), line("tree_dbh"),
        line("pole_height"), line("tree_height"), line("regen_count"), line("sapling_count"),
        f"  stem DBH       {range_text(STEM_DBH)} (stem mapping; usual up to {STEM_DBH.soft_max:g})",
        "  The size classes include their lower edge and not their upper edge: 30.0 cm is a tree, 10.0 cm is a pole.",
        "",
        "THINGS TO REMEMBER / सम्झनुपर्ने कुरा",
    ] + [f"  {a} / {b}: {en}\n      {ne}" for a, b, en, ne in REMEMBER] + [
        "",
        "SAVING THE FILE ('Save as...') / फाइल सुरक्षित गर्ने",
    ] + [f"  {a} / {b}: {en}\n      {ne}" for a, b, en, ne in SAVING] + [
        "",
        "STATIONS / स्टेसन",
        "  List boundary stations in the order you walked them. The system finds a station whose digits look mistyped and proposes the correction.",
        "",
        "WHEN A VALUE IS REFUSED / मान अस्वीकृत भए",
        "  The report names the row. For a diameter or height the system proposes a replacement inside the right class; nothing changes until you apply it.",
        "",
        "Generated " + datetime.now(timezone.utc).strftime("%Y-%m-%d"),
    ]
    return "\n".join(rows) + "\n"


def build_templates_zip(land_unit: str = "ropani", *, household_workbook: Optional[Callable] = None, field_inventory_workbook: Optional[Callable] = None) -> bytes:
    """The whole zip in memory. ``household_workbook(land_unit)`` returns the household workbook (injected by the API layer, which owns that builder);
    ``field_inventory_workbook()`` the field-inventory workbook with the species list, which needs the database (without it the plain table is used)."""
    land_unit = land_unit if land_unit in ("ropani", "kaththa") else "ropani"
    bio = io.BytesIO()
    with zipfile.ZipFile(bio, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("00_READ_ME.txt", readme_text().encode("utf-8-sig"))
        for t in tables():
            if t.file_stem == "03_Field_Inventory" and field_inventory_workbook is not None:
                z.writestr(f"excel/{t.file_stem}.xlsx", field_inventory_workbook())
            else:
                z.writestr(f"excel/{t.file_stem}.xlsx", workbook_bytes(build_workbook(t)))
        if household_workbook is not None:
            z.writestr("excel/05_Households_and_Committees.xlsx", workbook_bytes(household_workbook(land_unit)))
    return bio.getvalue()
