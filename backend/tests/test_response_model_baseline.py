"""H4.8 / S3-47 — the response-model coverage ratchet's route walker.

The gate itself is `scripts/check_response_model_baseline.py`:
CI fails if the count of routes lacking a `response_model` increases.

FastAPI keeps `include_router` results as `_IncludedRouter` wrappers whose
mount prefix lives in `include_context.prefix` while the real, unprefixed
leaf paths sit behind `include_context.included_router`. A flat scan of
`app.routes` therefore reports neither the true path nor the true count —
exactly the failure mode a gate must not have. The tests build the real
nested shape and assert the walker reconstructs the mounted URLs.
"""
import pytest
from fastapi import FastAPI, APIRouter
from pydantic import BaseModel


class _Model(BaseModel):
    ok: bool


@pytest.fixture
def app() -> FastAPI:
    """An app with a nested-router shape mirroring the production one."""
    typed = APIRouter()
    untyped = APIRouter()

    @typed.get("/typed", response_model=_Model)
    async def typed_route():
        return {"ok": True}

    @untyped.get("/untyped")
    async def untyped_route():
        return {"untyped": True}

    @untyped.post("/untyped")
    async def untyped_post():
        return {"untyped": True}

    outer = APIRouter()
    outer.include_router(typed, prefix="/typed-prefix")
    outer.include_router(untyped, prefix="/untyped-prefix")

    app_ = FastAPI()
    app_.include_router(outer, prefix="/api/v1")
    return app_


def test_counts_only_routes_without_a_model(app: FastAPI):
    from scripts.check_response_model_baseline import url_of_untyped_routes

    found = url_of_untyped_routes(app)
    assert len(found) == 2  # typed GET is excluded; untyped GET + POST counted
    assert "GET    /api/v1/untyped-prefix/untyped" in found
    assert "POST   /api/v1/untyped-prefix/untyped" in found
    assert not any(k.endswith("/typed") for k in found)


def test_excludes_the_legacy_api_shim():
    from fastapi import FastAPI, APIRouter
    from scripts.check_response_model_baseline import url_of_untyped_routes

    # Production mounts the same aggregate router under both /api/v1 and /api
    # (S3-48). The ratchet must count the canonical namespace once, not twice.
    leaf = APIRouter()

    @leaf.get("/leaf", response_model=_Model)
    async def leaf_typed():
        return {"ok": True}

    @leaf.get("/bare")
    async def leaf_bare():
        return {"bare": True}

    def build(base: str) -> APIRouter:
        router = APIRouter()
        router.include_router(leaf, prefix=f"{base}/nested")
        return router

    prod = FastAPI()
    prod.include_router(build("/api/v1"))
    prod.include_router(build("/api"))

    found = url_of_untyped_routes(prod)
    assert len(found) == 1
    assert "GET    /api/v1/nested/bare" in found
    assert not any("/api/" in k and "/api/v1/" not in k for k in found)


def test_flat_scan_would_miss_the_nested_routes(app: FastAPI):
    """Guard that asserts the walker is actually needed."""
    from fastapi.routing import APIRoute
    from fastapi.routing import _IncludedRouter

    flat = [r for r in app.routes if isinstance(r, APIRoute)]
    wrappers = [r for r in app.routes if isinstance(r, _IncludedRouter)]
    assert len(flat) == 0  # app.routes holds ONLY wrappers at the top level
    assert len(wrappers) >= 1