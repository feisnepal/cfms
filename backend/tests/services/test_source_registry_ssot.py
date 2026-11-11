"""One source registry, one rejection (RS-0.3).

The natural divide sources are registered in TWO places: a module-level
``_PREVIEW_BY_SOURCE`` in ``auto_block_service`` and a function-local ``_PREVIEW_FNS``
in ``editing.py`` that was rebuilt on every auto-create preview request. The
divide-commit endpoint added a THIRD form of the same fact (``body.source not in
DIVIDE_SOURCES``). Nothing failed loudly when those drifted -- a source could be
registered in the service and silently rejected by the API -- and the three
endpoints rejected an unknown source through three different code paths.

These tests pin the contract RS-0.3 established:

* ``PREVIEW_FN_BY_SOURCE`` is the only map, and ``DIVIDE_SOURCES`` is derived from it;
* every endpoint rejects an unknown source with a byte-identical ``detail``;
* a source registered in that one place is immediately live on the endpoints that
  dispatch (this is the test that fails against the old duplicated dict);
* the divide-commit guard consults the same registry rather than a private copy.

No raster is ever touched: every case is about dispatch, so sources are either
rejected before any raster work or replaced with a stub.
"""

from __future__ import annotations

import uuid

import pytest
from geoalchemy2.shape import from_shape
from shapely.geometry import Polygon

from app.models.calculation import Calculation
from app.models.forest_block import ForestBlock
from app.models.user import User
from app.services import auto_block_service as svc

# 0.002 deg square, same shape the divide tests use.
_FOREST = Polygon([(84.0, 27.0), (84.002, 27.0), (84.002, 27.002), (84.0, 27.002)])

KNOWN_SOURCES = (
    "mmu", "slope", "aspect", "canopy", "nasa_quality",
    "forest_health", "landcover", "dem", "forest_type",
    "union_zonal", "union_fusion",
)


@pytest.fixture()
def owner(client, db):
    """A registered user with auth headers, the way the other suites build one."""
    email = f"ssot-{uuid.uuid4().hex[:8]}@example.com"
    client.post(
        "/api/auth/register",
        json={"email": email, "password": "TestPass123!", "full_name": "SSOT Tester"},
    )
    r = client.post(
        "/api/auth/login", json={"email": email, "password": "TestPass123!"}
    )
    headers = {"Authorization": f"Bearer {r.json()['access_token']}"}
    return headers, db.query(User).filter(User.email == email).first()


def _make_calc(db, user):
    calc = Calculation(
        id=str(uuid.uuid4()),
        user_id=user.id,
        uploaded_filename="ssot.csv",
        is_draft=False,
        structure_locked=False,
        result_data={},
    )
    db.add(calc)
    db.flush()
    calc.boundary_geom = from_shape(_FOREST, srid=4326)
    db.commit()
    return calc


@pytest.fixture()
def empty_calc(db, owner):
    """A calculation with a boundary and NO blocks -- auto-create's precondition."""
    _headers, user = owner
    return _make_calc(db, user)


@pytest.fixture()
def divide_calc(db, owner):
    """A calculation that already has one block, for the two divide endpoints.

    Deliberately a *different* calculation from ``empty_calc``: auto-create
    refuses 409 BLOCKS_EXIST once any block exists, so the three endpoints can
    never all be exercised against one row.
    """
    _headers, user = owner
    return _make_calc(db, user)


@pytest.fixture()
def parent_block(db, divide_calc):
    """A block on the divide calculation."""
    block = ForestBlock(
        calculation_id=divide_calc.id,
        name="Block-1",
        block_name="Block-1",
        geometry=from_shape(_FOREST, srid=4326),
        area_hectares=1.0,
        area_sqm=10000.0,
        index=1,
        is_compartment=False,
        division_level=1,
        parent_block_id=None,
        is_locked=False,
        child_count=0,
    )
    db.add(block)
    db.commit()
    return block


def _stub_result(db_, calc_, **kwargs):
    """Minimal valid preview payload: meta + empty FeatureCollection + edges."""
    return {
        "meta": {"source_layer": "rasters.stub"},
        "pieces": {"type": "FeatureCollection", "features": []},
        "edges": [],
    }


# --------------------------------------------------------------------------
# The registry itself
# --------------------------------------------------------------------------


def test_the_registry_holds_exactly_the_known_sources():
    """NASA was added as a fifth source (D33, RS-2.x) but this list was left at
    four, so the guard silently stopped covering the newest source. It failed only
    when the suite was finally run as part of a commit gate."""
    assert tuple(svc.PREVIEW_FN_BY_SOURCE) == KNOWN_SOURCES
    for name in KNOWN_SOURCES:
        assert callable(svc.PREVIEW_FN_BY_SOURCE[name])


def test_divide_sources_is_derived_not_a_second_list():
    """The whole point of the change: no hand-maintained second copy."""
    assert svc.DIVIDE_SOURCES == tuple(svc.PREVIEW_FN_BY_SOURCE)
    for name in KNOWN_SOURCES:
        assert svc.is_valid_source(name)
    assert not svc.is_valid_source("moonlight")


def test_resolve_source_fn_raises_the_one_canonical_code():
    with pytest.raises(ValueError) as exc:
        svc.resolve_source_fn("moonlight")
    assert str(exc.value) == svc.SOURCE_ERROR_CODE == "bad_source"


def test_resolve_source_fn_returns_the_registered_function():
    for name in KNOWN_SOURCES:
        assert svc.resolve_source_fn(name) is svc.PREVIEW_FN_BY_SOURCE[name]


# --------------------------------------------------------------------------
# The gate: one rejection shape across all three endpoints
# --------------------------------------------------------------------------


def test_all_three_endpoints_reject_an_unknown_source_identically(
    client, db, owner, empty_calc, divide_calc, parent_block
):
    """The RS-0.3 acceptance criterion, asserted on the wire.

    Auto-create preview, divide preview and divide commit previously reached
    ``blocks.bad_source`` by three unrelated routes. They must now emit the same
    status AND the same serialized ``detail``.
    """
    headers, _user = owner
    create_base = f"/api/v1/calculations/{empty_calc.id}"
    divide = (
        f"/api/v1/calculations/{divide_calc.id}/blocks/{parent_block.id}/auto-divide"
    )

    create = client.post(
        f"{create_base}/auto-blocks/preview",
        headers=headers,
        json={"level": "blocks", "source": "moonlight"},
    )
    preview = client.post(
        f"{divide}/preview", headers=headers, json={"source": "moonlight"}
    )
    commit = client.post(
        f"{divide}/commit", headers=headers, json={"source": "moonlight", "blocks": []}
    )

    assert create.status_code == preview.status_code == commit.status_code == 400
    assert create.json()["detail"] == preview.json()["detail"] == commit.json()["detail"]

    detail = create.json()["detail"]
    assert detail["code"] == "blocks.bad_source"
    # Bilingual, so the client can render either language from one response.
    assert detail.get("message") and detail.get("message_np")


# --------------------------------------------------------------------------
# The regression: registering a source once makes it live on the dispatcher
# --------------------------------------------------------------------------


def test_a_source_registered_once_is_live_on_both_dispatch_endpoints(
    client, db, owner, empty_calc, divide_calc, parent_block, monkeypatch
):
    """FAILS against the old code.

    ``editing.py`` kept its own ``_PREVIEW_FNS`` dict, so a source added to
    ``auto_block_service`` alone was rejected by the auto-create preview with a
    400 while the divide preview dispatched to it. Registering through the single
    map must be enough for both.
    """
    headers, _user = owner
    calls = []

    def _recording_stub(db_, calc_, **kwargs):
        calls.append(kwargs.get("level"))
        return _stub_result(db_, calc_, **kwargs)

    monkeypatch.setitem(svc.PREVIEW_FN_BY_SOURCE, "stub", _recording_stub)

    base = f"/api/v1/calculations/{empty_calc.id}"
    create = client.post(
        f"{base}/auto-blocks/preview",
        headers=headers,
        json={"level": "blocks", "source": "stub"},
    )
    preview = client.post(
        f"/api/v1/calculations/{divide_calc.id}"
        f"/blocks/{parent_block.id}/auto-divide/preview",
        headers=headers,
        json={"source": "stub"},
    )

    # Both must have dispatched to the stub, not rejected the source.
    assert create.status_code == 200, create.text
    assert preview.status_code == 200, preview.text
    assert len(calls) == 2
    assert create.json()["meta"]["source_layer"] == "rasters.stub"
    assert preview.json()["meta"]["source"] == "stub"


def test_the_divide_commit_guard_reads_the_same_registry(
    client, db, owner, divide_calc, parent_block, monkeypatch
):
    """Commit never calls a preview function, so assert the guard itself.

    A registered source gets *past* the source check and fails on the next rule
    (empty blocks); an unregistered one never gets that far. That difference is
    only observable if the guard reads the same map the dispatcher does.
    """
    headers, _user = owner
    url = (
        f"/api/v1/calculations/{divide_calc.id}"
        f"/blocks/{parent_block.id}/auto-divide/commit"
    )

    monkeypatch.setitem(svc.PREVIEW_FN_BY_SOURCE, "stub", lambda *a, **k: {})

    registered = client.post(
        url, headers=headers, json={"source": "stub", "blocks": []}
    )
    assert registered.status_code == 400
    assert registered.json()["detail"]["code"] == "blocks.empty_blocks"

    unknown = client.post(
        url, headers=headers, json={"source": "moonlight", "blocks": []}
    )
    assert unknown.status_code == 400
    assert unknown.json()["detail"]["code"] == "blocks.bad_source"
