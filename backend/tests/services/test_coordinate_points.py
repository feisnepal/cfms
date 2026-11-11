"""Per-point coordinate judgement (owner plan step C1/C3): by size not by header, with the rows named."""
import numpy as np
import pandas as pd
import pytest

from app.services.upload import coordinates as co
from app.services.upload.findings import CATALOGUE


@pytest.mark.parametrize("x, y, kind", [
    (84.1, 28.2, "degrees"), (28.2, 84.1, "swapped"), (350_000, 3_065_000, "utm"), (3_065_000, 350_000, "swapped_utm"),
    (94.1, 28.2, "outside_nepal"), (0, 0, "zero"), (None, 28.2, "missing"), ("N/A", 28.2, "missing"), (float("nan"), 1, "missing"),
    (5_000_000_000, 7, "unknown"), (-84.1, 28.2, "outside_nepal"),
])
def test_point_kind(x, y, kind):
    assert co.point_kind(x, y) == kind


def test_one_stray_point_no_longer_makes_the_whole_file_unknown():
    d = co.diagnose([84.1, 84.2, 94.1, 84.3], [28.2, 28.3, 28.2, 28.4])
    assert d["kind"] == "ok" and d["dominant"] == "degrees"
    assert d["strays"] == [(4, "outside_nepal")]  # spreadsheet row 4 = the third data row


def test_rows_come_from_the_dataframe_index_not_the_position():
    df = pd.DataFrame({"lon": [84.1, None, 84.3, 0.0], "lat": [28.2, 28.2, 28.4, 0.0]}, index=[0, 1, 2, 3])
    d = co.diagnose(df["lon"], df["lat"])
    assert d["missing_rows"] == [3, 5]  # blank + (0,0)


def test_a_whole_file_of_swapped_utm_is_named():
    d = co.diagnose([3_065_000, 3_066_000], [350_000, 351_000])
    assert d["kind"] == "swapped_utm"


def test_a_utm_file_with_one_degree_row_is_still_utm_and_the_degree_row_is_a_stray():
    d = co.diagnose([350_000, 351_000, 84.1], [3_065_000, 3_066_000, 28.2])
    assert d["kind"] == "utm" and d["strays"] == [(4, "degrees")]


def test_findings_name_the_rows():
    f = co.coordinate_findings(pd.Series([84.1, None, 94.1, 84.3]), pd.Series([28.2, 28.2, 28.2, 28.4]), file="f.csv")
    by = {x.code: x for x in f}
    assert by["coordinates.rows_missing"].where["rows"] == [3] and "3" in by["coordinates.rows_missing"].title_en
    assert by["coordinates.stray_points"].where["rows"] == [4]
    assert "outside Nepal" in by["coordinates.stray_points"].title_en


def test_a_clean_file_has_no_coordinate_findings():
    assert co.coordinate_findings([84.1, 84.2], [28.2, 28.3]) == []


def test_empty_input_is_still_empty():
    assert co.diagnose([], [])["kind"] == "empty"


def test_the_new_findings_are_in_the_catalogue_in_both_languages():
    for code in ("coordinates.rows_missing", "coordinates.stray_points", "coordinates.looks_swapped_utm"):
        assert code in CATALOGUE and CATALOGUE[code]["title"]["ne"] and CATALOGUE[code]["fix"]["ne"]
