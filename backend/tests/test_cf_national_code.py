"""Schedule 11: the national database code reference and its checks (owner request 2026-10-11)."""
from __future__ import annotations

import uuid

from app.services import cf_national_code as nc


def test_the_schedule_is_complete_and_matches_the_official_local_level_counts():
    rows = nc._rows()
    assert [r["sn"] for r in rows] == list(range(1, 754))  # one row per local level, no gap, no repeat
    per_province = {}
    for r in rows:
        per_province[r["province_code"]] = per_province.get(r["province_code"], 0) + 1
    assert per_province == {"KOS": 137, "MAD": 136, "BAG": 119, "GAN": 85, "LUM": 109, "KAR": 79, "SUD": 88}


def test_a_local_number_is_unique_within_its_division():
    seen = set()
    for r in nc._rows():
        key = (r["province_code"], r["division_code"], r["local_no"])
        assert key not in seen
        seen.add(key)


def test_districts_with_two_division_offices_keep_both_codes():
    codes = {(r["district"], r["division_code"]) for r in nc._rows()}
    for district, expected in {
        "Udaypur": {"UDT", "UDA"}, "Sindhuli": {"SIN", "SIM"}, "Makwanpur": {"MKM", "MAK"}, "Kapilwastu": {"KAP", "KAG"},
        "Dang": {"DAN", "DDE"}, "Surkhet": {"SUR", "SUB"}, "Kailai": {"KAI", "KLP"},
    }.items():
        assert {c for d, c in codes if d == district} == expected, district
    # every other district has exactly one
    from collections import defaultdict

    per = defaultdict(set)
    for d, c in codes:
        per[d].add(c)
    assert sorted(d for d, c in per.items() if len(c) > 1) == ["Dang", "Kailai", "Kapilwastu", "Makwanpur", "Sindhuli", "Surkhet", "Udaypur"]


def test_the_row_with_a_malformed_code_in_the_source_is_read_as_bhojpur_01():
    row = next(r for r in nc._rows() if r["sn"] == 49)
    assert (row["province_code"], row["division_code"], row["local_no"]) == ("KOS", "BJP", "01")


def test_the_picker_groups_province_division_and_local_levels():
    ref = {p["code"]: p for p in nc.reference()}
    assert set(ref) == {"KOS", "MAD", "BAG", "GAN", "LUM", "KAR", "SUD"}
    koshi = {d["code"]: d for d in ref["KOS"]["divisions"]}
    assert koshi["TAP"]["locals"][0] == {"name": "Phaktanglung", "no": "01", "district": "Taplejung"}
    assert {d["code"] for d in ref["LUM"]["divisions"]} >= {"DAN", "DDE", "KAP", "KAG"}


def test_compose_shows_what_is_still_missing():
    assert nc.compose("KOS", "TAP", "AB", "1", "7") == "KOS/TAP/AB/01/7"
    assert nc.compose("KOS", "TAP", "", "01", "") == "KOS/TAP/__/01/___"
    assert nc.compose("", "", "", "", "") == "___/___/__/__/___"


def test_check_accepts_a_code_that_follows_the_schedule_and_names_what_does_not():
    ok = nc.check("KOS/TAP/AB/01/007")
    assert ok["ok"] is True and ok["parts"]["division"] == "TAP"
    assert nc.check("KOS/TAP/AB/99/007")["problems"] == ["unknown_local_level"]
    assert nc.check("KOS/ZZZ/AB/01/007")["problems"] == ["unknown_division"]
    assert nc.check("XXX/TAP/AB/01/007")["problems"] == ["unknown_province"]
    assert nc.check("MAK/PH/42/33")["problems"] == ["format"]  # older style codes are reported, never refused
    assert nc.check("")["problems"] == ["empty"]


def _login(client, prefix):
    email = f"{prefix}-{uuid.uuid4().hex[:10]}@example.com"
    client.post("/api/auth/register", json={"email": email, "password": "TestPass123!", "full_name": "NC Tester"})
    resp = client.post("/api/auth/login", json={"email": email, "password": "TestPass123!"})
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def test_the_reference_and_check_endpoints(client, db):
    headers = _login(client, "nccode")
    ref = client.get("/api/calculations/forest-metadata/national-code-reference", headers=headers)
    assert ref.status_code == 200, ref.text
    assert len(ref.json()["provinces"]) == 7
    chk = client.get("/api/calculations/forest-metadata/national-code-check", params={"code": "KOS/TAP/AB/01/7"}, headers=headers)
    assert chk.status_code == 200 and chk.json()["ok"] is True
    assert client.get("/api/calculations/forest-metadata/national-code-reference").status_code in (401, 403)


# --- preselecting from the forest's own Province and Municipality ----------------------------------------------------------------
def test_province_is_recognised_in_every_spelling_the_app_holds():
    for text, code in {
        "कोशी": "KOS", "Koshi": "KOS", "Province 1": "KOS", "कोशी प्रदेश": "KOS", "बाग्मती": "BAG", "बागमती": "BAG",
        "Madhesh Pradesh": "MAD", "गण्डकी": "GAN", "Lumbini Province": "LUM", "कर्णाली": "KAR", "सुदूरपश्चिम": "SUD",
        "Sudurpashchim": "SUD", "प्रदेश नं. ३": "BAG",
    }.items():
        assert nc.province_code_for(text) == code, text
    assert nc.province_code_for("Atlantis") is None and nc.province_code_for("") is None and nc.province_code_for(None) is None


def test_your_two_forests_resolve_to_their_division_and_local_level():
    udayapur = nc.match_location("कोशी", "Udayapurgadhi", ["Udayapur"])
    assert (udayapur["province_code"], udayapur["division_code"], udayapur["local_no"], udayapur["confidence"]) == ("KOS", "UDT", "07", "exact")
    makwanpur = nc.match_location("बाग्मती", "Makawanpurgadhi", ["Makawanpur"])
    assert (makwanpur["division_code"], makwanpur["local_no"], makwanpur["confidence"]) == ("MAK", "04", "exact")


def test_a_different_romanisation_is_a_close_match_not_a_miss():
    r = nc.match_location("Koshi", "Udaypurgadhi")
    assert r["division_code"] == "UDT" and r["confidence"] in ("exact", "close")
    r2 = nc.match_location("Koshi", "Sirinjanga")  # the schedule has Sirinjangha
    assert r2["division_code"] == "TAP" and r2["local_no"] == "02"


def test_a_municipality_name_used_twice_is_ambiguous_until_the_district_is_known():
    r = nc.match_location("Koshi", "Miklajung")
    assert r["confidence"] == "ambiguous" and {c["division_code"] for c in r["candidates"]} == {"PAN", "MOR"}
    narrowed = nc.match_location("Koshi", "Miklajung", ["Morang"])
    assert (narrowed["division_code"], narrowed["local_no"], narrowed["confidence"]) == ("MOR", "01", "exact")


def test_a_devanagari_only_municipality_gives_the_province_and_nothing_else():
    r = nc.match_location("कोशी", "उदयपुरगढी")
    assert r["province_code"] == "KOS" and r["confidence"] == "none" and r["division_code"] is None


def test_an_unrelated_name_matches_nothing():
    assert nc.match_location("Koshi", "Atlantisgadhi")["confidence"] == "none"
    assert nc.match_location("Koshi", "")["confidence"] == "none"


def test_the_match_endpoint_uses_the_calculations_own_district_to_break_a_tie(client, db):
    from app.models.calculation import Calculation
    from app.models.user import User

    email = f"ncmatch-{uuid.uuid4().hex[:10]}@example.com"
    client.post("/api/auth/register", json={"email": email, "password": "TestPass123!", "full_name": "NC Match"})
    resp = client.post("/api/auth/login", json={"email": email, "password": "TestPass123!"})
    headers = {"Authorization": f"Bearer {resp.json()['access_token']}"}
    user = db.query(User).filter(User.email == email).first()
    calc = Calculation(user_id=user.id, forest_name="Match CF", result_data={"whole_district": "Morang"})
    db.add(calc)
    db.commit()
    url = f"/api/calculations/{calc.id}/forest-metadata/national-code-match"

    # "Miklajung" exists in Panchthar and in Morang; the analysis says Morang, so it is settled without asking the user
    r = client.get(url, params={"province": "कोशी", "palika": "Miklajung"}, headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert (body["division_code"], body["local_no"], body["confidence"]) == ("MOR", "01", "exact")

    # someone else's forest is not readable
    other = f"ncother-{uuid.uuid4().hex[:10]}@example.com"
    client.post("/api/auth/register", json={"email": other, "password": "TestPass123!", "full_name": "Other"})
    other_headers = {"Authorization": f"Bearer {client.post('/api/auth/login', json={'email': other, 'password': 'TestPass123!'}).json()['access_token']}"}
    assert client.get(url, params={"province": "कोशी", "palika": "Miklajung"}, headers=other_headers).status_code == 404
