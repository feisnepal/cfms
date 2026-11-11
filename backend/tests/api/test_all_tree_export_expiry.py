"""Total Tree Exports are deleted one hour after they finish.

The clock starts at ``completed_at`` (a long run must not eat the user's download
time), failed exports count from ``created_at``, and a running export is never
touched. Expiry removes the GPKG, the derived sample-plot GPKG and the record.
"""
import os
import uuid
from datetime import datetime, timedelta, timezone

from app.models.all_tree_export import AllTreeExport
from app.models.calculation import Calculation
from app.models.user import User, UserRole
from app.services.export_cleanup import (
    ALL_TREE_EXPORT_TTL,
    all_tree_export_expiry,
    purge_expired_all_tree_exports,
)

EXPORTS_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "exports")


def _calc(db):
    user = User(
        email=f"expiry{uuid.uuid4().hex[:8]}@test.com",
        full_name="Expiry Tester",
        role=UserRole.USER,
        hashed_password="not-a-real-hash",
    )
    db.add(user)
    db.flush()
    calc = Calculation(
        id=str(uuid.uuid4()),
        user_id=user.id,
        uploaded_filename="expiry-test.csv",
        is_draft=False,
        structure_locked=False,
    )
    db.add(calc)
    db.flush()
    return calc


def _export(db, calc, tmp_path, *, status="completed", created_ago, completed_ago=None):
    now = datetime.now(timezone.utc)
    gpkg = tmp_path / f"{uuid.uuid4().hex}.gpkg"
    gpkg.write_bytes(b"x")
    exp = AllTreeExport(
        calculation_id=calc.id,
        user_id=calc.user_id,
        model_type="full_extent",
        model_version="v1.0",
        algorithm_config={},
        status=status,
        gpkg_path=str(gpkg),
        created_at=now - created_ago,
        completed_at=(now - completed_ago) if completed_ago is not None else None,
    )
    db.add(exp)
    db.flush()
    return exp, gpkg


def test_expiry_is_one_hour_after_completion_not_creation(db, tmp_path):
    calc = _calc(db)
    # queued 3h ago but only finished 10 min ago -> still has ~50 min
    exp, _ = _export(
        db, calc, tmp_path,
        created_ago=timedelta(hours=3), completed_ago=timedelta(minutes=10),
    )
    assert all_tree_export_expiry(exp) == exp.completed_at + ALL_TREE_EXPORT_TTL
    assert exp.expires_at == exp.completed_at + timedelta(hours=1)
    assert purge_expired_all_tree_exports(db) == 0
    assert db.get(AllTreeExport, exp.id) is not None


def test_export_past_one_hour_is_deleted_with_its_files(db, tmp_path):
    calc = _calc(db)
    exp, gpkg = _export(
        db, calc, tmp_path,
        created_ago=timedelta(hours=2), completed_ago=timedelta(minutes=61),
    )
    derived = os.path.join(EXPORTS_DIR, f"sample_plots_{exp.id}.gpkg")
    os.makedirs(EXPORTS_DIR, exist_ok=True)
    with open(derived, "wb") as fh:
        fh.write(b"x")
    try:
        assert purge_expired_all_tree_exports(db) >= 1
        assert db.get(AllTreeExport, exp.id) is None
        assert not gpkg.exists()
        assert not os.path.exists(derived)
    finally:
        if os.path.exists(derived):
            os.remove(derived)


def test_running_export_is_never_expired(db, tmp_path):
    calc = _calc(db)
    exp, gpkg = _export(
        db, calc, tmp_path, status="processing", created_ago=timedelta(hours=5),
    )
    assert exp.expires_at is None
    purge_expired_all_tree_exports(db)
    assert db.get(AllTreeExport, exp.id) is not None
    assert gpkg.exists()


def test_failed_export_counts_from_creation(db, tmp_path):
    calc = _calc(db)
    exp, _ = _export(db, calc, tmp_path, status="failed", created_ago=timedelta(minutes=90))
    purge_expired_all_tree_exports(db)
    assert db.get(AllTreeExport, exp.id) is None
