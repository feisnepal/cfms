"""The expert review sheet of the provisional cards (``app.services.ntfp_card_review``)."""
import io
from types import SimpleNamespace

import pytest
from openpyxl import load_workbook

from app.services import ntfp_card_review as rv

CARDS = [
    {"species_key": "a one", "nepali_name": "क", "scientific_name": "A one", "card_status": "provisional", "parts_harvested": "जरा", "growth_class": "herb",
     "growth_how": "the species master lists it as 'Medicinal Herb'", "sampling_method": "destructive", "plot": "4-25", "individuals": "10-20"},
    {"species_key": "b two", "nepali_name": "ख", "scientific_name": "B two", "card_status": "provisional", "parts_harvested": "बोक्रा", "growth_class": "tree",
     "growth_how": "guessed from the part harvested (bark); confirm", "sampling_method": "semi_destructive", "plot": "100-500", "individuals": "3"},
]
SOURCES = [{"key": "DOF2069", "title": "t", "publisher": "p", "year": "2012", "read_status": "read", "url": None, "licence": "-"}]


def _fill(data, edits):
    wb = load_workbook(io.BytesIO(data))
    ws = wb[rv.CARDS]
    head = {c.value: c.column for c in ws[1]}
    for r in range(2, ws.max_row + 1):
        for col, val in edits.get(ws.cell(r, head["species_key"]).value, {}).items():
            ws.cell(r, head[col]).value = val
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def test_the_sheet_lists_the_derived_values_in_grey_and_leaves_the_review_columns_empty():
    wb = load_workbook(io.BytesIO(rv.build_sheet(CARDS, SOURCES)))
    assert wb.sheetnames == [rv.CARDS, "Sources", "How to review"]
    ws = wb[rv.CARDS]
    assert [c.value for c in ws[1]] == rv.FIXED + rv.REVIEW
    assert [ws.cell(2, 1).value, ws.cell(3, 1).value] == ["a one", "b two"]
    assert all(ws.cell(2, i).value is None for i in range(len(rv.FIXED) + 1, len(rv.FIXED) + len(rv.REVIEW) + 1))


def test_an_unfilled_sheet_gives_no_rows_and_a_filled_one_gives_only_the_answered_rows():
    data = rv.build_sheet(CARDS, SOURCES)
    assert rv.read_sheet(data) == []
    rows = rv.read_sheet(_fill(data, {"a one": {"confirmed": "Yes"}, "b two": {"growth_class": "shrub", "plot_min_sqm": 25, "plot_max_sqm": 25}}))
    assert [r["species_key"] for r in rows] == ["a one", "b two"]
    assert rows[0]["confirmed"] == "Yes" and rows[1]["growth_class"] == "shrub" and rows[1]["plot_min_sqm"] == 25


def test_a_file_that_is_not_the_sheet_is_refused_plainly():
    with pytest.raises(ValueError, match="readable"):
        rv.read_sheet(b"nope")
    from openpyxl import Workbook

    wb = Workbook()
    wb.active.title = "Other"
    buf = io.BytesIO()
    wb.save(buf)
    with pytest.raises(ValueError, match="missing"):
        rv.read_sheet(buf.getvalue())
    wb = load_workbook(io.BytesIO(rv.build_sheet(CARDS, SOURCES)))
    wb[rv.CARDS].cell(1, len(rv.FIXED) + 2).value = "growth"
    buf = io.BytesIO()
    wb.save(buf)
    with pytest.raises(ValueError, match="renamed"):
        rv.read_sheet(buf.getvalue())


def test_card_rows_list_only_provisional_cards_and_put_the_guessed_growth_class_first():
    mk = lambda key, status, card=True: SimpleNamespace(species_key=key, has_method_card=card, card_status=status, nepali_name="x", scientific_name=key, part_ne="p", growth_class="herb",
                                                        sampling_method="destructive", plot_min_sqm=4, plot_max_sqm=25, n_individuals_min=10, n_individuals_max=20)
    profs = [mk("c", "provisional"), mk("a", "provisional"), mk("done", "expert_confirmed"), mk("nocard", None, card=False), mk("b", "documented")]
    how = {"c": {"growth_class": "guessed from the part harvested; confirm"}, "a": {"growth_class": "the species master lists it"}, "b": {"growth_class": ""}}
    rows = rv.card_rows(profs, how)
    assert [r["species_key"] for r in rows] == ["c", "a"]          # documented and confirmed cards are not on the sheet
    assert rows[0]["plot"] == "4-25" and rows[0]["individuals"] == "10-20"
