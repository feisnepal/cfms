"""Entering a sample plot's findings on the map: the same checks as the form, and records are either uploaded or typed in, never both."""
from tests.integration.test_ntfp_design_api import _calc, _register, _seed_profiles
from tests.integration.test_ntfp_records_api import _design, _fill, _form, _upload


def _url(calc, plot):
    return f"/api/calculations/{calc.id}/ntfp/plots/{plot}/observations"


def _setup(client, db):
    _seed_profiles(db)
    headers, uid = _register(client)
    calc = _calc(db, uid)
    design = _design(client, headers, calc)
    plot = design["plots"][0]
    return headers, calc, plot["plot_number"], plot["species_keys"]


def test_a_plot_is_saved_with_counts_and_weights_and_read_back(client, db):
    headers, calc, n, keys = _setup(client, db)
    body = {"entries": [{"species_key": keys[0], "visit_date": "2026-10-20", "count_total": 7, "count_mature": 3,
                         "weights": [{"fresh_weight_g": 800, "dry_weight_g": 300}, {"fresh_weight_g": 900}]}]}
    r = client.put(_url(calc, n), json=body, headers=headers)
    assert r.status_code == 200, r.text
    assert (r.json()["observations_written"], r.json()["weights_written"]) == (1, 2)
    got = client.get(f"/api/calculations/{calc.id}/ntfp/observations", headers=headers).json()
    assert got["mode"] == "manual" and got["pairs_recorded"] == 1
    o = got["observations"][0]
    assert (o["plot_number"], o["count_total"], o["source"]) == (n, 7, "manual")
    assert [(w["sample_no"], w["fresh_weight_g"], w["dry_weight_g"]) for w in o["weights"]] == [(1, 800.0, 300.0), (2, 900.0, None)]


def test_saving_again_replaces_the_weights_and_an_empty_entry_clears_the_record(client, db):
    headers, calc, n, keys = _setup(client, db)
    put = lambda entries: client.put(_url(calc, n), json={"entries": entries}, headers=headers)
    assert put([{"species_key": keys[0], "count_total": 5, "weights": [{"fresh_weight_g": 100}, {"fresh_weight_g": 200}]}]).status_code == 200
    assert put([{"species_key": keys[0], "count_total": 6, "weights": [{"fresh_weight_g": 300}]}]).status_code == 200
    o = client.get(f"/api/calculations/{calc.id}/ntfp/observations", headers=headers).json()["observations"][0]
    assert o["count_total"] == 6 and [w["fresh_weight_g"] for w in o["weights"]] == [300.0]
    r = put([{"species_key": keys[0]}])
    assert r.status_code == 200 and r.json()["cleared"] == 1
    got = client.get(f"/api/calculations/{calc.id}/ntfp/observations", headers=headers).json()
    assert got["pairs_recorded"] == 0 and got["mode"] is None          # nothing left: either way is open again


def test_a_mistake_saves_nothing_and_names_the_species(client, db):
    headers, calc, n, keys = _setup(client, db)
    r = client.put(_url(calc, n), headers=headers, json={"entries": [
        {"species_key": keys[0], "count_total": 4, "count_mature": 9}]})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "plot.invalid"
    f = next(f for f in r.json()["detail"]["findings"] if f["severity"] == "error")
    assert f["code"] == "count.parts_exceed_total" and f["species_key"] == keys[0]
    assert client.get(f"/api/calculations/{calc.id}/ntfp/observations", headers=headers).json()["pairs_recorded"] == 0
    r = client.put(_url(calc, n), headers=headers, json={"entries": [{"species_key": keys[0], "count_total": 3, "weights": [{"fresh_weight_g": 5, "dry_weight_g": 9}]}]})
    assert r.status_code == 422 and "weight.dry_exceeds_fresh" in [f["code"] for f in r.json()["detail"]["findings"]]


def test_a_species_the_plot_does_not_carry_and_an_unknown_plot_are_refused(client, db):
    headers, calc, n, keys = _setup(client, db)
    r = client.put(_url(calc, n), headers=headers, json={"entries": [{"species_key": "no such species", "count_total": 1}]})
    assert r.status_code == 422 and r.json()["detail"]["findings"][0]["code"] == "pair.unknown"
    r = client.put(_url(calc, 9999), headers=headers, json={"entries": [{"species_key": keys[0], "count_total": 1}]})
    assert r.status_code == 404 and r.json()["detail"]["code"] == "unknown_plot"


def test_records_are_either_uploaded_or_entered_never_both(client, db):
    headers, calc, n, keys = _setup(client, db)
    assert client.put(_url(calc, n), headers=headers, json={"entries": [{"species_key": keys[0], "count_total": 2}]}).status_code == 200
    up = _upload(client, headers, calc, _fill(_form(client, headers, calc)))
    assert up.status_code == 409 and up.json()["detail"]["code"] == "mode_conflict"
    assert client.delete(f"/api/calculations/{calc.id}/ntfp/observations", headers=headers).status_code == 200
    assert _upload(client, headers, calc, _fill(_form(client, headers, calc))).status_code == 200
    r = client.put(_url(calc, n), headers=headers, json={"entries": [{"species_key": keys[0], "count_total": 2}]})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "mode_conflict"
    assert client.get(f"/api/calculations/{calc.id}/ntfp/observations", headers=headers).json()["mode"] == "upload"


def test_a_stranger_cannot_enter_a_plot(client, db):
    headers, calc, n, keys = _setup(client, db)
    other, _ = _register(client)
    assert client.put(_url(calc, n), headers=other, json={"entries": [{"species_key": keys[0], "count_total": 1}]}).status_code == 403
