"""
Phase 3 — DB-backed translations admin API tests.

Covers permissions (super_admin-only), CRUD (list/search/upsert), history
append, overlay reflecting overrides, and CSV import round-trip. Every user
gets a unique email so repeated pytest runs never collide.
"""
import uuid

from app.models.user import User, UserRole, UserStatus
from app.models.translation import Translation


def _uniq(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}@example.com"


def _register(client, email: str, password: str = "TestPass123!"):
    resp = client.post(
        "/api/auth/register",
        json={"email": email, "password": password, "full_name": "Tester"},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _login(client, email: str, password: str = "TestPass123!"):
    resp = client.post(
        "/api/auth/login",
        json={"email": email, "password": password},
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def _normal_user(client) -> dict:
    email = _uniq("user")
    _register(client, email)
    return _login(client, email)


def _super_user(client, db) -> dict:
    """Register a user, then promote the DB row to SUPER_ADMIN (role is read
    from the DB on every request — the JWT only carries the user id)."""
    email = _uniq("super")
    uid = _register(client, email)
    user = db.query(User).filter(User.id == uid).first()
    user.role = UserRole.SUPER_ADMIN
    db.commit()
    return _login(client, email)


def _put(client, key, headers, **payload):
    return client.put(f"/api/translations/{key}", headers=headers, json=payload)


def test_overlay_public_no_auth(client):
    resp = client.get("/api/translations/overlay")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "ne" in body and "en" in body


def test_list_requires_super_admin(client):
    headers = _normal_user(client)
    resp = client.get("/api/translations", headers=headers)
    assert resp.status_code == 403, resp.text
    assert resp.json()["detail"]["code"] == "auth.insufficient_permissions"


def test_put_requires_super_admin(client):
    headers = _normal_user(client)
    resp = _put(client, "auth.invalid_credentials", headers, ne="test")
    assert resp.status_code == 403, resp.text


def test_csv_requires_super_admin(client):
    headers = _normal_user(client)
    resp = client.get("/api/translations/csv", headers=headers)
    assert resp.status_code == 403, resp.text


def test_upsert_new_key_and_overlay(client, db):
    headers = _super_user(client, db)
    key = f"test.phase3.new_{uuid.uuid4().hex[:8]}"
    resp = _put(client, key, headers, en="Hello", ne="नमस्ते", note="added")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["key"] == key
    assert body["en"] == "Hello"
    assert body["ne"] == "नमस्ते"
    assert body["is_override"] is True
    assert body["source_file"] == "editor"

    # Overlay must now include the override as a nested path.
    overlay = client.get("/api/translations/overlay").json()
    assert "नमस्ते" in str(overlay["ne"])


def test_upsert_existing_appends_history(client, db):
    headers = _super_user(client, db)
    key = "common.save"

    # H1.14, corrected in H2.9: this test asserts the FIRST history entry
    # records a from_ne of "सेभ गर्नुहोस्" — the value seeded from the frontend
    # bundle. It originally relied on some earlier test having triggered the
    # backfill, which held under fixed collection order and not under
    # pytest-randomly.
    #
    # Calling seed_translations() was not enough either: it is idempotent *by
    # table emptiness* and returns immediately if any row exists, so a test that
    # inserted some unrelated key first left this one unseeded and from_ne None.
    # That is the intermittent failure seen on 2026-08-20. Set the precondition
    # this test actually needs, rather than a global one it hopes implies it.
    from app.models.translation import Translation

    seeded_ne = "सेभ गर्नुहोस्"
    row = db.query(Translation).filter(Translation.key == key).first()
    if row is None:
        db.add(Translation(key=key, en="Save", ne=seeded_ne,
                           source_file="bundle", is_override=False, reviewed=False))
    else:
        row.ne = seeded_ne
    db.commit()

    first = _put(client, key, headers, en="Save", ne="सुरक्षित गर्नुहोस्", note="v1")
    assert first.status_code == 200

    second = _put(client, key, headers, ne="बचत गर्नुहोस्", note="v2")
    assert second.status_code == 200
    body = second.json()
    assert body["ne"] == "बचत गर्नुहोस्"
    assert len(body["history"]) == 2
    assert body["history"][0]["from_ne"] == "सेभ गर्नुहोस्"
    assert body["history"][0]["to_ne"] == "सुरक्षित गर्नुहोस्"
    assert body["history"][0]["note"] == "v1"
    assert body["history"][1]["from_ne"] == "सुरक्षित गर्नुहोस्"
    assert body["history"][1]["to_ne"] == "बचत गर्नुहोस्"
    assert body["history"][1]["note"] == "v2"


def test_upsert_validation(client, db):
    headers = _super_user(client, db)
    resp = _put(client, "common.save", headers)
    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "translations.nothing_to_update"


def test_list_search_and_filters(client, db):
    headers = _super_user(client, db)
    key = f"test.search.{uuid.uuid4().hex[:8]}"
    _put(client, key, headers, en="Searchable phrase", ne="खोज")
    _put(client, "auth.invalid_credentials", headers, ne="गलत क्रेडेन्सियल")

    resp = client.get("/api/translations", headers=headers, params={"search": "Searchable phrase"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] >= 1
    assert any(item["key"] == key for item in body["items"])

    resp = client.get("/api/translations", headers=headers, params={"override_only": "true"})
    assert resp.status_code == 200
    assert all(item["is_override"] is True for item in resp.json()["items"])

    resp = client.get("/api/translations", headers=headers, params={"lang_is_empty": "ne"})
    assert resp.status_code == 200
    for item in resp.json()["items"]:
        assert not item["ne"]


def test_stats_endpoint(client, db):
    headers = _super_user(client, db)
    resp = client.get("/api/translations/stats", headers=headers)
    assert resp.status_code == 200, resp.text
    stats = resp.json()
    assert stats["total_keys"] > 0
    assert stats["untranslated_ne"] >= 0
    assert stats["overrides"] >= 0


def test_csv_import_roundtrip(client, db):
    headers = _super_user(client, db)
    key = f"test.csv.{uuid.uuid4().hex[:8]}"
    csv_content = (
        "key,en,np,context\n"
        f"{key},From CSV,सीएसभीबाट,Test\n"
    ).encode("utf-8")
    resp = client.post(
        "/api/translations/csv",
        headers=headers,
        files={"file": ("import.csv", csv_content, "text/csv")},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["key_count"] == 1

    row = db.query(Translation).filter(Translation.key == key).first()
    assert row is not None
    assert row.ne == "सीएसभीबाट"
    assert row.is_override is True


def test_seed_idempotent(client, db):
    headers = _super_user(client, db)
    client.get("/api/translations", headers=headers)  # triggers seed
    first = db.query(Translation).count()
    client.get("/api/translations", headers=headers)  # again
    second = db.query(Translation).count()
    assert first == second > 0

# ---------------------------------------------------------------------------
# T-1 — the reconciliation, and the defect it replaces
# ---------------------------------------------------------------------------
# `seed_translations` used to return 0 the moment the table held any row. It
# ran once when the bundle held ~535 keys and never again; by 2026-08-24 the
# live table held 536 rows against 4,777 in the bundle, so the editor could
# reach 11% of the interface. These tests pin the two properties that make
# repeated reconciliation safe: human edits survive, stale defaults do not.


def test_reconcile_picks_up_keys_added_after_the_first_seed(client, db):
    """The actual bug: a non-empty table used to mean "nothing to do"."""
    from app.services.translation_service import seed_translations

    seed_translations(db)
    before = db.query(Translation).count()
    assert before > 0

    # Simulate a key that was in the table, being removed — as if the bundle had
    # grown since the table was first populated.
    victim = db.query(Translation).filter(Translation.is_override.is_(False)).first()
    missing_key = victim.key
    db.delete(victim)
    db.commit()
    assert db.query(Translation).filter(Translation.key == missing_key).first() is None

    touched = seed_translations(db)

    assert touched >= 1
    assert db.query(Translation).filter(Translation.key == missing_key).first() is not None
    assert db.query(Translation).count() == before


def test_reconcile_never_touches_an_override(client, db):
    """`is_override` marks human work. It is the one thing that must survive."""
    from app.services.translation_service import seed_translations, upsert_translation

    seed_translations(db)
    row = db.query(Translation).filter(Translation.is_override.is_(False)).first()
    key = row.key

    upsert_translation(db, key, en="EDITED BY A HUMAN", ne="मानिसले सम्पादन गरेको")
    db.commit()

    seed_translations(db)

    after = db.query(Translation).filter(Translation.key == key).first()
    assert after.en == "EDITED BY A HUMAN"
    assert after.ne == "मानिसले सम्पादन गरेको"
    assert after.is_override is True


def test_reconcile_refreshes_a_stale_default(client, db):
    """A non-override row mirrors the bundle, so a drifted mirror is repaired.

    Without this the editor would display a string the application no longer
    uses, and the person editing it would have no way to tell.
    """
    from app.services.translation_service import seed_translations

    seed_translations(db)
    row = db.query(Translation).filter(Translation.is_override.is_(False)).first()
    key, real_en = row.key, row.en
    row.en = "STALE VALUE FROM AN OLDER BUNDLE"
    db.commit()

    seed_translations(db)

    assert db.query(Translation).filter(Translation.key == key).first().en == real_en


def test_reconcile_is_a_no_op_when_nothing_changed(client, db):
    """It runs on every admin request, so a settled table must cost nothing."""
    from app.services.translation_service import seed_translations

    seed_translations(db)
    assert seed_translations(db) == 0


def test_reconcile_does_not_change_what_users_see(client, db):
    """Only `is_override` rows reach the frontend, so inserts are invisible."""
    from app.services.translation_service import seed_translations, get_overlay_rows

    seed_translations(db)
    before = get_overlay_rows(db)

    victim = db.query(Translation).filter(Translation.is_override.is_(False)).first()
    db.delete(victim)
    db.commit()
    seed_translations(db)

    assert get_overlay_rows(db) == before
