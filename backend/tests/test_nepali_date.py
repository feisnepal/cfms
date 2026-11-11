"""The fiscal-year conversion behind the metadata form's default period.

`app.services.forest_metadata_service.fiscal_year_defaults` seeds `fy_start` and
`fy_end`, but the rule that decides *which* year is current belongs here. It is
worth its own test because it is the one place where "this year" is not the BS
year on the calendar: the Nepali fiscal year starts at Shrawan (month 4), so
Baisakh, Jestha and Ashad still belong to the previous year's period.
"""
from __future__ import annotations

from datetime import date

from app.utils.nepali_date import current_fiscal_year_start, fiscal_year_label


def test_a_fiscal_year_is_written_as_the_year_and_the_next_two_digits():
    assert fiscal_year_label(2083) == "2083/84"
    assert fiscal_year_label(2093) == "2093/94"


def test_shrawan_opens_a_new_fiscal_year():
    # Shrawan 1, 2083 is 2026-07-17. The day before is still the old period.
    assert current_fiscal_year_start(date(2026, 7, 17)) == 2083
    assert current_fiscal_year_start(date(2026, 7, 16)) == 2082


def test_baisakh_belongs_to_the_previous_fiscal_year():
    # Baisakh 1, 2083 (2026-04-14) is the new *calendar* year, but not the new
    # *fiscal* year -- that only turns over at Shrawan.
    assert current_fiscal_year_start(date(2026, 4, 14)) == 2082
    assert current_fiscal_year_start(date(2026, 5, 1)) == 2082


def test_late_in_the_bs_year_is_the_current_fiscal_year():
    # Ashoj 2083 (2026-10-12), the date this was written against.
    assert current_fiscal_year_start(date(2026, 10, 12)) == 2083
