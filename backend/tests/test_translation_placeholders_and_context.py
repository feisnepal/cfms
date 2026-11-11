"""P1 of the yearly-activities plan (§4.6b): a reviewer cannot break a message by dropping a
{{placeholder}}, and each key can carry a note saying where the sentence appears."""

import json
import uuid

import pytest
from sqlalchemy import or_

from app.models.translation import Translation
from app.models.user import User, UserRole
from app.services import translation_service as ts


@pytest.fixture(autouse=True)
def _remove_the_rows_these_tests_create(db):
    """The client fixture commits, so rows made here would outlive the test — and another test that picks
    "the first non-override row" as its victim would then delete one the bundle cannot restore.
    """
    yield
    db.rollback()
    db.query(Translation).filter(
        or_(Translation.key.like("testp.%"), Translation.key.like("testc.%"))
    ).delete(synchronize_session=False)
    db.commit()


def _super_headers(client, db):
    email = f"tp-{uuid.uuid4().hex[:10]}@example.com"
    resp = client.post(
        "/api/auth/register",
        json={
            "email": email,
            "password": "TestPass123!",
            "full_name": "Translation Tester",
        },
    )
    assert resp.status_code == 201, resp.text
    user = db.query(User).filter(User.id == resp.json()["id"]).first()
    user.role = UserRole.SUPER_ADMIN
    db.commit()
    login = client.post(
        "/api/auth/login", json={"email": email, "password": "TestPass123!"}
    )
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def _put(client, key, headers, **payload):
    return client.put(f"/api/translations/{key}", headers=headers, json=payload)


# ------------------------------------------------------------------ the placeholder guard
def test_placeholders_are_read_in_order_without_repeats():
    assert ts.placeholders_of("“{{activity}}” Year {{ years }} {{activity}}") == [
        "activity",
        "years",
    ]
    assert ts.placeholders_of("no placeholders") == []
    assert ts.placeholders_of(None) == []


def test_an_edit_that_drops_a_placeholder_is_refused_and_one_that_keeps_it_is_saved(
    client, db
):
    headers = _super_headers(client, db)
    key = f"testp.{uuid.uuid4().hex[:8]}.greeting"
    db.add(
        Translation(
            key=key,
            en="Hello {{name}}, you have {{count}} messages",
            ne=None,
            source_file="bundle",
        )
    )
    db.commit()

    dropped = _put(
        client, key, headers, ne="नमस्ते, तपाईंसँग {{count}} सन्देश छन्"
    )  # {{name}} is gone
    assert dropped.status_code == 422, dropped.text
    detail = dropped.json()["detail"]
    assert detail["code"] == "translations.placeholder_missing"
    assert "{{name}}" in detail["placeholders"] and "{{name}}" in detail["message"]
    db.expire_all()
    assert (
        db.query(Translation).filter_by(key=key).one().ne is None
    )  # nothing was saved

    kept = _put(client, key, headers, ne="नमस्ते {{name}}, तपाईंसँग {{count}} सन्देश छन्")
    assert kept.status_code == 200, kept.text


def test_the_english_edit_is_checked_too_and_a_key_without_placeholders_is_free(
    client, db
):
    headers = _super_headers(client, db)
    key = f"testp.{uuid.uuid4().hex[:8]}.line"
    db.add(Translation(key=key, en="Saved {{what}}", ne=None, source_file="bundle"))
    plain = f"testp.{uuid.uuid4().hex[:8]}.plain"
    db.add(Translation(key=plain, en="Just words", ne=None, source_file="bundle"))
    db.commit()

    assert _put(client, key, headers, en="Saved.").status_code == 422
    assert _put(client, plain, headers, ne="केवल शब्द").status_code == 200


def test_the_shipped_english_is_the_source_of_truth_for_a_bundle_key(client, db):
    """A real bundle key: the catalogue's own next-step text needs {{activity}} in every language."""
    headers = _super_headers(client, db)
    key = "yearlyPlan.next.NO_LOCATION.text"
    ts.seed_translations(db)
    bad = _put(client, key, headers, ne="स्थान नक्सामा तोकिएको छैन।")
    assert (
        bad.status_code == 422
        and "{{activity}}" in bad.json()["detail"]["placeholders"]
    )
    good = _put(client, key, headers, ne="“{{activity}}” को स्थान नक्सामा तोकिएको छैन।")
    assert good.status_code == 200, good.text


# ------------------------------------------------------------------------- context notes
def test_the_shipped_catalogue_has_a_note_for_every_key_and_each_note_names_its_placeholders():
    notes = ts.load_context_notes()
    en_leaves, _ne = ts.load_bundle_pairs()
    catalogue = {k for k in en_leaves if k.startswith("yearlyPlan.")}
    assert catalogue and catalogue <= set(notes), sorted(catalogue - set(notes))
    for key in catalogue:
        for name in ts.placeholders_of(en_leaves[key]):
            # the note tells the reviewer what {{name}} stands for
            assert "{{" + name + "}}" in notes[key], (key, name)


def test_seeding_fills_an_empty_context_and_never_overwrites_one(
    client, db, tmp_path, monkeypatch
):
    key_new = f"testc.{uuid.uuid4().hex[:8]}.a"
    key_kept = f"testc.{uuid.uuid4().hex[:8]}.b"
    (tmp_path / "x_context.json").write_text(
        json.dumps({key_new: "Appears on the plan card", key_kept: "Should not win"}),
        encoding="utf-8",
    )
    monkeypatch.setattr(ts, "CONTEXT_NOTES_DIR", tmp_path)
    db.add(Translation(key=key_new, en="A", ne=None, source_file="bundle"))
    db.add(
        Translation(
            key=key_kept,
            en="B",
            ne=None,
            source_file="bundle",
            context="Written by a person",
        )
    )
    db.commit()

    ts.seed_translations(db)

    db.expire_all()
    assert (
        db.query(Translation).filter_by(key=key_new).one().context
        == "Appears on the plan card"
    )
    assert (
        db.query(Translation).filter_by(key=key_kept).one().context
        == "Written by a person"
    )


def test_the_list_endpoint_returns_the_context_for_the_reviewer(client, db):
    headers = _super_headers(client, db)
    resp = client.get(
        "/api/translations",
        headers=headers,
        params={"category": "yearlyPlan", "per_page": 500},
    )
    assert resp.status_code == 200, resp.text
    items = (
        resp.json()["items"]
        if isinstance(resp.json(), dict) and "items" in resp.json()
        else resp.json()
    )
    by_key = {i["key"]: i for i in items}
    assert by_key["yearlyPlan.next.NO_LOCATION.text"]["context"].startswith(
        "Next-step card"
    )
