"""NTFP inventory API, phase 3: the field form, the upload and the stored records (``app/api/ntfp.py``)."""
import io
import uuid
from datetime import date

from openpyxl import load_workbook
from shapely import wkt as shp_wkt
from shapely.geometry import box

from app.models.calculation import Calculation
from app.models.ntfp_method import NtfpObservation, NtfpSamplePlot, NtfpSamplingDesign, NtfpWeightSample
from tests.integration.test_ntfp_design_api import BODY, _calc, _register, _seed_profiles

XLSX = ("form.xlsx", None, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


def _design(client, headers, calc):
    r = client.post(f"/api/calculations/{calc.id}/ntfp/design", json=BODY, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def _form(client, headers, calc) -> bytes:
    r = client.get(f"/api/calculations/{calc.id}/ntfp/form", headers=headers)
    assert r.status_code == 200, r.text
    assert "spreadsheetml" in r.headers["content-type"] and "NTFP_Form" in r.headers["content-disposition"]
    return r.content


def _fill(data: bytes, rows: int = 3, weights: bool = True) -> bytes:
    """Count the first ``rows`` rows (plot 1's species first); weigh the first row's species twice."""
    wb = load_workbook(io.BytesIO(data))
    ws = wb["Plots"]
    head = {c.value: c.column for c in ws[1]}
    first_plot, first_key = ws.cell(2, head["plot_number"]).value, ws.cell(2, head["species_key"]).value
    for r in range(2, 2 + rows):
        ws.cell(r, head["visit_date"]).value = date(2026, 10, 20)
        ws.cell(r, head["count_total"]).value = 10 + r
        ws.cell(r, head["count_mature"]).value = 4
    if weights:
        wsw = wb["Weights"]
        for i, (fresh, dry) in enumerate([(800, 300), (900, None)], 2):
            wsw.cell(i, 1).value, wsw.cell(i, 2).value, wsw.cell(i, 5).value, wsw.cell(i, 6).value = first_plot, first_key, fresh, dry
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def _upload(client, headers, calc, data, name="form.xlsx"):
    return client.post(f"/api/calculations/{calc.id}/ntfp/upload", headers=headers,
                       files={"file": (name, data, XLSX[2])})


def test_form_needs_a_design_first(client, db):
    _seed_profiles(db)
    headers, uid = _register(client)
    calc = _calc(db, uid)
    r = client.get(f"/api/calculations/{calc.id}/ntfp/form", headers=headers)
    assert r.status_code == 404 and r.json()["detail"]["code"] == "no_design"


def test_download_fill_upload_and_read_back(client, db):
    _seed_profiles(db)
    headers, uid = _register(client)
    calc = _calc(db, uid)
    design = _design(client, headers, calc)
    form = _form(client, headers, calc)
    pairs = sum(len(p["species_keys"]) for p in design["plots"])
    assert load_workbook(io.BytesIO(form))["Plots"].max_row == pairs + 1

    r = _upload(client, headers, calc, _fill(form))
    assert r.status_code == 200, r.text
    assert r.json()["observations_written"] == 3 and r.json()["weights_written"] == 2

    got = client.get(f"/api/calculations/{calc.id}/ntfp/observations", headers=headers).json()
    assert got["pairs_assigned"] == pairs and got["pairs_recorded"] == 3 and got["weights"] == 2
    first = got["observations"][0]
    assert first["visit_date"] == "2026-10-20" and first["count_mature"] == 4
    assert [(w["sample_no"], w["fresh_weight_g"], w["dry_weight_g"]) for w in first["weights"]] == [(1, 800.0, 300.0), (2, 900.0, None)]


def test_uploading_again_replaces_what_the_file_names_and_keeps_the_rest(client, db):
    _seed_profiles(db)
    headers, uid = _register(client)
    calc = _calc(db, uid)
    _design(client, headers, calc)
    form = _form(client, headers, calc)
    assert _upload(client, headers, calc, _fill(form, rows=3)).status_code == 200

    # a second file that counts only the first row, with different numbers and one weight
    wb = load_workbook(io.BytesIO(form))
    ws = wb["Plots"]
    head = {c.value: c.column for c in ws[1]}
    ws.cell(2, head["visit_date"]).value = date(2026, 10, 21)
    ws.cell(2, head["count_total"]).value = 99
    wsw = wb["Weights"]
    wsw.cell(2, 1).value, wsw.cell(2, 2).value, wsw.cell(2, 5).value = ws.cell(2, 1).value, ws.cell(2, head["species_key"]).value, 123
    out = io.BytesIO()
    wb.save(out)
    second = _upload(client, headers, calc, out.getvalue())
    assert second.status_code == 200, second.text

    got = client.get(f"/api/calculations/{calc.id}/ntfp/observations", headers=headers).json()
    assert got["pairs_recorded"] == 3                                   # the other two are kept
    assert got["observations"][0]["count_total"] == 99
    assert [w["fresh_weight_g"] for w in got["observations"][0]["weights"]] == [123.0]   # replaced, not appended
    assert got["observations"][1]["count_total"] == 13                  # untouched


def test_a_form_with_a_mistake_imports_nothing_and_says_where(client, db):
    _seed_profiles(db)
    headers, uid = _register(client)
    calc = _calc(db, uid)
    _design(client, headers, calc)
    form = _form(client, headers, calc)
    wb = load_workbook(io.BytesIO(_fill(form)))
    ws = wb["Plots"]
    head = {c.value: c.column for c in ws[1]}
    ws.cell(3, head["count_total"]).value = -4
    out = io.BytesIO()
    wb.save(out)
    r = _upload(client, headers, calc, out.getvalue())
    assert r.status_code == 422
    detail = r.json()["detail"]
    assert detail["code"] == "form.invalid" and any(f["code"] == "count.invalid" and f["row"] == 3 and f["sheet"] == "Plots" for f in detail["findings"])
    assert db.query(NtfpObservation).join(NtfpSamplePlot).join(NtfpSamplingDesign).filter(NtfpSamplingDesign.calculation_id == calc.id).count() == 0


def test_wrong_files_are_refused_plainly(client, db):
    _seed_profiles(db)
    headers, uid = _register(client)
    calc = _calc(db, uid)
    _design(client, headers, calc)
    assert _upload(client, headers, calc, b"a,b\n1,2\n", name="form.csv").status_code == 400
    assert _upload(client, headers, calc, b"", name="form.xlsx").status_code == 400
    r = _upload(client, headers, calc, b"not a workbook", name="form.xlsx")
    assert r.status_code == 422 and r.json()["detail"]["findings"][0]["code"] == "file.corrupt"


def test_a_design_with_records_cannot_be_replaced_or_deleted_until_the_records_go(client, db):
    _seed_profiles(db)
    headers, uid = _register(client)
    calc = _calc(db, uid)
    _design(client, headers, calc)
    assert _upload(client, headers, calc, _fill(_form(client, headers, calc))).status_code == 200
    url = f"/api/calculations/{calc.id}/ntfp"
    r = client.post(url + "/design", json={**BODY, "seed": 77}, headers=headers)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "has_records"
    assert client.delete(url + "/design", headers=headers).status_code == 409
    assert client.get(url + "/observations", headers=headers).json()["pairs_recorded"] == 3   # nothing was lost

    assert client.delete(url + "/observations", headers=headers).json() == {"deleted": 3}
    assert client.post(url + "/design", json={**BODY, "seed": 77}, headers=headers).status_code == 200
    assert client.get(url + "/observations", headers=headers).json()["pairs_recorded"] == 0


def test_deleting_the_forest_deletes_its_records(client, db):
    _seed_profiles(db)
    headers, uid = _register(client)
    calc = _calc(db, uid)
    _design(client, headers, calc)
    assert _upload(client, headers, calc, _fill(_form(client, headers, calc))).status_code == 200
    assert db.query(NtfpWeightSample).count() >= 2
    obs_ids = [o.id for o in db.query(NtfpObservation).join(NtfpSamplePlot).join(NtfpSamplingDesign).filter(NtfpSamplingDesign.calculation_id == calc.id).all()]
    assert len(obs_ids) == 3
    db.expire_all()
    db.delete(db.get(Calculation, calc.id))
    db.commit()
    assert db.query(NtfpObservation).filter(NtfpObservation.id.in_(obs_ids)).count() == 0


def test_a_stranger_cannot_download_upload_or_read(client, db):
    _seed_profiles(db)
    headers, uid = _register(client)
    other, _ = _register(client)
    calc = _calc(db, uid)
    _design(client, headers, calc)
    base = f"/api/calculations/{calc.id}/ntfp"
    assert client.get(base + "/form", headers=other).status_code == 403
    assert client.get(base + "/observations", headers=other).status_code == 403
    assert client.delete(base + "/observations", headers=other).status_code == 403
    assert _upload(client, other, calc, b"x").status_code == 403
