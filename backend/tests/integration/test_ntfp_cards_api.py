"""NTFP method cards with their sources: the card and source endpoints, the catalogue fields, the harvest-plan hint and the expert review."""
import pytest

from app.core import ntfp_sources as src
from app.core.ntfp_methods import profiles
from app.models.ntfp_method import NtfpMethodProfile, NtfpMethodValue, NtfpSource
from app.services import ntfp_card_service as cards
from tests.integration.test_ntfp_design_api import BODY, _calc, _register, _seed_profiles
from tests.integration.test_ntfp_harvest_api import TIMUR, _surveyed

JAT = "nardostachys jatamansi"


@pytest.fixture(autouse=True)
def _remove_the_test_species(db):
    """The review tests make a species and review sources in the shared database: take them out again so they never show in the real species list."""
    yield
    db.rollback()
    db.query(NtfpMethodValue).filter((NtfpMethodValue.species_key.like("zz %")) | (NtfpMethodValue.source_key.like("REVIEW-%"))).delete(synchronize_session=False)
    db.query(NtfpSource).filter(NtfpSource.key.like("REVIEW-%")).delete(synchronize_session=False)
    db.query(NtfpMethodProfile).filter(NtfpMethodProfile.species_key.like("zz %")).delete(synchronize_session=False)
    db.commit()


def _seed_cards(db):
    """The migration seeds the sources and values; a test database built from the models alone does not."""
    _seed_profiles(db)
    if db.query(NtfpSource).count():
        return
    for k, s in src.SOURCES.items():
        db.add(NtfpSource(key=k, **{c: s.get(c) for c in ("title", "publisher", "year", "url", "tier", "read_status", "licence", "note")}))
    db.flush()
    for v in src.all_documented_values(profiles()):
        db.add(NtfpMethodValue(**v))
    db.commit()


def _card(client, headers, calc, key=JAT):
    return client.get(f"/api/calculations/{calc.id}/ntfp/profiles/{key}", headers=headers)


def test_a_card_lists_every_value_with_its_source_and_flags_disagreement(client, db):
    _seed_cards(db)
    headers, uid = _register(client)
    calc = _calc(db, uid)
    r = _card(client, headers, calc)
    assert r.status_code == 200, r.text
    card = r.json()
    facts = {(f["field"], f["part_group"]): f for f in card["facts"]}
    plot = facts[("plot_area_sqm", None)]["chosen"]
    assert (plot["source_key"], plot["status"], plot["locator"]) == ("DOF2069", "documented", "Annex 2") and plot["source_title"]
    aah = facts[("aah_pct", "क")]
    assert aah["chosen"]["value_num"] == 80 and aah["chosen"]["source_key"] == "ANSAB2022" and aah["chosen"]["source_url"].startswith("https://ansab.org.np")
    season = facts[("season", "क")]                      # the guideline's season (unreviewed) beside ANSAB's (documented)
    assert season["chosen"]["source_key"] == "ANSAB2022" and {o["source_key"] for o in season["others"]} == {"DOF2069"} and season["conflict"] is True
    assert set(card["sources"]) >= {"DOF2069", "ANSAB2022"} and card["card_status"] in ("documented", "provisional", "expert_confirmed", None)


def test_an_unknown_species_is_a_404_and_a_stranger_is_refused(client, db):
    _seed_cards(db)
    headers, uid = _register(client)
    other, _ = _register(client)
    calc = _calc(db, uid)
    r = _card(client, headers, calc, "no such species")
    assert r.status_code == 404 and r.json()["detail"]["code"] == "unknown_species"
    assert _card(client, other, calc).status_code == 403
    assert client.get(f"/api/calculations/{calc.id}/ntfp/sources", headers=other).status_code == 403


def test_the_sources_endpoint_separates_documents_read_from_leads(client, db):
    _seed_cards(db)
    headers, uid = _register(client)
    calc = _calc(db, uid)
    got = client.get(f"/api/calculations/{calc.id}/ntfp/sources", headers=headers).json()["sources"]
    by = {s["key"]: s for s in got}
    assert by["DOF2069"]["read_status"] == "read" and by["ANSAB2022"]["licence"].startswith("Non-commercial")
    assert by["ICFRE-2020"]["read_status"] == "read" and by["ICFRE-2020"]["tier"] > by["ANSAB2022"]["tier"] and by["HFRI-2009"]["read_status"] == "lead"
    assert [s["tier"] for s in got] == sorted(s["tier"] for s in got)


def test_the_catalogue_carries_the_card_status_and_the_chosen_harvest_and_season(client, db):
    _seed_cards(db)
    headers, uid = _register(client)
    calc = _calc(db, uid)
    species = client.get(f"/api/calculations/{calc.id}/ntfp/species", headers=headers).json()["species"]
    jat = next(s for s in species if s["species_key"] == JAT)
    assert jat["aah"][0]["value_num"] == 80 and jat["aah"][0]["source_key"] == "ANSAB2022"
    assert jat["season"] and jat["season"][0]["part_group"] == "क" and "card_status" in jat


def test_the_harvest_plan_row_carries_the_annual_allowable_harvest_of_its_part(client, db):
    _seed_cards(db)
    headers, uid, calc = _surveyed(client, db)
    rows = client.get(f"/api/calculations/{calc.id}/ntfp/harvest-plan", headers=headers).json()["rows"]
    timur = next(r for r in rows if r["species_key"] == TIMUR)
    assert timur["aah"]["pct_min"] == 80 and timur["aah"]["source_key"] in ("ANSAB2010", "ANSAB2022") and timur["aah"]["locator"]


# ── the expert review ────────────────────────────────────────────────────────────────────────────────────────────────────────

def _provisional(db, key="zz test herb"):
    row = db.query(NtfpMethodProfile).filter_by(species_key=key).first()
    if row is None:
        row = NtfpMethodProfile(species_key=key, scientific_name="Zz test", nepali_name="परीक्षण", has_method_card=True, card_status="provisional", growth_class="herb",
                                part_groups=["क"], sampling_method="destructive", plot_min_sqm=4, plot_max_sqm=25, n_individuals_min=10, n_individuals_max=20)
        db.add(row)
        db.add(NtfpMethodValue(species_key=key, field="plot_area_sqm", value_num=4, value_num2=25, source_key="RULE", locator="t", status="derived", chosen=True))
        db.commit()
    return row


def test_a_reviewer_can_confirm_a_provisional_card_as_it_stands(client, db):
    _seed_cards(db)
    _provisional(db)
    out = cards.apply_review(db, [{"species_key": "zz test herb", "confirmed": "Yes"}], "A. Reviewer")
    db.commit()
    assert out["cards_confirmed"] == 1 and out["values_written"] >= 1
    db.expire_all()
    assert db.query(NtfpMethodProfile).filter_by(species_key="zz test herb").one().card_status == "expert_confirmed"
    v = db.query(NtfpMethodValue).filter_by(species_key="zz test herb", field="plot_area_sqm", chosen=True).one()
    assert (v.status, v.reviewed_by) == ("expert_confirmed", "A. Reviewer")


def test_a_correction_becomes_a_new_chosen_value_and_the_old_one_stays_as_history(client, db):
    _seed_cards(db)
    _provisional(db)
    cards.apply_review(db, [{"species_key": "zz test herb", "confirmed": "no", "plot_min_sqm": "9", "plot_max_sqm": "16", "growth_class": "shrub", "maturity": "after fruiting"}], "B. Reviewer")
    db.commit()
    db.expire_all()
    prof = db.query(NtfpMethodProfile).filter_by(species_key="zz test herb").one()
    assert (prof.growth_class, float(prof.plot_min_sqm), float(prof.plot_max_sqm), prof.maturity_ne, prof.card_status) == ("shrub", 9.0, 16.0, "after fruiting", "expert_confirmed")
    plot = db.query(NtfpMethodValue).filter_by(species_key="zz test herb", field="plot_area_sqm").all()
    chosen = [v for v in plot if v.chosen]
    assert len(chosen) == 1 and chosen[0].source_key.startswith("REVIEW-") and chosen[0].status == "expert_confirmed"
    assert len(plot) >= 2 and any(v.source_key == "RULE" and not v.chosen for v in plot)      # the derived value is kept
    assert db.get(NtfpSource, chosen[0].source_key).tier == 0                                    # a reviewer outranks every document


@pytest.mark.parametrize("row,fragment", [
    ({"species_key": "no such species", "confirmed": "yes"}, "Unknown species"),
    ({"species_key": "zz test herb", "growth_class": "bush"}, "growth class"),
    ({"species_key": "zz test herb", "sampling_method": "cut it down"}, "sampling method"),
    ({"species_key": "zz test herb", "plot_min_sqm": "-3"}, "0 or more"),
    ({"species_key": "zz test herb", "plot_min_sqm": "x"}, "must be a number"),
    ({"species_key": "zz test herb", "plot_min_sqm": "30", "plot_max_sqm": "10"}, "above the maximum"),
])
def test_a_bad_review_row_is_refused_and_nothing_is_written(client, db, row, fragment):
    _seed_cards(db)
    _provisional(db)
    before = db.query(NtfpMethodValue).count()
    with pytest.raises(cards.ReviewError, match=fragment):
        cards.apply_review(db, [{"species_key": "zz test herb", "confirmed": "yes"}, row], "C. Reviewer")
    db.rollback()
    assert db.query(NtfpMethodValue).count() == before


def test_a_review_needs_a_named_reviewer_and_an_unconfirmed_untouched_row_is_skipped(client, db):
    _seed_cards(db)
    _provisional(db)
    with pytest.raises(cards.ReviewError):
        cards.apply_review(db, [{"species_key": "zz test herb", "confirmed": "yes"}], "  ")
    out = cards.apply_review(db, [{"species_key": "zz test herb", "confirmed": "no"}], "D. Reviewer")
    assert out["cards_confirmed"] == 0 and len(out["skipped"]) == 1


def _super_admin(client, db):
    from app.models.user import User, UserRole

    headers, uid = _register(client)
    db.query(User).filter(User.id == uid).update({"role": UserRole.SUPER_ADMIN})
    db.commit()
    return headers, uid


def test_only_a_super_admin_sees_or_submits_the_card_review(client, db):
    _seed_cards(db)
    _provisional(db)
    headers, _ = _register(client)
    assert client.get("/api/calculations/ntfp-cards/review", headers=headers).status_code == 403
    r = client.post("/api/calculations/ntfp-cards/review", headers=headers, json={"rows": [{"species_key": "zz test herb", "confirmed": True}]})
    assert r.status_code == 403 and r.json()["detail"]["code"] == "super_admin_only"
    assert db.query(NtfpMethodProfile).filter_by(species_key="zz test herb").one().card_status == "provisional"


def test_the_super_admin_lists_the_waiting_cards_and_confirms_one_in_their_own_name(client, db):
    _seed_cards(db)
    _provisional(db)
    headers, _ = _super_admin(client, db)
    queue = client.get("/api/calculations/ntfp-cards/review", headers=headers).json()["cards"]
    mine = next(c for c in queue if c["species_key"] == "zz test herb")
    assert (mine["growth_class"], mine["plot_min_sqm"], mine["plot_max_sqm"], mine["n_individuals_max"]) == ("herb", 4.0, 25.0, 20)
    assert all(c["species_key"] != JAT for c in queue)                      # a documented card is not waiting
    r = client.post("/api/calculations/ntfp-cards/review", headers=headers, json={"rows": [{"species_key": "zz test herb", "confirmed": True}]})
    assert r.status_code == 200, r.text
    assert r.json()["cards_confirmed"] == 1 and r.json()["remaining"] == len(queue) - 1
    db.expire_all()
    v = db.query(NtfpMethodValue).filter_by(species_key="zz test herb", field="plot_area_sqm", chosen=True).one()
    assert v.status == "expert_confirmed" and v.reviewed_by == "Ntfp Tester"


def test_a_correction_through_the_endpoint_and_a_bad_row_that_writes_nothing(client, db):
    _seed_cards(db)
    _provisional(db)
    headers, _ = _super_admin(client, db)
    bad = client.post("/api/calculations/ntfp-cards/review", headers=headers, json={"rows": [{"species_key": "zz test herb", "confirmed": True}, {"species_key": "zz test herb", "growth_class": "bush"}]})
    assert bad.status_code == 422 and bad.json()["detail"]["code"] == "review_invalid"
    assert db.query(NtfpMethodProfile).filter_by(species_key="zz test herb").one().card_status == "provisional"
    ok = client.post("/api/calculations/ntfp-cards/review", headers=headers, json={"rows": [{"species_key": "zz test herb", "growth_class": "shrub", "plot_min_sqm": 9, "plot_max_sqm": 16}]})
    assert ok.status_code == 200, ok.text
    db.expire_all()
    prof = db.query(NtfpMethodProfile).filter_by(species_key="zz test herb").one()
    assert (prof.growth_class, float(prof.plot_min_sqm), float(prof.plot_max_sqm), prof.card_status) == ("shrub", 9.0, 16.0, "expert_confirmed")
    assert client.post("/api/calculations/ntfp-cards/review", headers=headers, json={"rows": [{"species_key": "zz test herb", "aah_pct_min": 150}]}).status_code == 422   # out of range
