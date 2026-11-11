"""P1b of the yearly-activities plan (§4.11): the seed of English names / search words for the master list.

The seed script is the only writer of `name_en` / `search_terms`; it must never label a row whose Nepali
name differs, must be idempotent, and must be fully reversible. The list endpoint carries the new fields.
"""

import uuid

from sqlalchemy import text

from app.models.yearly_activities import PotentialActivity
from scripts import seed_activity_search_terms as seed_mod


def _new_row(db, name, *, active=True, pid=None):
    row = PotentialActivity(
        project_name="Test project",
        progarms="Test programme",
        activities=name,
        unit="ha",
        is_active=active,
    )
    if pid is not None:
        row.id = pid
    db.add(row)
    db.flush()
    return row


def _spec(row, en="Test nursery", terms="nursery, nurseri"):
    return {"id": row.id, "ne": row.activities, "en": en, "terms": terms}


# --------------------------------------------------------------------------------- the data file
def test_the_file_covers_every_real_activity_exactly_once():
    rows = seed_mod.load_rows()
    ids = [r["id"] for r in rows]
    assert sorted(ids) == list(
        range(1, 136)
    )  # 136 is the stray test row (D30): not labelled
    for r in rows:
        assert r["ne"].strip() and r["en"].strip(), r["id"]
        # every activity has at least a few words to be found by besides its own name
        assert len(r["terms"].replace(",", " ").split()) >= 2, r["id"]


def test_english_names_are_distinct_except_for_the_known_repeats():
    rows = seed_mod.load_rows()
    by_en = {}
    for r in rows:
        by_en.setdefault(r["en"], []).append(r["id"])
    repeated = {tuple(v) for v in by_en.values() if len(v) > 1}
    # the master list itself repeats "समूहको विधान संशोधन" (108, 111); the picker tells them apart by unit
    assert repeated <= {(108, 111)}, repeated


# ------------------------------------------------------------------------------ the seed function
def test_seed_labels_a_matching_row_and_is_idempotent(db):
    row = _new_row(db, f"नर्सरी परीक्षण {uuid.uuid4().hex[:6]}")
    spec = _spec(row)

    first = seed_mod.seed(db, [spec])
    assert first["updated"] == 1 and first["unchanged"] == 0
    db.expire_all()
    fresh = db.query(PotentialActivity).filter_by(id=row.id).one()
    assert (fresh.name_en, fresh.search_terms) == ("Test nursery", "nursery, nurseri")

    second = seed_mod.seed(db, [spec])
    assert second["updated"] == 0 and second["unchanged"] == 1


def test_seed_skips_a_row_whose_nepali_name_differs(db):
    row = _new_row(db, "यो नाम फरक छ")
    wrong = {**_spec(row), "ne": "अर्को नाम"}

    report = seed_mod.seed(db, [wrong])

    assert report["name_differs"] == [row.id] and report["updated"] == 0
    db.expire_all()
    assert db.query(PotentialActivity).filter_by(id=row.id).one().name_en is None


def test_seed_reports_a_row_that_does_not_exist(db):
    report = seed_mod.seed(db, [{"id": 987654, "ne": "x", "en": "x", "terms": "x"}])
    assert report["missing"] == [987654]


def test_rollback_blanks_only_rows_whose_name_still_matches(db):
    mine = _new_row(db, f"मेरो {uuid.uuid4().hex[:6]}")
    other = _new_row(db, f"अर्को {uuid.uuid4().hex[:6]}")
    for r in (mine, other):
        db.execute(
            text(
                "UPDATE potential_activities SET name_en='E', search_terms='t' WHERE id=:i"
            ),
            {"i": r.id},
        )
    specs = [_spec(mine), {**_spec(other), "ne": "बदलिएको नाम"}]

    assert seed_mod.rollback(db, specs) == 1
    db.expire_all()
    assert db.query(PotentialActivity).filter_by(id=mine.id).one().name_en is None
    assert db.query(PotentialActivity).filter_by(id=other.id).one().name_en == "E"


# --------------------------------------------------------------------- D30: the stray test row
def test_the_stray_row_is_only_deactivated_when_it_is_the_stray_row_and_unused(db):
    stray = db.query(PotentialActivity).filter_by(id=seed_mod.STRAY_ID).first()
    if (
        stray is None
    ):  # a fresh test database has no such row: create it as it is in cf_db
        stray = _new_row(db, seed_mod.STRAY_ACTIVITY, pid=seed_mod.STRAY_ID)
    if stray.activities != seed_mod.STRAY_ACTIVITY:
        # another master list occupies id 136 here: the script must leave it alone
        assert "left alone" in seed_mod.deactivate_stray(db)
        return

    stray.is_active = True
    db.flush()
    assert seed_mod.deactivate_stray(db) == "deactivated"
    assert seed_mod.deactivate_stray(db) == "already inactive"
    assert seed_mod.reactivate_stray(db) == "reactivated"
    db.expire_all()
    assert (
        db.query(PotentialActivity).filter_by(id=seed_mod.STRAY_ID).one().is_active
        is True
    )


# ------------------------------------------------------------------------------ the list endpoint
def test_the_list_endpoint_carries_the_english_name_search_words_and_map_kind(
    client, db
):
    email = f"pa-{uuid.uuid4().hex[:10]}@example.com"
    reg = client.post(
        "/api/auth/register",
        json={"email": email, "password": "TestPass123!", "full_name": "Picker Tester"},
    )
    assert reg.status_code == 201, reg.text
    login = client.post(
        "/api/auth/login", json={"email": email, "password": "TestPass123!"}
    )
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    row = _new_row(db, f"खोज परीक्षण {uuid.uuid4().hex[:6]}")
    row.name_en = "Search test"
    row.search_terms = "khoj, find"
    row.map_kind = "nursery"
    db.commit()

    resp = client.get("/api/yearly-activities/potential-activities", headers=headers)
    assert resp.status_code == 200, resp.text
    mine = next(a for a in resp.json() if a["id"] == row.id)
    assert (mine["name_en"], mine["search_terms"], mine["map_kind"]) == (
        "Search test",
        "khoj, find",
        "nursery",
    )
