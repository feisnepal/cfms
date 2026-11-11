"""The NTFP field form: what is built and what is accepted coming back (``app.services.ntfp_form``)."""
import io
from datetime import date

import pytest
from openpyxl import Workbook, load_workbook

from app.services import ntfp_form as f

TODAY = date(2026, 10, 22)
DESIGN = {
    "species": [{"species_key": "zanthoxylum armatum", "label": "टिमुर", "plot_sqm": 25, "growth_class": "shrub"},
                {"species_key": "bombax ceiba", "label": "सिमल", "plot_sqm": 500, "growth_class": "tree"}],
    "plots": [
        {"plot_number": 1, "stratum": "B1", "longitude": 83.401, "latitude": 27.401, "species_keys": ["zanthoxylum armatum", "bombax ceiba"]},
        {"plot_number": 2, "stratum": "B1", "longitude": 83.402, "latitude": 27.402, "species_keys": ["zanthoxylum armatum"]},
    ],
}
PROFILES = [
    {"species_key": "zanthoxylum armatum", "nepali_name": "टिमुर", "scientific_name": "Zanthoxylum armatum", "part_ne": "फल", "part_groups": ["ङ"],
     "sampling_method": "non_destructive", "maturity_ne": "फल पाकेर कालो भएपछि", "n_individuals_min": 3, "n_individuals_max": 3,
     "harvest_fraction_pct": 90.0, "conversion_factor": None, "procedure_en": "Count the shrubs."},
    {"species_key": "bombax ceiba", "nepali_name": "सिमल", "scientific_name": "Bombax ceiba", "part_ne": "फूल", "part_groups": ["घ"],
     "sampling_method": "non_destructive", "maturity_ne": "फूल फुलेको रूख", "n_individuals_min": 2, "n_individuals_max": 2,
     "harvest_fraction_pct": 50.0, "conversion_factor": None, "procedure_en": "Count the trees."},
]
ASSIGNED = {(p["plot_number"], k): True for p in DESIGN["plots"] for k in p["species_keys"]}
PARTS = {p["species_key"]: p["part_groups"] for p in PROFILES}
TIMUR, SIMAL = "zanthoxylum armatum", "bombax ceiba"


def _built() -> bytes:
    return f.build_workbook(DESIGN, PROFILES, "Test Forest")


def _fill(data: bytes, plots=None, weights=None) -> bytes:
    """Type into the form the way a team would: ``plots`` {(plot, key): {column: value}}, ``weights`` [row dict]."""
    wb = load_workbook(io.BytesIO(data))
    ws = wb[f.PLOTS]
    head = {c.value: c.column for c in ws[1]}
    for r in range(2, ws.max_row + 1):
        pair = (ws.cell(r, head["plot_number"]).value, ws.cell(r, head["species_key"]).value)
        for col, val in (plots or {}).get(pair, {}).items():
            ws.cell(r, head[col]).value = val
    wsw = wb[f.WEIGHTS]
    whead = {c.value: c.column for c in wsw[1]}
    for i, row in enumerate(weights or [], 2):
        for col, val in row.items():
            wsw.cell(i, whead[col]).value = val
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def _read(data, existing=None):
    return f.read_workbook(data, ASSIGNED, existing or {}, PARTS, TODAY)


def _codes(res, severity=None):
    return [x["code"] for x in res["findings"] if severity is None or x["severity"] == severity]


# ── the form ──────────────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_the_form_lists_exactly_the_pairs_the_design_assigned():
    wb = load_workbook(io.BytesIO(_built()))
    assert wb.sheetnames == [f.PLOTS, f.WEIGHTS, f.GUIDE, f.INSTRUCTIONS]
    rows = list(wb[f.PLOTS].iter_rows(min_row=2, values_only=True))
    assert [(r[0], r[4]) for r in rows] == [(1, "bombax ceiba"), (1, "zanthoxylum armatum"), (2, "zanthoxylum armatum")]
    assert wb[f.PLOTS]["H2"].value == 500 and wb[f.PLOTS]["H3"].value == 25  # each species' own plot size
    assert [c.value for c in wb[f.PLOTS][1]][-7:] == f.PLOT_ENTRY


def test_the_guide_sheet_carries_the_method_of_each_species():
    ws = load_workbook(io.BytesIO(_built()))[f.GUIDE]
    rows = {r[0]: r for r in ws.iter_rows(min_row=2, values_only=True)}
    assert rows[TIMUR][5] == "non destructive" and rows[TIMUR][7] == 2 and rows[TIMUR][9] == "3" and rows[TIMUR][10] == 90.0
    assert rows[SIMAL][7] == 1


def test_an_empty_form_reads_as_nothing_surveyed_and_no_errors():
    res = _read(_built())
    assert res["ok"] and res["observations"] == [] and res["weights"] == []


# ── counts ────────────────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_a_filled_row_becomes_an_observation_and_zero_is_kept_as_absent():
    res = _read(_fill(_built(), {(1, TIMUR): {"visit_date": date(2026, 10, 20), "count_total": 12, "count_mature": 5, "count_small": 4, "tillers": 30},
                                 (2, TIMUR): {"visit_date": date(2026, 10, 20), "count_total": 0}}))
    assert res["ok"]
    by = {(o["plot_number"], o["species_key"]): o for o in res["observations"]}
    assert by[(1, TIMUR)]["count_total"] == 12 and by[(1, TIMUR)]["tillers"] == 30 and by[(1, TIMUR)]["visit_date"] == "2026-10-20"
    assert by[(2, TIMUR)]["count_total"] == 0   # looked, not there
    assert (1, SIMAL) not in by                  # empty: not surveyed yet


def test_devanagari_digits_and_text_dates_are_read():
    res = _read(_fill(_built(), {(1, TIMUR): {"visit_date": "२०२६-१०-२०", "count_total": "१२"}}))
    assert res["ok"] and res["observations"][0]["count_total"] == 12 and res["observations"][0]["visit_date"] == "2026-10-20"


@pytest.mark.parametrize("cell,code", [
    ({"count_total": -1}, "count.invalid"), ({"count_total": 2.5}, "count.invalid"), ({"count_total": "many"}, "count.invalid"),
    ({"count_total": 5, "count_mature": 4, "count_small": 3}, "count.parts_exceed_total"),
    ({"count_total": 3, "count_mature": 4}, "count.parts_exceed_total"),
    ({"visit_date": date(2026, 12, 1), "count_total": 1}, "date.future"),
    ({"visit_date": "last week", "count_total": 1}, "date.invalid"),
    ({"count_mature": 2}, "count.total_missing"),
])
def test_a_bad_count_row_is_an_error_with_its_row_and_column(cell, code):
    res = _read(_fill(_built(), {(1, TIMUR): cell}))
    assert not res["ok"] and code in _codes(res, "error")
    assert all(x["sheet"] == f.PLOTS and x["row"] for x in res["findings"])


def test_a_missing_date_is_only_a_warning():
    res = _read(_fill(_built(), {(1, TIMUR): {"count_total": 3}}))
    assert res["ok"] and _codes(res) == ["date.missing"]


def test_a_pair_the_design_did_not_assign_is_refused():
    data = _fill(_built(), {(1, TIMUR): {"count_total": 3, "visit_date": date(2026, 10, 1)}})
    wb = load_workbook(io.BytesIO(data))
    ws = wb[f.PLOTS]
    ws["E3"].value = "bombax ceiba" if ws["E3"].value != "bombax ceiba" else "acorus calamus"
    ws["E4"].value = "bombax ceiba"          # plot 2 never had the simal
    ws["J4"].value = 3
    out = io.BytesIO()
    wb.save(out)
    res = _read(out.getvalue())
    assert "pair.unknown" in _codes(res, "error")


def test_a_pair_listed_twice_is_refused():
    data = _fill(_built(), {(1, TIMUR): {"count_total": 3, "visit_date": date(2026, 10, 1)}})
    wb = load_workbook(io.BytesIO(data))
    ws = wb[f.PLOTS]
    for c in range(1, 16):
        ws.cell(5, c).value = ws.cell(3, c).value
    out = io.BytesIO()
    wb.save(out)
    assert "pair.duplicate" in _codes(_read(out.getvalue()), "error")


# ── weights ───────────────────────────────────────────────────────────────────────────────────────────────────────────────────

COUNT = {(1, TIMUR): {"visit_date": date(2026, 10, 20), "count_total": 12}}


def test_weights_are_numbered_in_order_and_take_the_species_usual_part():
    res = _read(_fill(_built(), COUNT, [{"plot_number": 1, "species_key": TIMUR, "fresh_weight_g": 800, "dry_weight_g": 300},
                                         {"plot_number": 1, "species_key": TIMUR, "fresh_weight_g": 900}]))
    assert res["ok"]
    assert [(w["sample_no"], w["part_group"], w["fresh_weight_g"], w["dry_weight_g"]) for w in res["weights"]] == [(1, "ङ", 800.0, 300.0), (2, "ङ", 900.0, None)]


def test_a_part_may_be_named_in_nepali():
    res = _read(_fill(_built(), COUNT, [{"plot_number": 1, "species_key": TIMUR, "fresh_weight_g": 800, "part": "पात/डाँठ"}]))
    assert res["ok"] and res["weights"][0]["part_group"] == "ग"


@pytest.mark.parametrize("row,code", [
    ({"fresh_weight_g": 100, "dry_weight_g": 120}, "weight.dry_exceeds_fresh"),
    ({"fresh_weight_g": 0}, "weight.fresh_invalid"),
    ({"fresh_weight_g": -5}, "weight.fresh_invalid"),
    ({"dry_weight_g": 50}, "weight.fresh_invalid"),
    ({"fresh_weight_g": "heavy"}, "weight.fresh_invalid"),
    ({"fresh_weight_g": 9_999_999}, "weight.fresh_invalid"),
    ({"fresh_weight_g": 100, "dry_weight_g": -1}, "weight.dry_invalid"),
    ({"fresh_weight_g": 100, "part": "roots"}, "part.unknown"),
    ({"fresh_weight_g": 100, "sample_no": 0}, "sample.invalid"),
])
def test_a_bad_weight_row_is_an_error(row, code):
    res = _read(_fill(_built(), COUNT, [{"plot_number": 1, "species_key": TIMUR, **row}]))
    assert not res["ok"] and code in _codes(res, "error")


def test_a_weight_needs_a_count_of_at_least_one():
    row = [{"plot_number": 1, "species_key": TIMUR, "fresh_weight_g": 800}]
    assert "weight.no_count" in _codes(_read(_fill(_built(), None, row)), "error")
    zero = {(1, TIMUR): {"visit_date": date(2026, 10, 20), "count_total": 0}}
    assert "weight.zero_count" in _codes(_read(_fill(_built(), zero, row)), "error")
    assert _read(_fill(_built(), None, row), existing={(1, TIMUR): 7})["ok"]   # the count was uploaded earlier


def test_a_dry_weight_far_below_the_fresh_is_a_warning_not_an_error():
    res = _read(_fill(_built(), COUNT, [{"plot_number": 1, "species_key": TIMUR, "fresh_weight_g": 1000, "dry_weight_g": 10}]))
    assert res["ok"] and "weight.dry_very_low" in _codes(res, "warning")


def test_a_repeated_sample_number_is_refused():
    rows = [{"plot_number": 1, "species_key": TIMUR, "sample_no": 1, "fresh_weight_g": 800}, {"plot_number": 1, "species_key": TIMUR, "sample_no": 1, "fresh_weight_g": 700}]
    assert "sample.duplicate" in _codes(_read(_fill(_built(), COUNT, rows)), "error")


def test_one_error_refuses_the_whole_file():
    res = _read(_fill(_built(), {(1, TIMUR): {"visit_date": date(2026, 10, 20), "count_total": 12}, (2, TIMUR): {"count_total": -3}}))
    assert not res["ok"]


# ── the file itself ───────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_a_file_that_is_not_a_workbook_is_one_plain_finding():
    res = _read(b"this is not a spreadsheet")
    assert not res["ok"] and _codes(res) == ["file.corrupt"]


def test_a_workbook_without_the_plots_sheet_or_with_a_renamed_column_is_refused():
    wb = Workbook()
    wb.active.title = "Sheet1"
    buf = io.BytesIO()
    wb.save(buf)
    assert _codes(_read(buf.getvalue())) == ["sheet.missing"]
    data = _built()
    wb = load_workbook(io.BytesIO(data))
    wb[f.PLOTS]["J1"].value = "total"
    out = io.BytesIO()
    wb.save(out)
    assert _codes(_read(out.getvalue())) == ["columns.missing"]
