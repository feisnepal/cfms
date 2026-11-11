"""
Digitize cleanup cron tests (Task 1.5.2 / Gap 1.2).

Covers the abandoned-draft cleanup rule:
- (draft_status='discarded' AND updated_at < now()-7d)
- OR (feature_count=0 AND created_at < now()-1d)
- Only digitize-purpose layers (source_format='digitize') — import layers untouched.
- Batch-limited; emits digitize_drafts_abandoned_total per batch.
"""
import sys
import os
from datetime import datetime, timedelta, timezone
from uuid import uuid4

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

from app.models.calculation import Calculation
from app.models.workspace_layer import (
    WorkspaceLayer,
    DRAFT_STATUS_DISCARDED,
    DRAFT_STATUS_FINALIZED,
    DRAFT_STATUS_ACTIVE,
)
from app.services.digitize_cleanup_service import (
    cleanup_abandoned_digitize_drafts,
    count_abandoned_digitize_drafts,
)


@pytest.fixture(autouse=True)
def _isolate_layers(db):
    """Global-count queries must not see rows from other tests/files."""
    db.query(WorkspaceLayer).delete()
    db.commit()
    yield


def _make_calc(db):
    from sqlalchemy import func
    from shapely.geometry import Polygon
    from app.models.user import User, UserRole
    user = User(
        id=uuid4(),
        email=f"cleanup_{uuid4().hex}@example.com",
        hashed_password="x",
        full_name="Cleanup Tester",
        role=UserRole.USER,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    calc = Calculation(
        user_id=user.id,
        forest_name="Cleanup Forest",
        block_name="B1",
        boundary_geom=func.ST_GeomFromText(
            Polygon([[83.0, 27.0], [85.0, 27.0], [85.0, 29.0], [83.0, 29.0], [83.0, 27.0]]).wkt,
            4326,
        ),
    )
    db.add(calc)
    db.commit()
    db.refresh(calc)
    return calc


def _layer(db, calc, *, draft_status, source_format="digitize", feature_count=0, created_days_ago=0, updated_days_ago=0):
    now = datetime.now(timezone.utc)
    layer = WorkspaceLayer(
        calculation_id=calc.id,
        name="L",
        purpose="sample_plot",
        source_format=source_format,
        feature_count=feature_count,
        geometry_types=["Point"],
        layer_data={"type": "FeatureCollection", "features": []},
        is_draft=True,
        draft_status=draft_status,
        created_at=now - timedelta(days=created_days_ago),
        updated_at=now - timedelta(days=updated_days_ago),
    )
    db.add(layer)
    db.commit()
    db.refresh(layer)
    return layer


class TestCleanupTargetSelection:
    def test_discarded_old_deleted(self, db):
        calc = _make_calc(db)
        target = _layer(db, calc, draft_status=DRAFT_STATUS_DISCARDED, updated_days_ago=8)
        _layer(db, calc, draft_status=DRAFT_STATUS_DISCARDED, updated_days_ago=2)  # too fresh
        _layer(db, calc, draft_status=DRAFT_STATUS_ACTIVE, updated_days_ago=8)  # not discarded

        assert count_abandoned_digitize_drafts(db) == 1
        res = cleanup_abandoned_digitize_drafts(db)
        assert res["deleted"] == 1

        still = db.query(WorkspaceLayer).filter(WorkspaceLayer.id == target.id).first()
        assert still is None  # hard-deleted

    def test_empty_old_deleted(self, db):
        calc = _make_calc(db)
        target = _layer(db, calc, draft_status=DRAFT_STATUS_ACTIVE, feature_count=0, created_days_ago=3)
        # Fresh empty draft (a few hours old) must NOT be cleaned up
        fresh = _layer(db, calc, draft_status=DRAFT_STATUS_ACTIVE, feature_count=0, created_days_ago=0)

        assert count_abandoned_digitize_drafts(db) == 1
        res = cleanup_abandoned_digitize_drafts(db)
        assert res["deleted"] == 1
        assert db.query(WorkspaceLayer).filter(WorkspaceLayer.id == target.id).first() is None
        assert db.query(WorkspaceLayer).filter(WorkspaceLayer.id == fresh.id).first() is not None

    def test_import_layers_untouched(self, db):
        calc = _make_calc(db)
        # A legacy imported layer (source_format='geojson'), old + discarded
        # status does not exist for imports, but simulate an old import row that
        # should never be touched by the digitize cron.
        _layer(db, calc, draft_status=DRAFT_STATUS_FINALIZED, source_format="geojson", feature_count=5, created_days_ago=30)
        _layer(db, calc, draft_status=DRAFT_STATUS_DISCARDED, source_format="geojson", feature_count=0, created_days_ago=30)

        assert count_abandoned_digitize_drafts(db) == 0
        res = cleanup_abandoned_digitize_drafts(db)
        assert res["deleted"] == 0

    def test_batch_limit(self, db):
        calc = _make_calc(db)
        for i in range(5):
            _layer(db, calc, draft_status=DRAFT_STATUS_DISCARDED, updated_days_ago=8)
        res = cleanup_abandoned_digitize_drafts(db, batch_limit=2)
        assert res["deleted"] == 2
        # remaining 3 still qualify
        assert count_abandoned_digitize_drafts(db) == 3

    def test_empty_run_noop(self, db):
        calc = _make_calc(db)
        _layer(db, calc, draft_status=DRAFT_STATUS_ACTIVE, feature_count=1)
        res = cleanup_abandoned_digitize_drafts(db)
        assert res["deleted"] == 0


class TestCleanupMetric:
    def test_metric_emitted_on_delete(self, db, monkeypatch):
        from app.services import digitize_metrics_service

        calls = []
        monkeypatch.setattr(digitize_metrics_service, "increment_abandoned_drafts", lambda n: calls.append(n))

        calc = _make_calc(db)
        _layer(db, calc, draft_status=DRAFT_STATUS_DISCARDED, updated_days_ago=8)
        _layer(db, calc, draft_status=DRAFT_STATUS_DISCARDED, updated_days_ago=9)

        cleanup_abandoned_digitize_drafts(db)
        assert calls == [2]

    def test_no_metric_when_nothing_deleted(self, db, monkeypatch):
        from app.services import digitize_metrics_service

        calls = []
        monkeypatch.setattr(digitize_metrics_service, "increment_abandoned_drafts", lambda n: calls.append(n))

        calc = _make_calc(db)
        _layer(db, calc, draft_status=DRAFT_STATUS_ACTIVE, feature_count=1)

        cleanup_abandoned_digitize_drafts(db)
        assert calls == []
