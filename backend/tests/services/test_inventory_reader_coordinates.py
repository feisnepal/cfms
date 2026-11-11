"""The shared stem-mapping file reader turns hand-typed coordinates into numbers for every read of the file."""
import pandas as pd
import pytest

from app.api.inventory import read_upload_file

DMS = 27 + 41 / 60 + 12 / 3600


def _csv(rows, header="species,dia_cm,longitude,latitude"):
    return (header + "\n" + "\n".join(rows) + "\n").encode("utf-8")


def test_dms_decimal_comma_and_thousands_become_numbers():
    df = read_upload_file(_csv(['Sal,35,"84,25","27°41\'12""N"', "Sal,40,८४.३,२७.७"]), "stems.csv")
    assert df["longitude"].tolist() == pytest.approx([84.25, 84.3])
    assert df["latitude"].tolist() == pytest.approx([DMS, 27.7])
    assert str(df["longitude"].dtype).startswith("float")  # a numeric column for everything that follows


def test_utm_sheets_headed_easting_northing_are_cleaned_too():
    df = read_upload_file(_csv(['Sal,35,"345,678.5","3,065,000"', "Sal,40,345700.5,3065100"], header="species,dia_cm,Easting,Northing"), "stems.csv")
    assert df["Easting"].tolist() == pytest.approx([345678.5, 345700.5]) and df["Northing"].tolist() == pytest.approx([3065000.0, 3065100.0])


def test_a_cell_that_cannot_be_read_stays_as_typed_for_the_validator_to_name():
    df = read_upload_file(_csv(["Sal,35,near the stream,27.7", "Sal,40,84.3,27.8"]), "stems.csv")
    assert df["longitude"].tolist() == ["near the stream", 84.3] and df["latitude"].tolist() == pytest.approx([27.7, 27.8])


def test_a_plain_numeric_file_and_other_columns_are_untouched():
    df = read_upload_file(_csv(["Sal,35,84.25,27.7", "Pine,40,84.3,27.8"]), "stems.csv")
    assert df["species"].tolist() == ["Sal", "Pine"] and df["dia_cm"].tolist() == [35, 40]
    assert df["longitude"].tolist() == [84.25, 84.3]


def test_a_file_without_coordinate_columns_is_returned_as_is():
    df = read_upload_file(b"species,dia_cm\nSal,35\n", "stems.csv")
    assert list(df.columns) == ["species", "dia_cm"]
