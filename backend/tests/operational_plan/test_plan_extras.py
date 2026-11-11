"""Derived scalars / tables for the Rambhadevi-style plan (plan_extras.py, table_columns.py)."""
import json

from app.services.operational_plan import plan_extras as pe
from app.services.operational_plan.table_columns import ordered_headers


def _ln(activity, year, qty, unit="हेक्टर", block="", **kw):
    base = {"activity": activity, "program": kw.pop("program", "वन सम्बर्दन कार्यहरु"), "unit": unit, "map_kind": "",
            "is_felling": False, "potential_id": kw.pop("pid", 1), "sn": "", "year": year, "quantity": qty,
            "budget": kw.pop("budget", 0.0), "block": block}
    base.update(kw)
    return base


def test_fy_labels_from_devanagari_or_latin_text():
    assert pe.fy_labels("२०८२/०८३")[:2] == ["२०८२/८३", "२०८३/८४"]
    assert pe.fy_labels("2082/083")[9] == "२०९१/९२"
    assert pe.fy_labels("") == [] and pe.fy_labels("n/a") == []


def test_committee_scalars_count_by_gender():
    raw = {"committees": {"user_committee": {"members": [
        {"gender": "महिला"}, {"gender": "महिला"}, {"gender": "पुरूष"}]}}}
    assert pe.committee_scalars(raw) == {"uc_female_members": 2, "uc_male_members": 1}
    assert pe.committee_scalars({}) == {"uc_female_members": 0, "uc_male_members": 0}


def test_silviculture_schedule_places_operations_by_year_and_unit():
    lines = [
        _ln("पुनरुत्पादन कटानका लागि वार्षिक कार्यक्षेत्र (Annual working unit) सीमांकन", 1, 1.83, block="C1S8"),
        _ln("पुनरुत्पादन कटान क्षेत्रमा तारबार गर्ने", 1, 5, block="C1S8"),          # a follow-up, not the felling itself
        _ln("पुनरुत्पादन तयारी कटान", 5, 18.34, block="C1S7"),
        _ln("थिनिङ्ग तथा सुधार कटान", 3, 18.34, block="C1S3"),
        _ln("पुनरुत्पादन अभिवृद्धि क्रियाकलाप", 1, 1.834, block="C1S8"),
    ]
    rows = pe.silviculture_schedule(lines, pe.fy_labels("२०८२/०८३"))
    assert len(rows) == 10 and rows[0]["बर्ष"] == "प्रथम" and rows[0]["आ.व."] == "२०८२/८३"
    assert rows[0]["पुनरुत्पादन_कटान_स्थान"] == "C1S8" and rows[0]["पुनरुत्पादन_कटान_हेक्टर"] == 1.83
    assert rows[4]["पुनरुत्पादन_तयारी_कटान_स्थान"] == "C1S7"
    assert rows[2]["थिनिङ्ग_तथा_सुधार_कटान_स्थान"] == "C1S3"
    assert rows[0]["पुनरुत्पादन_अभिवृद्धि_हेक्टर"] == 1.83
    assert pe.silviculture_schedule([], []) == []


def test_felling_yield_by_year_sums_per_activity_and_year():
    lines = [_ln("काठ", 1, 3049, unit="क्यु.फि.", is_felling=True), _ln("काठ", 1, 1, unit="क्यु.फि.", is_felling=True),
             _ln("काठ", 2, 3049, unit="क्यु.फि.", is_felling=True), _ln("दाउरा", 1, 12.6, unit="चट्टा", is_felling=True),
             _ln("नर्सरी निर्माण", 1, 1, unit="वटा")]
    rows = {r["क्रियाकलाप"]: r for r in pe.felling_yield_by_year(lines)}
    assert set(rows) == {"काठ", "दाउरा"}
    assert rows["काठ"]["बर्ष_१"] == 3050 and rows["काठ"]["बर्ष_२"] == 3049 and rows["काठ"]["जम्मा"] == 6099


def test_fire_line_plan_totals_kilometres():
    lines = [_ln("अग्नि नियन्त्रण रेखा निर्माण तथा मर्मतसम्भार", 1, 0.33, unit="कि.मि.", block="C1S8", map_kind="fire_line"),
             _ln("अग्नि नियन्त्रण रेखा निर्माण तथा मर्मतसम्भार", 2, 0.55, unit="कि.मि.", block="C1S2", map_kind="fire_line")]
    rows = pe.fire_line_plan(lines, pe.fy_labels("२०८२/०८३"))
    assert rows[-1]["सि.न."] == "जम्मा" and rows[-1]["परिमाण_कि.मी"] == 0.88
    assert rows[0]["क्रियाकलाप"].startswith("C1S8")


def test_annual_budget_table_has_quantity_and_budget_rows_in_thousands_and_skips_empty_activities():
    lines = [_ln("चरिचरण नियन्त्रण", y, 1, unit="प्याकेज", program="वन संरक्षण कार्यहरु", budget=20000.0) for y in range(1, 11)]
    lines.append(_ln("कुनै काम नगरिने", 1, 0, program="वन संरक्षण कार्यहरु"))
    rows = pe.annual_budget_table(lines)
    names = [r["कार्यक्रमको_नाम"] for r in rows]
    assert "कुनै काम नगरिने" not in names
    qty = next(r for r in rows if r["कार्यक्रमको_नाम"] == "चरिचरण नियन्त्रण")
    bud = rows[rows.index(qty) + 1]
    assert qty["जम्मा"] == 10 and qty["दर_हजारमा"] == 20.0
    assert bud["इकाई"] == "बजेट" and bud["बर्ष_१"] == 20.0 and bud["जम्मा"] == 200.0
    assert rows[-1]["जम्मा"] == 200.0


def test_aspect_slope_and_erosion_words():
    ra = {"aspect": {"percentages": {"E": 0.8, "SE": 20.9, "S": 31.4, "W": 22.0}},
          "slope": {"percentages": {"gentle": 5, "moderate": 20, "steep": 60, "very_steep": 15}}}
    assert pe.aspect_dominant_names(ra) == "दक्षिण पूर्व, दक्षिण, पश्चिम"
    assert pe.slope_range_deg(ra) == "० देखि ४५ डिग्री भन्दा बढी"
    assert pe.slope_range_deg({"slope": {"percentages": {"gentle": 100}}}) == "० देखि १९ डिग्री"
    assert pe.slope_range_deg({}) is None
    assert pe.erosion_status_word({"soil_loss_mean_t_ha": 3.0, "soil_loss_available": True}) == "न्यून"
    assert pe.erosion_status_word({"soil_loss_mean_t_ha": 25.47, "soil_loss_severity_breaks": [5, 10, 20, 40, 80]}) == "धेरै उच्च"
    assert pe.erosion_status_word({}) is None


def test_column_order_survives_a_jsonb_style_key_reorder():
    rows = [{"क्र.सं.": "१.१", "कार्यक्रमको_नाम": "x", "इकाई": "प्याकेज", "दर_हजारमा": 1, "बर्ष_१": 1, "जम्मा": 1}]
    scrambled = [dict(sorted(rows[0].items(), key=lambda kv: (len(kv[0].encode()), kv[0].encode())))]  # what JSONB does
    assert list(scrambled[0].keys()) != list(rows[0].keys())
    back = json.loads(json.dumps(scrambled, ensure_ascii=False))
    assert ordered_headers("ya_annual_budget_table", back) == ["क्र.सं.", "कार्यक्रमको_नाम", "इकाई", "दर_हजारमा", "बर्ष_१", "जम्मा"]
    assert ordered_headers("some_other_table", [{"b": 1, "a": 2, "_hidden": 3}]) == ["b", "a"]
    assert ordered_headers("hh_caste_prosperity_table", [{"जम्मा": 1, "सम्पन्न": 1, "अति विपन्न": 0, "जातजाति": "x", "मध्यम": 1}]) == \
        ["जातजाति", "अति विपन्न", "मध्यम", "सम्पन्न", "जम्मा"]
