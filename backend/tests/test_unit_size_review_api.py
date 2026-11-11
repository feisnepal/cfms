"""P8 tier 1 - the read-only unit-size-review endpoint.

The route's job is narrow and testable: classify, propose, and change nothing.
These tests pin the read-only promise as well as the payload, because a review
endpoint that mutates a forest would be worse than the defect it reports.
"""

from __future__ import annotations

import uuid

import pytest
from geoalchemy2.shape import from_shape
from shapely.geometry import box

from app.models.calculation import Calculation
from app.models.forest_block import ForestBlock

SQM_PER_HA = 10_000.0

# 2.00 ha and 4.00 ha neighbours sharing an edge, a 0.0002 ha sliver on that edge,
# and an island. Mirrors the DB-level fixture so the payload can be checked against
# known geometry rather than a hardcoded expectation.
BIG_W = box(0.0, 0.0, 100.0, 200.0)
BIG_E = box(100.0, 0.0, 300.0, 200.0)
SLIVER = box(100.0, 100.0, 100.1, 100.2)
ISLAND = box(5000.0, 0.0, 5000.1, 5000.1)
UNITS = [("BIG-W", BIG_W), ("BIG-E", BIG_E), ("SLIVER", SLIVER), ("ISLAND", ISLAND)]


def _ha(geom) -> float:
    return geom.area / SQM_PER_HA


@pytest.fixture
def forest_with_calc(db, auth_headers):
    """A four-unit forest owned by the authenticated user, with a boundary area.

    ``auth_headers`` returns only a bearer token, so the owner is resolved by the
    fixed email that fixture registers - no dependency on a token-decoding API.
    """
    from app.models.user import User

    owner = db.query(User).filter(User.email == "testuser@example.com").first()
    assert owner is not None, "auth_headers should have registered its user"

    calc = Calculation(
        id=uuid.uuid4(),
        user_id=owner.id,
        forest_name="P8 review fixture",
        result_data={"area_hectares": 6.0},
    )
    db.add(calc)
    db.flush()
    for i, (name, geom) in enumerate(UNITS):
        db.add(
            ForestBlock(
                id=uuid.uuid4(),
                calculation_id=calc.id,
                name=name,
                block_name=name,
                geometry=from_shape(geom, srid=4326),
                area_hectares=_ha(geom),
                index=i,
                is_compartment=False,
                division_level=1,
            )
        )
    db.commit()
    try:
        yield calc
    finally:
        db.query(Calculation).filter(Calculation.id == calc.id).delete(
            synchronize_session=False
        )
        db.commit()


def test_endpoint_returns_the_three_bands(client, forest_with_calc, auth_headers):
    resp = client.get(
        f"/api/v1/calculations/{forest_with_calc.id}/unit-size-review",
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert body["read_only"] is True
    assert body["mmu_ha"] == pytest.approx(1.0)
    assert body["review_pct"] == 5.0
    assert body["boundary_area_ha"] == pytest.approx(6.0)

    by_name = {c["block_name"]: c for c in body["candidates"]}
    assert set(by_name) == {"BIG-W", "BIG-E", "SLIVER", "ISLAND"}

    # 6.0 ha boundary -> 5% screen is 0.3 ha, so only the two slivers are sub-MMU.
    assert by_name["SLIVER"]["band"] == "sub_mmu"
    assert by_name["ISLAND"]["band"] == "sub_mmu"
    assert by_name["BIG-W"]["band"] == "ok"
    assert by_name["BIG-E"]["band"] == "ok"

    assert body["summary"]["sub_mmu"] == 2
    assert body["summary"]["total"] == 4


def test_merge_proposal_names_the_larger_touching_neighbour(
    client, forest_with_calc, auth_headers
):
    resp = client.get(
        f"/api/v1/calculations/{forest_with_calc.id}/unit-size-review",
        headers=auth_headers,
    )
    by_name = {c["block_name"]: c for c in resp.json()["candidates"]}
    sliver = by_name["SLIVER"]
    # Touches both big units; the larger wins.
    assert sliver["neighbour"] == "BIG-E"
    assert sliver["neighbour_area_ha"] == pytest.approx(4.0)
    assert sliver["unmergeable"] is False
    assert "BIG-E" in sliver["reason"]


def test_island_is_reported_unmergeable_not_fine(
    client, forest_with_calc, auth_headers
):
    resp = client.get(
        f"/api/v1/calculations/{forest_with_calc.id}/unit-size-review",
        headers=auth_headers,
    )
    by_name = {c["block_name"]: c for c in resp.json()["candidates"]}
    island = by_name["ISLAND"]
    assert island["unmergeable"] is True
    assert island["neighbour"] is None
    assert "cannot be merged" in island["reason"]


def test_reason_carries_the_numbers(client, forest_with_calc, auth_headers):
    resp = client.get(
        f"/api/v1/calculations/{forest_with_calc.id}/unit-size-review",
        headers=auth_headers,
    )
    by_name = {c["block_name"]: c for c in resp.json()["candidates"]}
    reason = by_name["SLIVER"]["reason"]
    assert "1 ha" in reason
    assert "500 m2" in reason  # 5 x 500 m2 cannot fit


def test_review_pct_is_overridable_per_request(client, forest_with_calc, auth_headers):
    """5% of 6 ha is 0.3 ha, so raising it to 50% sweeps the big units into review."""
    resp = client.get(
        f"/api/v1/calculations/{forest_with_calc.id}/unit-size-review",
        headers=auth_headers,
        params={"review_pct": 50.0},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["review_pct"] == 50.0
    by_name = {c["block_name"]: c for c in body["candidates"]}
    assert by_name["BIG-W"]["band"] == "review"
    assert by_name["BIG-W"]["action"] == "flag_only"
    assert by_name["BIG-W"]["neighbour"] is None


def test_out_of_range_review_pct_is_rejected(client, forest_with_calc, auth_headers):
    for bad in (-1.0, 101.0):
        resp = client.get(
            f"/api/v1/calculations/{forest_with_calc.id}/unit-size-review",
            headers=auth_headers,
            params={"review_pct": bad},
        )
        assert resp.status_code == 422, f"review_pct={bad} should be rejected"


def test_unknown_calculation_is_404(client, auth_headers):
    resp = client.get(
        f"/api/v1/calculations/{uuid.uuid4()}/unit-size-review", headers=auth_headers
    )
    assert resp.status_code == 404


def test_another_users_calculation_is_404(client, db, auth_headers):
    """Ownership is enforced, not just existence."""
    from app.models.user import User, UserStatus

    other = User(
        id=uuid.uuid4(),
        email=f"p8-other-{uuid.uuid4().hex[:10]}@example.com",
        hashed_password="x",
        full_name="Other",
        status=UserStatus.ACTIVE,
    )
    db.add(other)
    db.flush()
    calc = Calculation(id=uuid.uuid4(), user_id=other.id, forest_name="not yours")
    db.add(calc)
    db.commit()
    try:
        resp = client.get(
            f"/api/v1/calculations/{calc.id}/unit-size-review", headers=auth_headers
        )
        assert resp.status_code == 404
    finally:
        db.query(Calculation).filter(Calculation.id == calc.id).delete(
            synchronize_session=False
        )
        db.query(User).filter(User.id == other.id).delete(synchronize_session=False)
        db.commit()


def test_the_endpoint_changes_nothing(client, db, forest_with_calc, auth_headers):
    """The read-only promise, asserted rather than asserted-in-prose."""
    before = db.query(ForestBlock).filter(
        ForestBlock.calculation_id == forest_with_calc.id
    ).count()
    result_before = dict(forest_with_calc.result_data or {})

    resp = client.get(
        f"/api/v1/calculations/{forest_with_calc.id}/unit-size-review",
        headers=auth_headers,
    )
    assert resp.status_code == 200
    client.get(
        f"/api/v1/calculations/{forest_with_calc.id}/unit-size-review",
        headers=auth_headers,
    )

    db.expire_all()
    after = db.query(ForestBlock).filter(
        ForestBlock.calculation_id == forest_with_calc.id
    ).count()
    calc = db.query(Calculation).filter(Calculation.id == forest_with_calc.id).first()
    assert after == before
    assert dict(calc.result_data or {}) == result_before


# ── the merge action needs two things the review must supply ─────────────────
def test_candidate_carries_the_id_and_layer_type_the_merge_needs(
    client, forest_with_calc, auth_headers
):
    """merge-features takes feature_ids and a layer_type, so the review must hand
    both over - otherwise the button would have to guess a name to an id."""
    resp = client.get(
        f"/api/v1/calculations/{forest_with_calc.id}/unit-size-review",
        headers=auth_headers,
    )
    by_name = {c["block_name"]: c for c in resp.json()["candidates"]}
    sliver = by_name["SLIVER"]
    # Both ids resolve to real rows, and the layer type is the unit's OWN.
    assert sliver["id"] and sliver["neighbour_id"]
    assert sliver["id"] != sliver["neighbour_id"]
    assert sliver["layer_type"] == "blocks"


def test_an_island_has_a_null_neighbour_id_and_is_not_actionable(
    client, forest_with_calc, auth_headers
):
    """The fields must not invite a merge that cannot be performed."""
    resp = client.get(
        f"/api/v1/calculations/{forest_with_calc.id}/unit-size-review",
        headers=auth_headers,
    )
    by_name = {c["block_name"]: c for c in resp.json()["candidates"]}
    island = by_name["ISLAND"]
    assert island["neighbour"] is None
    assert island["neighbour_id"] is None
    # It still has its own id and layer, so the UI can show it.
    assert island["id"]
    assert island["layer_type"] == "blocks"


def test_layer_type_is_derived_not_guessed(client, db, auth_headers):
    """A sub-compartment must report 'sub_compartments', not 'compartments'.

    The guardrail is "merge like with like", and it is only worth anything if the
    layer type follows the unit's own row rather than whatever the caller assumed.
    """
    from app.models.calculation import Calculation
    from app.models.forest_block import ForestBlock
    from app.models.user import User, UserStatus

    owner = db.query(User).filter(User.email == "testuser@example.com").first()
    other = User(
        id=uuid.uuid4(),
        email=f"p8-sub-{uuid.uuid4().hex[:10]}@example.com",
        hashed_password="x",
        full_name="Sub",
        status=UserStatus.ACTIVE,
    )
    db.add(other)
    db.flush()
    calc = Calculation(
        id=uuid.uuid4(), user_id=owner.id, forest_name="sub forest",
        result_data={"area_hectares": 4.0},
    )
    db.add(calc)
    db.flush()
    sub = ForestBlock(
        id=uuid.uuid4(),
        calculation_id=calc.id,
        name="SUB-1",
        block_name="SUB-1",
        geometry=from_shape(box(0.0, 0.0, 100.0, 100.0), srid=4326),
        area_hectares=1.0,
        index=0,
        is_compartment=True,
        division_level=2,
    )
    db.add(sub)
    db.commit()
    try:
        resp = client.get(
            f"/api/v1/calculations/{calc.id}/unit-size-review", headers=auth_headers
        )
        assert resp.status_code == 200, resp.text
        by_name = {c["block_name"]: c for c in resp.json()["candidates"]}
        assert by_name["SUB-1"]["layer_type"] == "sub_compartments"
    finally:
        db.query(Calculation).filter(Calculation.id == calc.id).delete(
            synchronize_session=False
        )
        db.query(User).filter(User.id == other.id).delete(synchronize_session=False)
        db.commit()
