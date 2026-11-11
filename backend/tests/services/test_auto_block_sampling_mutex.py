"""Auto-Block commit/preview vs. the compartment <-> block-level-sampling mutex.

Compartments and block-level sampling are mutually exclusive: the
`check_dimension_exclusivity()` trigger on `forest_blocks` rejects any
`is_compartment` insert once a `sampling_designs` row exists for the
calculation. Auto-Block commit did not check first, so the user designed a whole
compartment split, pressed Commit, and got a bare 500 ("Internal server error
Reference: ...") from the raw RaiseException. The guard now answers with the
same bilingual 400 the divide-compartment endpoints use, and the preview says so
before any work is done. Block level is unaffected.
"""

from __future__ import annotations

import uuid

import pytest
from geoalchemy2.shape import from_shape
from shapely.geometry import Polygon, mapping

from app.models.calculation import Calculation
from app.models.forest_block import ForestBlock
from app.models.sampling import SamplingDesign
from app.models.user import User, UserRole
from app.services import auto_block_service as svc

_BOUNDARY = Polygon([(84.0, 27.0), (84.002, 27.0), (84.002, 27.002), (84.0, 27.002)])
_LEFT = Polygon([(84.0, 27.0), (84.001, 27.0), (84.001, 27.002), (84.0, 27.002)])
_RIGHT = Polygon([(84.001, 27.0), (84.002, 27.0), (84.002, 27.002), (84.001, 27.002)])

MUTEX_CODE = "compartments.sampling_mutex"


def _owner(client, db):
    email = f"mutex-{uuid.uuid4().hex[:8]}@example.com"
    client.post(
        "/api/auth/register",
        json={"email": email, "password": "TestPass123!", "full_name": "Mutex Tester"},
    )
    r = client.post(
        "/api/auth/login", json={"email": email, "password": "TestPass123!"}
    )
    headers = {"Authorization": f"Bearer {r.json()['access_token']}"}
    return headers, db.query(User).filter(User.email == email).first()


def _make_calc(db, user=None, with_sampling=False):
    if user is None:
        user = User(
            email=f"mutexsvc{uuid.uuid4().hex[:8]}@test.com",
            full_name="Mutex Service Tester",
            role=UserRole.USER,
            hashed_password="not-a-real-hash",
        )
        db.add(user)
        db.flush()
    calc = Calculation(
        id=str(uuid.uuid4()),
        user_id=user.id,
        uploaded_filename="sampling-mutex-test.csv",
        is_draft=False,
    )
    db.add(calc)
    db.flush()
    calc.boundary_geom = from_shape(_BOUNDARY, srid=4326)
    if with_sampling:
        db.add(SamplingDesign(calculation_id=calc.id, sampling_type="systematic"))
    db.commit()
    return calc


def _payload():
    return [
        {"index": 1, "name": "C-1", "block_name": "C-1", "geometry": mapping(_LEFT)},
        {"index": 2, "name": "C-2", "block_name": "C-2", "geometry": mapping(_RIGHT)},
    ]


def _block_count(db, calc):
    return db.query(ForestBlock).filter(ForestBlock.calculation_id == calc.id).count()


# ---------------------------------------------------------------------------
# Service layer
# ---------------------------------------------------------------------------
def test_commit_compartments_refused_when_sampling_exists(db):
    calc = _make_calc(db, with_sampling=True)
    with pytest.raises(ValueError, match=r"^SAMPLING_MUTEX:"):
        svc.commit_blocks(db, calc, _payload(), level="compartments")
    # Refused before any insert, so nothing was written (and the trigger never fired).
    assert _block_count(db, calc) == 0


def test_commit_blocks_allowed_when_sampling_exists(db):
    """The trigger only guards compartments — block level must stay open."""
    calc = _make_calc(db, with_sampling=True)
    created = svc.commit_blocks(db, calc, _payload(), level="blocks")
    assert len(created) == 2
    assert _block_count(db, calc) == 2


def test_commit_compartments_allowed_without_sampling(db):
    calc = _make_calc(db, with_sampling=False)
    created = svc.commit_blocks(db, calc, _payload(), level="compartments")
    assert len(created) == 2
    rows = db.query(ForestBlock).filter(ForestBlock.calculation_id == calc.id).all()
    assert all(r.is_compartment for r in rows)


def test_check_only_applies_to_compartment_level(db):
    calc = _make_calc(db, with_sampling=True)
    svc.check_compartment_sampling_mutex(db, calc, "blocks")  # no raise
    with pytest.raises(ValueError, match=r"^SAMPLING_MUTEX:"):
        svc.check_compartment_sampling_mutex(db, calc, "compartments")


# ---------------------------------------------------------------------------
# API — the answer the user actually sees (400 + bilingual message, not a 500)
# ---------------------------------------------------------------------------
def test_api_commit_compartments_returns_400_not_500(client, db):
    headers, user = _owner(client, db)
    calc = _make_calc(db, user=user, with_sampling=True)

    resp = client.post(
        f"/api/v1/calculations/{calc.id}/auto-blocks/commit",
        headers=headers,
        json={"level": "compartments", "blocks": _payload()},
    )
    assert resp.status_code == 400, resp.text
    detail = resp.json()["detail"]
    assert detail["code"] == MUTEX_CODE
    assert "sampling" in detail["message"].lower()
    assert detail["message_np"]
    assert _block_count(db, calc) == 0


def test_api_commit_blocks_level_unaffected_by_sampling(client, db):
    headers, user = _owner(client, db)
    calc = _make_calc(db, user=user, with_sampling=True)

    resp = client.post(
        f"/api/v1/calculations/{calc.id}/auto-blocks/commit",
        headers=headers,
        json={"level": "blocks", "blocks": _payload()},
    )
    assert resp.status_code == 200, resp.text
    assert len(resp.json()["blocks"]) >= 2


def test_api_preview_compartments_refused_up_front(client, db):
    headers, user = _owner(client, db)
    calc = _make_calc(db, user=user, with_sampling=True)

    resp = client.post(
        f"/api/v1/calculations/{calc.id}/auto-blocks/preview",
        headers=headers,
        json={"level": "compartments", "source": "mmu"},
    )
    assert resp.status_code == 400, resp.text
    assert resp.json()["detail"]["code"] == MUTEX_CODE
