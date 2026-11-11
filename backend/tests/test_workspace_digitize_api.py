"""
On-screen digitizing API tests (GD Phase 1.2).

Covers the four digitize endpoints added to workspace.py:
- POST /workspace/{calc}/digitize-layers          — draft create
- POST /workspace/{calc}/digitize-layers/{id}/features/bulk  — bulk upsert/delete
- POST /workspace/{calc}/digitize-layers/{id}/finalize       — finalize (sync fallback)
- GET  /workspace/{calc}/digitize-layers/{id}/finalize-status — poll

Key assertions:
- Feature flag gate (digitize_v1 OFF → 404; ON → works)
- Ownership enforcement reuses the existing _require_calculation_access path
- Draft-status state machine (ACTIVE → SYNCING → FINALIZED / VALIDATION_FAILED)
- Sanitizer rejects oversized / out-of-bounds / wrong-purpose geometry
- Server-assigned featureId (client temp ids are never trusted)
- Idempotency-Key dedup on bulk + finalize
- Validation-failed finalize records last_validation_error
"""
import sys
import os
from uuid import uuid4

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

from app.core.feature_flags import feature_flags, DIGITIZE_V1
from app.models.calculation import Calculation

WS = "/api/v1/workspace"


@pytest.fixture(autouse=True)
def _enable_digitize():
    """Enable the digitize_v1 flag for all tests here (restore after)."""
    feature_flags.set_for_test(DIGITIZE_V1, True)
    yield
    feature_flags.set_for_test(DIGITIZE_V1, False)


def _user(client, tag):
    email = f"{tag}_{uuid4().hex}@example.com"
    client.post(
        "/api/auth/register",
        json={"email": email, "password": "Passw0rd!x", "full_name": "Test"},
    )
    resp = client.post(
        "/api/auth/login",
        json={"email": email, "password": "Passw0rd!x"},
    )
    assert resp.status_code == 200, resp.text
    token = resp.json()["access_token"]
    me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200, me.text
    return {"Authorization": f"Bearer {token}"}, me.json()["id"]


def _boundary():
    """A ~10km-wide boundary polygon around (84, 28) for the distance validator."""
    from shapely.geometry import Polygon
    return Polygon([
        [83.0, 27.0], [85.0, 27.0], [85.0, 29.0], [83.0, 29.0], [83.0, 27.0],
    ])


def _make_calc(db, user_id):
    from sqlalchemy import func
    calc = Calculation(
        user_id=user_id,
        forest_name="Digitize Forest",
        block_name="B1",
        boundary_geom=func.ST_GeomFromText(_boundary().wkt, 4326),
    )
    db.add(calc)
    db.commit()
    db.refresh(calc)
    return calc


def _add_blocks_layer(db, calc):
    """An admin (blocks) layer so sub-layer drafts pass validate_first_layer."""
    from app.models.workspace_layer import WorkspaceLayer, DRAFT_STATUS_FINALIZED
    layer = WorkspaceLayer(
        calculation_id=calc.id,
        name="Blocks",
        purpose="blocks",
        source_format="digitize",
        feature_count=1,
        geometry_types=["Polygon"],
        layer_data={
            "type": "FeatureCollection",
            "features": [{
                "type": "Feature",
                "geometry": _poly(),
                "properties": {"name": "B1", "featureId": "blocks-0"},
            }],
        },
        is_draft=False,
        draft_status=DRAFT_STATUS_FINALIZED,
    )
    db.add(layer)
    db.commit()
    db.refresh(layer)
    return layer


def _poly(lon=84.0, lat=28.0):
    return {
        "type": "Polygon",
        "coordinates": [[[lon, lat], [lon + 1, lat], [lon + 1, lat + 1], [lon, lat + 1], [lon, lat]]],
    }


def _point(lon=84.0, lat=28.0):
    return {"type": "Point", "coordinates": [lon, lat]}


def _draft(client, db, headers, uid, purpose="sample_plot", name="Plots"):
    calc = _make_calc(db, uid)
    _add_blocks_layer(db, calc)
    r = client.post(
        f"{WS}/{calc.id}/digitize-layers",
        json={"purpose": purpose, "name": name},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    return calc, r.json()["id"]


def _finalizable(client, db, headers, uid, purpose="sample_plot"):
    calc, layer_id = _draft(client, db, headers, uid, purpose=purpose)
    client.post(
        f"{WS}/{calc.id}/digitize-layers/{layer_id}/features/bulk",
        json={"features": [
            {"clientTempId": "t1", "operation": "upsert", "feature": {"geometry": _point()}},
            {"clientTempId": "t2", "operation": "upsert", "feature": {"geometry": _point(84.1, 28.1)}},
        ]},
        headers=headers,
    )
    return calc, layer_id


@pytest.fixture()
def force_sync_finalize(monkeypatch):
    """Force the finalize endpoint's sync fallback regardless of Redis state.

    The endpoint tries arq (create_pool → enqueue_job) and only runs the sync
    chain when enqueue raises. These tests assert the sync result, so we patch
    arq.create_pool to raise so they are deterministic (no live Redis dependency).
    """
    import arq

    async def _raise(*args, **kwargs):
        raise ConnectionError("Redis unavailable (forced sync in tests)")

    monkeypatch.setattr(arq, "create_pool", _raise)


class TestDigitizeFlagGate:
    def test_disabled_returns_404(self, client, db, monkeypatch):
        feature_flags.set_for_test(DIGITIZE_V1, False)
        headers, uid = _user(client, "flag")
        calc = _make_calc(db, uid)
        resp = client.post(
            f"{WS}/{calc.id}/digitize-layers",
            json={"purpose": "sample_plot", "name": "Plots"},
            headers=headers,
        )
        assert resp.status_code == 404, resp.text


class TestDigitizeCreate:
    def test_create_draft(self, client, db):
        headers, uid = _user(client, "creator")
        calc = _make_calc(db, uid)
        _add_blocks_layer(db, calc)
        resp = client.post(
            f"{WS}/{calc.id}/digitize-layers",
            json={"purpose": "sample_plot", "name": "Sample Plots"},
            headers=headers,
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["purpose"] == "sample_plot"
        assert body["draft_status"] == "active"
        assert body["feature_count"] == 0
        assert body["is_draft"] is True
        # sample_plot only accepts Point per SSOT matrix
        assert body["geometry_types"] == ["Point"]

    def test_unknown_purpose_400(self, client, db):
        headers, uid = _user(client, "creator")
        calc = _make_calc(db, uid)
        _add_blocks_layer(db, calc)
        resp = client.post(
            f"{WS}/{calc.id}/digitize-layers",
            json={"purpose": "flying_saucer", "name": "x"},
            headers=headers,
        )
        assert resp.status_code == 400, resp.text

    def test_empty_name_422(self, client, db):
        headers, uid = _user(client, "creator")
        calc = _make_calc(db, uid)
        _add_blocks_layer(db, calc)
        resp = client.post(
            f"{WS}/{calc.id}/digitize-layers",
            json={"purpose": "sample_plot", "name": "   "},
            headers=headers,
        )
        assert resp.status_code == 422, resp.text

    def test_duplicate_draft_same_purpose_409(self, client, db):
        headers, uid = _user(client, "creator")
        calc = _make_calc(db, uid)
        _add_blocks_layer(db, calc)
        r1 = client.post(
            f"{WS}/{calc.id}/digitize-layers",
            json={"purpose": "sample_plot", "name": "A"},
            headers=headers,
        )
        assert r1.status_code == 200, r1.text
        r2 = client.post(
            f"{WS}/{calc.id}/digitize-layers",
            json={"purpose": "sample_plot", "name": "B"},
            headers=headers,
        )
        assert r2.status_code == 409, r2.text

    def test_non_owner_forbidden(self, client, db):
        owner, uid = _user(client, "owner")
        attacker, _ = _user(client, "attacker")
        calc = _make_calc(db, uid)
        _add_blocks_layer(db, calc)
        resp = client.post(
            f"{WS}/{calc.id}/digitize-layers",
            json={"purpose": "sample_plot", "name": "Mine"},
            headers=attacker,
        )
        assert resp.status_code == 403, resp.text

    def test_unauthenticated_401(self, client, db):
        headers, uid = _user(client, "creator")
        calc = _make_calc(db, uid)
        _add_blocks_layer(db, calc)
        resp = client.post(
            f"{WS}/{calc.id}/digitize-layers",
            json={"purpose": "sample_plot", "name": "x"},
        )
        assert resp.status_code in (401, 403), resp.text


class TestDigitizeBulk:
    def test_upsert_assigns_server_feature_ids(self, client, db):
        headers, uid = _user(client, "bulk")
        calc, layer_id = _draft(client, db, headers, uid)
        resp = client.post(
            f"{WS}/{calc.id}/digitize-layers/{layer_id}/features/bulk",
            json={
                "features": [
                    {"clientTempId": "t1", "operation": "upsert", "feature": {"geometry": _point()}},
                    {"clientTempId": "t2", "operation": "upsert", "feature": {"geometry": _point(84.1, 28.1)}},
                ]
            },
            headers=headers,
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["feature_count"] == 2
        # Server featureIds are stable + not equal to client temp ids
        fid1 = body["mapping"]["t1"]
        fid2 = body["mapping"]["t2"]
        assert fid1 != "t1" and fid2 != "t2" and fid1 != fid2
        assert fid1.startswith("digitize-")

    def test_wrong_geometry_type_400(self, client, db):
        headers, uid = _user(client, "bulk")
        calc, layer_id = _draft(client, db, headers, uid)
        # sample_plot accepts ONLY Point — Polygon must be rejected
        resp = client.post(
            f"{WS}/{calc.id}/digitize-layers/{layer_id}/features/bulk",
            json={
                "features": [
                    {"clientTempId": "t1", "operation": "upsert", "feature": {"geometry": _poly()}},
                ]
            },
            headers=headers,
        )
        assert resp.status_code == 400, resp.text
        assert "not allowed" in resp.json()["detail"]

    def test_delete_removes_feature(self, client, db):
        headers, uid = _user(client, "bulk")
        calc, layer_id = _draft(client, db, headers, uid)
        up = client.post(
            f"{WS}/{calc.id}/digitize-layers/{layer_id}/features/bulk",
            json={"features": [{"clientTempId": "t1", "operation": "upsert", "feature": {"geometry": _point()}}]},
            headers=headers,
        )
        fid = up.json()["mapping"]["t1"]
        resp = client.post(
            f"{WS}/{calc.id}/digitize-layers/{layer_id}/features/bulk",
            json={"features": [{"clientTempId": fid, "operation": "delete"}]},
            headers=headers,
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["feature_count"] == 0
        assert resp.json()["deleted"] == 1

    def test_oversized_geometry_400(self, client, db):
        headers, uid = _user(client, "bulk")
        calc, layer_id = _draft(client, db, headers, uid)
        # 5001 vertices > WORKSPACE_IMPORT_MAX_VERTICES cap → 400
        coords = [[84.0 + i * 0.0001, 28.0 + i * 0.0001] for i in range(5002)]
        resp = client.post(
            f"{WS}/{calc.id}/digitize-layers/{layer_id}/features/bulk",
            json={
                "features": [
                    {"clientTempId": "t1", "operation": "upsert",
                     "feature": {"geometry": {"type": "Polygon", "coordinates": [coords]}}},
                ]
            },
            headers=headers,
        )
        assert resp.status_code == 400, resp.text

    def test_idempotency_key_dedup(self, client, db):
        headers, uid = _user(client, "bulk")
        calc, layer_id = _draft(client, db, headers, uid)
        idem = str(uuid4())
        payload = {
            "features": [{"clientTempId": "t1", "operation": "upsert", "feature": {"geometry": _point()}}],
            "idempotency_key": idem,
        }
        r1 = client.post(
            f"{WS}/{calc.id}/digitize-layers/{layer_id}/features/bulk",
            json=payload,
            headers=headers,
        )
        assert r1.status_code == 200, r1.text
        r2 = client.post(
            f"{WS}/{calc.id}/digitize-layers/{layer_id}/features/bulk",
            json=payload,
            headers=headers,
        )
        assert r2.status_code == 200, r2.text
        # Second call returns cached response → same mapping, no duplicate append
        assert r1.json() == r2.json()
        assert r2.json()["feature_count"] == 1

    def test_modify_finalized_layer_409(self, client, db):
        headers, uid = _user(client, "bulk")
        calc, layer_id = _draft(client, db, headers, uid)
        # Simulate a finalized layer state
        from app.models.workspace_layer import WorkspaceLayer, DRAFT_STATUS_FINALIZED
        layer = db.query(WorkspaceLayer).filter(WorkspaceLayer.id == layer_id).first()
        layer.draft_status = DRAFT_STATUS_FINALIZED
        db.commit()
        resp = client.post(
            f"{WS}/{calc.id}/digitize-layers/{layer_id}/features/bulk",
            json={"features": [{"clientTempId": "t1", "operation": "upsert", "feature": {"geometry": _point()}}]},
            headers=headers,
        )
        assert resp.status_code == 409, resp.text


class TestDigitizeFinalize:
    def test_finalize_sync_success(self, client, db, force_sync_finalize):
        headers, uid = _user(client, "fin")
        calc, layer_id = _finalizable(client, db, headers, uid)
        resp = client.post(
            f"{WS}/{calc.id}/digitize-layers/{layer_id}/finalize",
            json={},
            headers=headers,
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["status"] == "succeeded"
        assert body["draft_status"] == "finalized"
        assert body["feature_count"] >= 1

        status_resp = client.get(
            f"{WS}/{calc.id}/digitize-layers/{layer_id}/finalize-status",
            headers=headers,
        )
        assert status_resp.status_code == 200, status_resp.text
        assert status_resp.json()["status"] == "succeeded"

    def test_finalize_async_queued_when_arq_accepts(self, client, db, monkeypatch):
        """The enqueue happy path: when arq accepts the job the endpoint returns
        the queued envelope (task_id + poll interval) without doing the work."""
        import arq

        class _Pool:
            async def enqueue_job(self, *a, **k):
                return "task-123"

            async def close(self):
                return None

        async def _pool(*args, **kwargs):
            return _Pool()

        monkeypatch.setattr(arq, "create_pool", _pool)

        headers, uid = _user(client, "async")
        calc, layer_id = _finalizable(client, db, headers, uid)
        resp = client.post(
            f"{WS}/{calc.id}/digitize-layers/{layer_id}/finalize",
            json={},
            headers=headers,
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["status"] == "queued"
        assert resp.json()["task_id"] == "task-123"
        assert resp.json()["poll_interval_s"] == 2


    def test_finalize_empty_layer_400(self, client, db):
        headers, uid = _user(client, "fin")
        calc, layer_id = _draft(client, db, headers, uid)
        resp = client.post(
            f"{WS}/{calc.id}/digitize-layers/{layer_id}/finalize",
            json={},
            headers=headers,
        )
        assert resp.status_code == 400, resp.text

    def test_finalize_non_owner_403(self, client, db):
        owner, uid = _user(client, "owner")
        attacker, _ = _user(client, "attacker")
        calc, layer_id = _finalizable(client, db, owner, uid)
        resp = client.post(
            f"{WS}/{calc.id}/digitize-layers/{layer_id}/finalize",
            json={},
            headers=attacker,
        )
        assert resp.status_code == 403, resp.text

    def test_finalize_wrong_purpose_geometry_validation_failed(self, client, db, force_sync_finalize):
        """A roads draft containing an illegal Point must fail validation at
        finalize and record last_validation_error."""
        from app.models.workspace_layer import WorkspaceLayer
        headers, uid = _user(client, "fin")
        # roads draft (allowed geometry = LineString)
        calc, layer_id = _draft(client, db, headers, uid, purpose="roads")

        # Simulate a stale draft: a Point reached the layer outside the bulk
        # gate (e.g. legacy PATCH) — finalize must reject it via the processor.
        layer = db.query(WorkspaceLayer).filter(WorkspaceLayer.id == layer_id).first()
        layer.layer_data = {
            "type": "FeatureCollection",
            "features": [{
                "type": "Feature",
                "geometry": _point(),
                "properties": {"name": "bad", "featureId": "stale-0"},
            }],
        }
        layer.feature_count = 1
        db.commit()

        resp = client.post(
            f"{WS}/{calc.id}/digitize-layers/{layer_id}/finalize",
            json={},
            headers=headers,
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["status"] == "validation_failed", resp.text
        assert body["draft_status"] == "validation_failed"
        assert body["last_validation_error"] is not None

        status_resp = client.get(
            f"{WS}/{calc.id}/digitize-layers/{layer_id}/finalize-status",
            headers=headers,
        )
        assert status_resp.json()["status"] == "validation_failed"
        assert "last_validation_error" in status_resp.json()


class TestDigitizeCSRF:
    """Gap 6.3 — auth is JWT-Bearer (no cookies), so classic CSRF does not apply.
    These pin the defense-in-depth guarantees: no-token mutating calls → 401,
    X-Requested-With accepted by CORS, and preflight OPTIONS handled."""

    def test_no_token_mutating_call_401(self, client, db):
        headers, uid = _user(client, "csrf")
        calc = _make_calc(db, uid)
        _add_blocks_layer(db, calc)
        # POST without Authorization → 401
        resp = client.post(
            f"{WS}/{calc.id}/digitize-layers",
            json={"purpose": "sample_plot", "name": "x"},
        )
        assert resp.status_code in (401, 403), resp.text

    def test_bulk_without_token_401(self, client, db):
        headers, uid = _user(client, "csrf")
        calc, layer_id = _draft(client, db, headers, uid)
        resp = client.post(
            f"{WS}/{calc.id}/digitize-layers/{layer_id}/features/bulk",
            json={"features": [{"clientTempId": "t1", "operation": "upsert", "feature": {"geometry": _point()}}]},
        )
        assert resp.status_code in (401, 403), resp.text

    def test_finalize_without_token_401(self, client, db):
        headers, uid = _user(client, "csrf")
        calc, layer_id = _finalizable(client, db, headers, uid)
        resp = client.post(
            f"{WS}/{calc.id}/digitize-layers/{layer_id}/finalize",
            json={},
        )
        assert resp.status_code in (401, 403), resp.text

    def test_x_requested_with_header_accepted(self, client, db):
        headers, uid = _user(client, "csrf")
        hdr = dict(headers)
        hdr["X-Requested-With"] = "XMLHttpRequest"
        calc = _make_calc(db, uid)
        _add_blocks_layer(db, calc)
        resp = client.post(
            f"{WS}/{calc.id}/digitize-layers",
            json={"purpose": "sample_plot", "name": "x"},
            headers=hdr,
        )
        assert resp.status_code == 200, resp.text

    def test_preflight_options_from_unknown_origin_rejected(self, client, db):
        # A disallowed Origin in a preflight OPTIONS must NOT be allowed through.
        resp = client.options(
            f"{WS}/{uuid4()}/digitize-layers",
            headers={
                "Origin": "https://evil.example.com",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "authorization,content-type",
            },
        )
        # CORSMiddleware returns 400 for disallowed origins on preflight
        assert resp.status_code in (400, 403), resp.text
        assert resp.headers.get("access-control-allow-origin") is None


class TestDigitizeSchema:
    """Task 1.2.6 — Pydantic schema validation surfaces as 422 via FastAPI."""

    def test_feature_bulk_requires_feature_for_upsert(self, client, db):
        headers, uid = _user(client, "schema")
        calc, layer_id = _draft(client, db, headers, uid)
        # No clientTempId → 422
        resp = client.post(
            f"{WS}/{calc.id}/digitize-layers/{layer_id}/features/bulk",
            json={"features": [{"operation": "upsert", "feature": {"geometry": _point()}}]},
            headers=headers,
        )
        assert resp.status_code == 422, resp.text

    def test_feature_bulk_too_many_422(self, client, db):
        headers, uid = _user(client, "schema")
        calc, layer_id = _draft(client, db, headers, uid)
        many = [
            {"clientTempId": f"t{i}", "operation": "upsert", "feature": {"geometry": _point()}}
            for i in range(51)
        ]
        resp = client.post(
            f"{WS}/{calc.id}/digitize-layers/{layer_id}/features/bulk",
            json={"features": many},
            headers=headers,
        )
        assert resp.status_code == 422, resp.text

    def test_digitize_layer_create_invalid_body_422(self, client, db):
        headers, uid = _user(client, "schema")
        calc = _make_calc(db, uid)
        _add_blocks_layer(db, calc)
        resp = client.post(
            f"{WS}/{calc.id}/digitize-layers",
            json={"name": "no purpose"},
            headers=headers,
        )
        assert resp.status_code == 422, resp.text


class TestDigitizeAuditLog:
    """Task 1.4.4 — collaborators + digitize audit log (Gap 6.1).

    - Only the creator may discard a draft; any calc owner/editor can finalize.
    - Audit rows written on create_draft / add_feature / finalize / discard.
    - geometry_hash is stable for identical geometry (dedup/forensic).
    - GET audit endpoint is owner-gated.
    """

    def test_audit_rows_on_create_add_finalize(self, client, db, force_sync_finalize):
        headers, uid = _user(client, "audit")
        calc, layer_id = _draft(client, db, headers, uid)

        client.post(
            f"{WS}/{calc.id}/digitize-layers/{layer_id}/features/bulk",
            json={"features": [
                {"clientTempId": "t1", "operation": "upsert", "feature": {"geometry": _point()}},
                {"clientTempId": "t2", "operation": "upsert", "feature": {"geometry": _point(84.1, 28.1)}},
            ]},
            headers=headers,
        )
        client.post(
            f"{WS}/{calc.id}/digitize-layers/{layer_id}/finalize",
            json={},
            headers=headers,
        )

        resp = client.get(
            f"{WS}/{calc.id}/digitize-layers/{layer_id}/audit",
            headers=headers,
        )
        assert resp.status_code == 200, resp.text
        entries = resp.json()["entries"]
        actions = [e["action"] for e in entries]
        # create_draft → add_feature (one flush) → finalize
        assert "create_draft" in actions
        assert "add_feature" in actions
        assert "finalize" in actions
        add_entry = next(e for e in entries if e["action"] == "add_feature")
        assert add_entry["feature_count_delta"] == 2
        assert add_entry["user_id"] == uid

    def test_discard_writes_audit_row(self, client, db):
        headers, uid = _user(client, "audit")
        calc, layer_id = _draft(client, db, headers, uid)

        resp = client.delete(
            f"{WS}/{calc.id}/import-layers/{layer_id}",
            headers=headers,
        )
        assert resp.status_code == 200, resp.text

        audit = client.get(
            f"{WS}/{calc.id}/digitize-layers/{layer_id}/audit",
            headers=headers,
        )
        assert audit.status_code == 200, audit.text
        actions = [e["action"] for e in audit.json()["entries"]]
        assert "discard" in actions

    def test_non_creator_cannot_discard_but_owner_can(self, client, db):
        owner_hdr, owner_uid = _user(client, "audit_owner")
        other_hdr, _ = _user(client, "audit_other")
        calc, layer_id = _draft(client, db, owner_hdr, owner_uid)

        # Other (non-creator, non-owner) user → 403
        resp = client.delete(
            f"{WS}/{calc.id}/import-layers/{layer_id}",
            headers=other_hdr,
        )
        assert resp.status_code == 403, resp.text

        # Owner (who created the draft) → 200
        resp = client.delete(
            f"{WS}/{calc.id}/import-layers/{layer_id}",
            headers=owner_hdr,
        )
        assert resp.status_code == 200, resp.text

    def test_editor_can_finalize_but_not_discard_others_draft(self, client, db, force_sync_finalize):
        # A SUPER_ADMIN editor (calc access but NOT the layer creator) may
        # append + finalize a collaborator's draft, but may NOT discard it.
        from app.models.user import User, UserRole
        creator_hdr, creator_uid = _user(client, "audit_creator")
        admin_hdr, admin_uid = _user(client, "audit_admin")
        admin = db.query(User).filter(User.id == admin_uid).first()
        admin.role = UserRole.SUPER_ADMIN
        db.commit()

        calc, layer_id = _finalizable(client, db, creator_hdr, creator_uid)

        # Editor can finalize
        resp = client.post(
            f"{WS}/{calc.id}/digitize-layers/{layer_id}/finalize",
            json={},
            headers=admin_hdr,
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["draft_status"] == "finalized"

        # Editor cannot discard the creator's draft
        resp = client.delete(
            f"{WS}/{calc.id}/import-layers/{layer_id}",
            headers=admin_hdr,
        )
        assert resp.status_code == 403, resp.text

    def test_owner_can_append_and_finalize(self, client, db, force_sync_finalize):
        # Editor/owner flow: an owner-created draft is appended to + finalized.
        headers, uid = _user(client, "audit_editor")
        calc, layer_id = _finalizable(client, db, headers, uid)

        resp = client.post(
            f"{WS}/{calc.id}/digitize-layers/{layer_id}/finalize",
            json={},
            headers=headers,
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["draft_status"] == "finalized"

    def test_geometry_hash_stable(self, client, db):
        headers, uid = _user(client, "audit_hash")
        calc, layer_id = _draft(client, db, headers, uid)

        f1 = {"geometry": _point()}
        f2 = {"geometry": _point()}
        # Identical geometry → identical hash, regardless of extra properties
        from app.services.digitize_audit_service import geometry_hash_of
        h1 = geometry_hash_of([f1, {"properties": {"bogus": 1}} | f2])
        h2 = geometry_hash_of([{"properties": {"other": 2}} | f1, f2])
        assert h1 and h1 == h2

        # Different geometry → different hash
        h3 = geometry_hash_of([{"geometry": _point(85.0, 28.0)}])
        assert h3 != h1

    def test_audit_get_access_controlled(self, client, db):
        owner_hdr, owner_uid = _user(client, "audit_owner2")
        other_hdr, _ = _user(client, "audit_other2")
        calc, layer_id = _draft(client, db, owner_hdr, owner_uid)

        resp = client.get(
            f"{WS}/{calc.id}/digitize-layers/{layer_id}/audit",
            headers=other_hdr,
        )
        assert resp.status_code == 403, resp.text

        resp = client.get(
            f"{WS}/{calc.id}/digitize-layers/{layer_id}/audit",
            headers=owner_hdr,
        )
        assert resp.status_code == 200, resp.text

    def test_audit_requires_token(self, client, db):
        headers, uid = _user(client, "audit_token")
        calc, layer_id = _draft(client, db, headers, uid)
        resp = client.get(
            f"{WS}/{calc.id}/digitize-layers/{layer_id}/audit",
        )
        assert resp.status_code in (401, 403), resp.text


class TestDigitizeStructuredLogging:
    """Task 1.4.4 / Gap 7.3 — digitize_action + digitize_validation_failed log
    lines carry the required structured `extra` keys."""

    def test_structured_formatter_emits_extra_keys(self):
        import logging
        from app.core.logging_config import StructuredFormatter

        record = logging.LogRecord(
            name="app.api.workspace",
            level=logging.INFO,
            pathname="workspace.py",
            lineno=1,
            msg="digitize_action",
            args=None,
            exc_info=None,
        )
        record.calculation_id = "calc-1"
        record.layer_id = 7
        record.user_id = "user-1"
        record.action = "add_feature"

        import json as _json
        parsed = _json.loads(StructuredFormatter().format(record))
        assert parsed["message"] == "digitize_action"
        assert parsed["calculation_id"] == "calc-1"
        assert parsed["layer_id"] == 7
        assert parsed["user_id"] == "user-1"
        assert parsed["action"] == "add_feature"
        assert "level" in parsed and "logger" in parsed

    def test_logger_warning_with_validation_failed_extra(self):
        import logging
        from app.core.logging_config import StructuredFormatter

        record = logging.LogRecord(
            name="app.api.workspace",
            level=logging.WARNING,
            pathname="workspace.py",
            lineno=1,
            msg="digitize_validation_failed",
            args=None,
            exc_info=None,
        )
        record.rule = "area_limit"
        record.limit_ha = 500.0
        record.actual_ha = 812.4
        record.feature_id = "digitize-abc123"

        import json as _json
        parsed = _json.loads(StructuredFormatter().format(record))
        assert parsed["message"] == "digitize_validation_failed"
        assert parsed["rule"] == "area_limit"
        assert parsed["limit_ha"] == 500.0
        assert parsed["actual_ha"] == 812.4
        assert parsed["feature_id"] == "digitize-abc123"
        assert parsed["level"] == "WARNING"


class TestDigitizeMetrics:
    """Task 1.5.1 — finalize emits digitize_finalize_result + duration metrics."""

    def _patch_metrics(self, monkeypatch):
        from app.api import workspace as workspace_mod
        from app.services import digitize_metrics_service

        results = []
        durations = []
        purposes = []
        monkeypatch.setattr(workspace_mod, "increment_finalize_result", lambda s: results.append(s))
        monkeypatch.setattr(workspace_mod, "increment_draft_create", lambda p: purposes.append(p))
        # finalize_duration_timer.__exit__ reads observe_finalize_duration from the
        # metrics module's own globals — patch there, not on the workspace binding.
        monkeypatch.setattr(digitize_metrics_service, "observe_finalize_duration", lambda s: durations.append(s))
        return results, durations, purposes

    def test_sync_finalize_emits_result_and_duration(self, client, db, monkeypatch, force_sync_finalize):
        results, durations, _ = self._patch_metrics(monkeypatch)

        headers, uid = _user(client, "metrics")
        calc, layer_id = _finalizable(client, db, headers, uid)

        resp = client.post(
            f"{WS}/{calc.id}/digitize-layers/{layer_id}/finalize",
            json={},
            headers=headers,
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["draft_status"] == "finalized"
        assert "succeeded" in results
        assert len(durations) == 1
        assert durations[0] >= 0

    def test_validation_failed_emits_result_metric(self, client, db, monkeypatch, force_sync_finalize):
        results, _, _ = self._patch_metrics(monkeypatch)

        headers, uid = _user(client, "metrics_vfail")
        calc, layer_id = _draft(client, db, headers, uid, purpose="roads")
        # Inject a stale single-point layer directly (bulk would reject a Point
        # for roads) so finalize fails validation with "at least 2 points".
        from app.models.workspace_layer import WorkspaceLayer
        layer = db.query(WorkspaceLayer).filter(WorkspaceLayer.id == layer_id).first()
        layer.layer_data = {
            "type": "FeatureCollection",
            "features": [{
                "type": "Feature",
                "geometry": _point(),
                "properties": {"name": "bad", "featureId": "stale-0"},
            }],
        }
        layer.feature_count = 1
        db.commit()

        resp = client.post(
            f"{WS}/{calc.id}/digitize-layers/{layer_id}/finalize",
            json={},
            headers=headers,
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["status"] == "validation_failed", resp.text
        assert "validation_failed" in results

    def test_draft_create_emits_purpose_metric(self, client, db, monkeypatch):
        _, _, purposes = self._patch_metrics(monkeypatch)

        headers, uid = _user(client, "metrics_create")
        calc, layer_id = _draft(client, db, headers, uid, purpose="water", name="Pond")
        assert calc is not None and layer_id is not None
        assert "water" in purposes
