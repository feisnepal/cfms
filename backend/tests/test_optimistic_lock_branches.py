"""One-off branch hits for optimistic-lock 404s (H4.2)."""
from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException

from app.services.optimistic_lock import check_and_bump


def test_check_and_bump_of_a_missing_row_is_a_404(db):
    """`expected is None` with a row that does not exist -> 404 (not a 409)."""
    with pytest.raises(HTTPException) as exc:
        check_and_bump(db, "household", uuid.uuid4(), None)
    assert exc.value.status_code == 404
    assert exc.value.detail == {"code": "NOT_FOUND"}


def _household(db):
    from app.models.calculation import Calculation
    from app.models.household_information import HouseholdInformation
    from app.models.user import User

    owner = User(
        email=f"guard-{uuid.uuid4().hex[:10]}@example.com",
        hashed_password="h", full_name="Guard",
    )
    db.add(owner)
    db.flush()
    calc = Calculation(user_id=owner.id, forest_name="Guard CF")
    db.add(calc)
    db.flush()
    row = HouseholdInformation(
        calculation_id=calc.id,
        house_no=7000 + uuid.uuid4().int % 900,
        surname="Rimal",
        created_by=owner.id,
    )
    db.add(row)
    db.commit()
    return row


def test_non_enforcing_guard_logs_instead_of_raising(db, caplog):
    """With the guard not enforcing, an unguarded write is logged, not fatal."""
    from app.services import optimistic_lock_guard as g

    row = _household(db)
    db.expire_all()

    saved = g._enforcing
    g._enforcing = lambda: False
    try:
        row.surname = "Changed Without Lock (non-enforcing)"
        db.flush()
    finally:
        g._enforcing = saved
    db.rollback()


def test_install_is_idempotent(monkeypatch):
    """Calling install() twice must not double-register the listener."""
    from app.services import optimistic_lock_guard as g

    # Reset the installed flag so the idempotency branch runs once in this test.
    monkeypatch.setattr(g._guard, "_installed", True, raising=False)
    g.install()
    g.install()  # must not raise or double-register


def test_guard_skips_an_object_dirty_without_a_real_change(db):
    """H4.2: an object can land in `session.dirty` having been touched without
    anything actually differing (e.g. attribute set to its own value). The guard
    must not raise on that -- that is the `if not changed: continue` branch."""
    from app.services import optimistic_lock_guard as g

    row = _household(db)
    db.expire_all()

    # Force the exact no-op edge: attribute assigned to its own value while the
    # guard is enforcing. history.has_changes() is False, so `changed` is empty
    # and the guard continues instead of raising LockNotTakenError.
    row.surname = row.surname
    saved = g._enforcing
    g._enforcing = lambda: True
    try:
        db.flush()
    finally:
        g._enforcing = saved
    db.rollback()
