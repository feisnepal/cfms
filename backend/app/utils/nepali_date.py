"""Nepali date and fiscal year utilities.

Provides regex-based validation for Nepali (BS) date strings and Nepali fiscal
year format strings, plus the one conversion the metadata form needs: which
fiscal year a given day falls in.

The validators do only format and range checking. The fiscal-year helpers do
read the calendar (through ``nepali-datetime``) because a fiscal year is not a
label you can write down without knowing the date -- "2083/84" begins on Shrawan
1, whose Gregorian day drifts year to year.

See also:
    app.schemas.metadata_form — uses these validators in forms
    app.services.forest_metadata_service — seeds fy_start / fy_end with them
"""

import re
from datetime import date as _date
from typing import Optional


def is_valid_nepali_date(date_str: str) -> bool:
    """Validate a Nepali date string in YYYY-MM-DD or YYYY/MM/DD format."""
    if not date_str or not isinstance(date_str, str):
        return False
    m = re.match(r"^(\d{4})[-/](\d{1,2})[-/](\d{1,2})$", date_str.strip())
    if not m:
        return False
    year, month, day = int(m.group(1)), int(m.group(2)), int(m.group(3))
    if year < 2050 or year > 2099:
        return False
    if month < 1 or month > 12:
        return False
    if day < 1 or day > 32:
        return False
    return True


def is_valid_nepali_fiscal_year(fy_str: str) -> bool:
    """Validate a Nepali fiscal year string in YYYY/YYYY format."""
    if not fy_str or not isinstance(fy_str, str):
        return False
    m = re.match(r"^(\d{4})/(\d{4})$", fy_str.strip())
    if not m:
        return False
    start, end = int(m.group(1)), int(m.group(2))
    if start < 2050 or start > 2099:
        return False
    if end != start + 1:
        return False
    return True


def is_valid_nepali_year_only(year_val) -> bool:
    """Validate a Nepali year value falls within the 2050-2099 BS range."""
    try:
        y = int(year_val)
        return 2050 <= y <= 2099
    except (ValueError, TypeError):
        return False


def current_fiscal_year_start(today: Optional[_date] = None) -> int:
    """The BS year the current Nepali fiscal year begins in.

    Nepal's fiscal year runs Shrawan 1 to Ashad end. Shrawan is the fourth BS
    month, so Baisakh, Jestha and Ashad (months 1-3) still belong to the *previous*
    year's fiscal year: 2083-01 (Baisakh) is in FY 2082/83, while 2083-04 (Shrawan)
    opens FY 2083/84. Returns, for example, 2083.

    `today` is a Gregorian date; it exists so a test can pin the conversion rather
    than read the clock.
    """
    import nepali_datetime

    if today is None:
        today = _date.today()
    bs = nepali_datetime.date.from_datetime_date(today)
    return bs.year if bs.month >= 4 else bs.year - 1


def fiscal_year_label(start_year: int) -> str:
    """The "2083/84" spelling of a fiscal year that begins in `start_year` BS.

    The second half is the next year's last two digits, which is how the fiscal
    year is written on every cover page (`app.services.report.document_builder`).
    """
    return f"{start_year}/{str(start_year + 1)[-2:]}"
