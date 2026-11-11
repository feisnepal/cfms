"""Coverage for the app exception handler's IntegrityError branch (H4.2).

The natural-key tests raise `IntegrityError` in-process but never route one
through the app's `SQLAlchemyError` exception handler, so its 409 path (and the
constraint-name lookup) stayed uncovered. These drive the handler directly.
"""
from __future__ import annotations

import uuid

import pytest
from fastapi import Request
from sqlalchemy.exc import IntegrityError

from app.main import (
    _NATURAL_KEY_MESSAGES,
    database_exception_handler,
    app,
)


def _request():
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/api/v1/household/bulk",
        "headers": [],
        "app": app,
    }
    return Request(scope)


def _integrity_error(constraint: str) -> IntegrityError:
    class _Diag:
        constraint_name = constraint

    class _Orig(Exception):
        diag = _Diag()

    exc = IntegrityError("stmt", {}, Exception("boom"))
    exc.orig = _Orig()
    return exc


@pytest.mark.anyio
async def test_a_known_natural_key_conflict_answers_409():
    constraint = list(_NATURAL_KEY_MESSAGES)[0]
    code = _NATURAL_KEY_MESSAGES[constraint]
    req = _request()
    resp = await database_exception_handler(req, _integrity_error(constraint))
    assert resp.status_code == 409
    assert resp.body
    import json
    body = json.loads(resp.body)
    assert body["detail"]["code"] == code


@pytest.mark.anyio
async def test_an_unknown_integrity_error_falls_back_to_bad_request():
    req = _request()
    resp = await database_exception_handler(
        req, _integrity_error("some_other_constraint"))
    import json
    body = json.loads(resp.body)
    assert resp.status_code == 409
    assert body["detail"]["code"] == "general.bad_request"
