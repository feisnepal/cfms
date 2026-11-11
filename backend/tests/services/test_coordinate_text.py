"""Hand-typed coordinates become numbers; what cannot be read is left as typed (owner plan step C5)."""
import pandas as pd
import pytest

from app.services.upload.coordinate_text import clean_coordinate_columns, parse_coordinate

_DMS = 27 + 41 / 60 + 12 / 3600


@pytest.mark.parametrize("typed, value", [
    ("27.69", 27.69), ("27.69°", 27.69), ("+84.1", 84.1), (" 84.1 ", 84.1), (28.2, 28.2), (84, 84.0),
    ("२७.६९", 27.69), ("८४.१२३४", 84.1234), ("२७°४१'१२\"", _DMS),
    ("27°41'12\"", _DMS), ("27°41'12\"N", _DMS), ("27° 41' 12\" N", _DMS), ("27d41m12s", _DMS), ("27:41:12", _DMS), ("27 41 12", _DMS),
    ("27°41'", 27 + 41 / 60), ("27°41.2'", 27 + 41.2 / 60), ("27°41′12″", _DMS), ("27°41'12.5\"", 27 + 41 / 60 + 12.5 / 3600),
    ("84°7'30\"E", 84 + 7 / 60 + 30 / 3600), ("84°7'30\"W", -(84 + 7 / 60 + 30 / 3600)),
    ("84,123", 84.123), ("27,69", 27.69), ("28,123", 28.123),
    ("345,678.5", 345678.5), ("3,065,000", 3065000.0), ("345,678", 345678.0),
])
def test_typed_forms_are_read(typed, value):
    assert parse_coordinate(typed) == pytest.approx(value)


@pytest.mark.parametrize("typed", ["", "  ", "N/A", "abc", "27°61'", "27°41'72\"", "12 34", "27.69.1", "--5", "१२३abc", None, True])
def test_what_cannot_be_read_with_confidence_is_left_alone(typed):
    assert parse_coordinate(typed) is None


def test_a_column_of_typed_coordinates_becomes_numbers_and_unreadable_cells_stay():
    df = pd.DataFrame({"longitude": ["८४.१", "84°7'30\"", "84,25", "N/A", 84.5], "latitude": ["27°41'12\"", "२७.७", "27,8", "27.9", 28.0], "note": list("abcde")})
    out = clean_coordinate_columns(df)
    assert list(out["latitude"]) == pytest.approx([_DMS, 27.7, 27.8, 27.9, 28.0])
    assert out["longitude"].iloc[0] == pytest.approx(84.1) and out["longitude"].iloc[1] == pytest.approx(84 + 7 / 60 + 30 / 3600)
    assert out["longitude"].iloc[3] == "N/A"  # left as typed: the validator names the row
    assert out["note"].tolist() == list("abcde") and df["longitude"].iloc[0] == "८४.१"  # the input frame is not modified


def test_numeric_columns_are_returned_untouched():
    df = pd.DataFrame({"longitude": [84.1, 84.2], "latitude": [28.2, 28.3]})
    assert clean_coordinate_columns(df) is df


def test_the_upload_normaliser_applies_it_for_both_paths():
    from app.services.upload.fi_columns import normalise_columns, normalise_columns_with_units

    df = pd.DataFrame({"Lon": ["८४.१", "84,2"], "Lat": ["27°41'12\"N", "27.7"], "Plot No": [1, 2]})
    out, renames, conversions = normalise_columns_with_units(df)
    assert list(out["longitude"]) == pytest.approx([84.1, 84.2]) and out["latitude"].iloc[0] == pytest.approx(_DMS)
    assert normalise_columns(df)[0]["longitude"].iloc[0] == pytest.approx(84.1)  # the later processing read sees the same numbers
    assert conversions == []  # the value conversion is not a reported conversion (owner: convert, no report line)
