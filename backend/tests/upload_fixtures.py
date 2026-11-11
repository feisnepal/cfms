"""Wrong-file fixtures for the upload-experience work (UPLOAD_EXPERIENCE_PLAN.md, UP-0).

Every function returns ``bytes`` built in memory, so no binary blobs live in the repo and each fixture says in code what is wrong with it.
The characterization tests (``test_upload_baseline_*.py``) record what the system does with each file TODAY; the later phases change that
behaviour on purpose and update those tests with it.
"""
from __future__ import annotations

import io
import zipfile

# ── file-level problems, valid for every upload ───────────────────────────────────────────────────────────────────────────────────────


def empty_file() -> bytes:
    return b""


def header_only_csv(header: str = "a,b,c") -> bytes:
    return (header + "\n").encode("utf-8")


def non_utf8_csv() -> bytes:
    """A CSV saved in a legacy single-byte encoding (Devanagari text cannot be decoded as UTF-8)."""
    return "house_no,surname\n1,Sharma\n2,".encode("utf-8") + b"\xff\xfe\xfa" + b"\n"


def csv_that_is_really_xlsx() -> bytes:
    """Starts with the zip signature of an .xlsx but is named .csv by the caller."""
    return xlsx_bytes([["house_no", "surname"], [1, "Sharma"]])


def corrupt_xlsx() -> bytes:
    return b"PK\x03\x04 this is not a real workbook"


def xlsx_bytes(rows: list[list], sheet: str = "Sheet1") -> bytes:
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = sheet
    for r in rows:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ── household ─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────

HH_HEADER_NE = ["घर नंवर", "थर", "महिला संख्या", "पुरूष संख्या"]
HH_HEADER_EN = ["house_no", "surname", "female_count", "male_count"]


def household_csv(rows: list[list], *, two_header_rows: bool = True) -> bytes:
    """The template shape (Nepali header row, English header row, data) or, with ``two_header_rows=False``, a single header row."""
    lines = [",".join(HH_HEADER_NE)]
    if two_header_rows:
        lines.append(",".join(HH_HEADER_EN))
    lines += [",".join(str(c) for c in r) for r in rows]
    return ("\n".join(lines) + "\n").encode("utf-8-sig")


def household_csv_with_bad_rows() -> bytes:
    """Three good rows, one with a negative count, one with a text count, one with a duplicate house number."""
    return household_csv([[1, "Sharma", 2, 3], [2, "Thapa", -1, 2], [3, "Rai", "two", 1], [4, "Gurung", 1, 1], [4, "Gurung", 1, 1]])


# ── user group / boundary files ───────────────────────────────────────────────────────────────────────────────────────────────────────

# A small square near Kavre (inside Nepal), in degrees.
KAVRE_SQUARE = [(85.55, 27.40), (85.57, 27.40), (85.57, 27.42), (85.55, 27.42)]


def points_csv(points, header: str = "lon,lat") -> bytes:
    return (header + "\n" + "\n".join(f"{a},{b}" for a, b in points) + "\n").encode("utf-8")


def csv_without_coordinate_columns() -> bytes:
    return b"name,village\nA,One\nB,Two\nC,Three\n"


def csv_with_swapped_lat_lon() -> bytes:
    """Longitude values under a 'lat' header and latitude values under 'lon' (the two columns labelled the wrong way round)."""
    return points_csv(KAVRE_SQUARE, header="lat,lon")


def csv_with_utm_values_and_no_crs() -> bytes:
    """UTM 45N metres in 'x,y' columns with no CRS stated."""
    return b"x,y\n343500,3030000\n345500,3030000\n345500,3032000\n343500,3032000\n"


def csv_with_collinear_points() -> bytes:
    return points_csv([(85.55, 27.40), (85.56, 27.40), (85.57, 27.40)])


def csv_with_two_points() -> bytes:
    return points_csv([(85.55, 27.40), (85.56, 27.41)])


def csv_square(side_deg: float) -> bytes:
    """A square of the given side (degrees) starting at the Kavre corner; 0.30 deg is roughly 33 km, far over 5,000 ha."""
    x0, y0 = KAVRE_SQUARE[0]
    return points_csv([(x0, y0), (x0 + side_deg, y0), (x0 + side_deg, y0 + side_deg), (x0, y0 + side_deg)])


def zip_without_shp() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("readme.txt", "no shapefile in here")
    return buf.getvalue()


# ── stem mapping (the individual-tree file) ──────────────────────────────────────────────────────────────────────────────────────────

STEM_HEADER = "tree_id,species,dbh_cm,height_m,longitude,latitude"
STEM_MAPPING = {"species": "species", "dbh_cm": "dia_cm", "height_m": "height_m", "longitude": "LONGITUDE", "latitude": "LATITUDE"}


def stem_csv(rows: list[tuple], header: str = STEM_HEADER) -> bytes:
    return (header + "\n" + "\n".join(",".join(str(c) for c in r) for r in rows) + "\n").encode("utf-8")


def stem_rows(n: int = 8, *, x0: float = 85.55, y0: float = 27.40) -> list[tuple]:
    return [(i, "Shorea robusta", 30 + i, 15, round(x0 + i * 0.0004, 6), round(y0 + i * 0.0004, 6)) for i in range(1, n + 1)]


def stem_csv_good() -> bytes:
    return stem_csv(stem_rows())


def stem_csv_wrong_crs_utm() -> bytes:
    """Coordinates in UTM metres under the longitude / latitude headers."""
    return stem_csv([(i, "Shorea robusta", 30, 15, 343500 + i * 10, 3030000 + i * 10) for i in range(1, 6)])


def stem_csv_swapped_xy() -> bytes:
    """Latitude values under the longitude header and the other way round."""
    return stem_csv([(i, "Shorea robusta", 30, 15, y, x) for i, _, _, _, x, y in stem_rows(5)])


def stem_csv_partly_outside(outside_share: float = 0.25, n: int = 20) -> bytes:
    """A good file where the given share of trees lies far outside the forest (default 25%, over the 20% tolerance)."""
    rows = stem_rows(n)
    k = int(n * outside_share)
    rows[:k] = [(r[0], r[1], r[2], r[3], 83.0 + r[0] * 0.0004, 27.0 + r[0] * 0.0004) for r in rows[:k]]
    return stem_csv(rows)


# ── field inventory (tree stand only: the smallest valid shape) ──────────────────────────────────────────────────────────────────────

FI_HEADER = "block_name,sample_plot_number,longitude,latitude,tree_species_scientific,tree_dbh_cm,tree_height_m"


def field_inventory_csv(rows: list[tuple], header: str = FI_HEADER) -> bytes:
    return (header + "\n" + "\n".join(",".join(str(c) for c in r) for r in rows) + "\n").encode("utf-8")


def fi_good_rows() -> list[tuple]:
    return [("C1", p, 85.55 + p * 0.001, 27.40 + p * 0.001, "Shorea robusta", 32 + p, 18) for p in range(1, 6)]


def fi_missing_longitude() -> bytes:
    return field_inventory_csv([(a, b, d, e, f, g) for a, b, c, d, e, f, g in [(r[0], r[1], r[2], r[3], r[4], r[5], r[6]) for r in fi_good_rows()]],
                               header="block_name,sample_plot_number,latitude,tree_species_scientific,tree_dbh_cm,tree_height_m")


def fi_dbh_in_mm() -> bytes:
    return field_inventory_csv([(a, b, c, d, e, f * 10, g) for a, b, c, d, e, f, g in fi_good_rows()])


def fi_misspelled_species() -> bytes:
    return field_inventory_csv([(a, b, c, d, "Shorea  robusta " if b % 2 else "Shorea robustta", f, g) for a, b, c, d, e, f, g in fi_good_rows()])


def fi_utm_coordinates() -> bytes:
    return field_inventory_csv([(a, b, 343500 + b * 10, 3030000 + b * 10, e, f, g) for a, b, c, d, e, f, g in fi_good_rows()])


# ── leftovers from UP-0.5 ──────────────────────────────────────────────────────────────────────────────────────────────────────────

def legacy_xls() -> bytes:
    """The header of an old binary Excel file (.xls) - also what a PASSWORD-PROTECTED .xlsx looks like (an encrypted OLE container)."""
    return b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 512


def oversize(mb: int = 51) -> bytes:
    return b"a,b\n" + b"1,2\n" * (mb * 1024 * 1024 // 4)


def household_xlsx_with_broken_committee() -> bytes:
    """A household workbook whose main-committee sheet has none of the template's column names (UP-0.5 / UP-3)."""
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = "घरधुरी"
    for r in (HH_HEADER_NE, HH_HEADER_EN, [1, "Sharma", 2, 3]):
        ws.append(r)
    cs = wb.create_sheet("वन उपभोक्ता समिति")
    for r in (["a", "b"], ["c", "d"], ["x", "y"], ["z", "w"]):
        cs.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
