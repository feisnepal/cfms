"""A whole column of diameters in millimetres is caught; ordinary forests and single typing slips are not (UP-3.3)."""
from __future__ import annotations

from app.services.upload.units import dbh_unit_findings, dbh_unit_problem


def test_a_column_in_millimetres_is_recognised_and_the_centimetre_value_is_suggested():
    med, as_cm = dbh_unit_problem([320, 350, 410, 280, 500])
    assert med == 350 and as_cm == 35


def test_ordinary_diameters_are_fine_including_a_few_very_big_trees():
    assert dbh_unit_problem([22, 31, 45, 38, 160, 27]) is None  # one 160 cm giant does not change the median


def test_a_single_slip_is_the_range_checks_business_not_a_unit_problem():
    assert dbh_unit_problem([30, 35, 3500]) is None


def test_too_few_values_say_nothing_and_blanks_text_and_zeros_are_ignored():
    assert dbh_unit_problem([400, 500]) is None
    assert dbh_unit_problem([None, "n/a", 0, 0, 30, 35, 40]) is None
    assert dbh_unit_problem(["300", "320", "340"]) == (320.0, 32.0)  # numbers typed as text still count


def test_the_finding_names_the_column_and_says_what_to_do_in_both_languages():
    f = dbh_unit_findings([("tree diameters", [320, 350, 410])], file="fi.csv")[0]
    assert f.code == "field_inventory.dbh_in_mm" and f.severity == "error"
    assert "tree diameters (median 350)" in f.title_en and "35 cm" in f.title_en and "divide by 10" in f.fix_en
    assert f.title_ne and f.fix_ne and f.where == {"file": "fi.csv"}


def test_heights_in_feet_are_a_warning_not_a_block():
    from app.services.upload.units import height_unit_findings, height_unit_problem

    assert height_unit_problem([50, 60, 70, 55]) is not None
    assert height_unit_problem([12, 18, 22, 15]) is None
    assert height_unit_problem([60, 70]) is None  # two values say nothing
    f = height_unit_findings([("tree heights", [50, 60, 70, 55])])
    assert len(f) == 1 and f[0].severity == "warning" and "feet" in f[0].title_en and f[0].fix_ne
