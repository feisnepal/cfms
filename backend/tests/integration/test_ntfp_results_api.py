"""NTFP inventory API, phase 4: the results endpoint and its link to the plan (``/ntfp/results``, OP table 39)."""
import io
from datetime import date

from openpyxl import load_workbook

from app.models.op_data_cache import OpDataCache
from tests.integration.test_ntfp_design_api import BODY, _calc, _register, _seed_profiles
from tests.integration.test_ntfp_records_api import XLSX


def _upload_counts(client, headers, calc, counts=None, weights=None):
    """Download the form and fill it: ``counts`` {(plot, key): total}; ``weights`` [(plot, key, fresh, dry)]."""
    form = client.get(f"/api/calculations/{calc.id}/ntfp/form", headers=headers).content
    wb = load_workbook(io.BytesIO(form))
    ws = wb["Plots"]
    head = {c.value: c.column for c in ws[1]}
    for r in range(2, ws.max_row + 1):
        pair = (ws.cell(r, head["plot_number"]).value, ws.cell(r, head["species_key"]).value)
        if counts is None or pair in counts:
            ws.cell(r, head["visit_date"]).value = date(2026, 10, 20)
            ws.cell(r, head["count_total"]).value = (counts or {}).get(pair, 3)
    wsw = wb["Weights"]
    for i, (plot, key, fresh, dry) in enumerate(weights or [], 2):
        wsw.cell(i, 1).value, wsw.cell(i, 2).value, wsw.cell(i, 5).value, wsw.cell(i, 6).value = plot, key, fresh, dry
    out = io.BytesIO()
    wb.save(out)
    r = client.post(f"/api/calculations/{calc.id}/ntfp/upload", headers=headers, files={"file": ("f.xlsx", out.getvalue(), XLSX[2])})
    assert r.status_code == 200, r.text


def test_results_need_a_design_and_start_empty(client, db):
    _seed_profiles(db)
    headers, uid = _register(client)
    calc = _calc(db, uid)
    url = f"/api/calculations/{calc.id}/ntfp/results"
    assert client.get(url, headers=headers).status_code == 404
    client.post(f"/api/calculations/{calc.id}/ntfp/design", json=BODY, headers=headers)
    res = client.get(url, headers=headers).json()
    assert res["ivi_parts"] == 2 and res["survey"]["pairs_recorded"] == 0
    assert {s["species_key"] for s in res["species"]} == {"zanthoxylum armatum", "bombax ceiba"}
    assert all(s["plots_surveyed"] == 0 and "not_surveyed" in s["warnings"] and s["ivi"] is None for s in res["species"])


def test_results_follow_the_uploaded_records_with_price_rates(client, db):
    _seed_profiles(db)
    headers, uid = _register(client)
    calc = _calc(db, uid)
    design = client.post(f"/api/calculations/{calc.id}/ntfp/design", json=BODY, headers=headers).json()
    timur = "zanthoxylum armatum"
    first = next(p["plot_number"] for p in design["plots"] if timur in p["species_keys"])
    _upload_counts(client, headers, calc, weights=[(first, timur, 800, 300), (first, timur, 900, 330)])

    res = client.get(f"/api/calculations/{calc.id}/ntfp/results", headers=headers).json()
    t = next(s for s in res["species"] if s["species_key"] == timur)
    assert t["plots_surveyed"] == t["plots_assigned"] and t["plots_present"] == t["plots_surveyed"] and t["frequency_pct"] == 100.0
    assert t["density_per_ha"] == 3 / 25 * 10000                     # 3 plants on every 25 m2 plot
    (part,) = t["parts"]
    assert part["part_group"] == "ङ" and part["samples"] == 2 and part["mean_fresh_g"] == 850.0
    assert part["conversion_factor"] == round(630 / 1700, 4)
    assert part["harvest_fraction_pct"] == 90.0 and part["scale_factor"] == round(100 / 90, 4)     # the guideline card: 90 % of the fruit is taken
    assert part["yield_fresh_kg_ha"] == round(3 / 25 * 10000 * 850 * (100 / 90) / 1000, 3)       # weights scaled up to the whole part
    assert part["price"]["basis"] == "schedule7" and part["price"]["estimated"] is False and part["price"]["npr_per_unit"] > 0
    assert t["nepali_name"] and t["scientific_name"] == "Zanthoxylum armatum"
    assert round(res["species"][0]["ivi"] + res["species"][1]["ivi"], 1) == 200.0   # relative frequency + density, each over 100


def test_the_plan_gets_table_39_only_when_records_exist_and_changes_clear_its_cache(client, db):
    from app.services.operational_plan.ntfp_inventory_op import get_ntfp_inventory_data

    _seed_profiles(db)
    headers, uid = _register(client)
    calc = _calc(db, uid)
    assert get_ntfp_inventory_data(db, calc.id) == {"available": False}              # no design
    client.post(f"/api/calculations/{calc.id}/ntfp/design", json=BODY, headers=headers)
    assert get_ntfp_inventory_data(db, calc.id) == {"available": False}              # a design but no records
    db.add(OpDataCache(calculation_id=calc.id, data={"_cache_version": 1}))
    db.commit()
    _upload_counts(client, headers, calc)
    assert db.query(OpDataCache).filter_by(calculation_id=calc.id).count() == 0      # the upload cleared the plan's cache
    inv = get_ntfp_inventory_data(db, calc.id)
    assert inv["available"] and inv["table_rows"] and inv["summary"]["species_surveyed"] == 2
    assert all(set(r) >= {"sn", "name", "frequency", "density", "ivi", "note"} for r in inv["table_rows"])


def test_a_stranger_cannot_read_the_results(client, db):
    _seed_profiles(db)
    headers, uid = _register(client)
    other, _ = _register(client)
    calc = _calc(db, uid)
    assert client.get(f"/api/calculations/{calc.id}/ntfp/results", headers=other).status_code == 403
