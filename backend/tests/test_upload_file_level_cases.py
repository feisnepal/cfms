"""UP-0.5 leftovers: a legacy .xls / password-protected workbook and an over-size file are explained, not raw errors."""
from __future__ import annotations

import json
import uuid

import pytest

from app.models.calculation import Calculation
from tests import upload_fixtures as fx
from tests.test_household_upload_overwrite_branches import _owner

RAW = ("Traceback", "zipfile", "BadZip", "bad magic", "openpyxl", "xlrd")


@pytest.fixture()
def forest(client, db):
    headers, user = _owner(client, db)
    c = Calculation(user_id=user.id, forest_name=f"FL {uuid.uuid4().hex[:6]}")
    db.add(c)
    db.commit()
    return headers, c


@pytest.mark.parametrize("name", ["hh.xls", "hh.xlsx"])
def test_a_legacy_or_password_protected_workbook_says_how_to_fix_it(client, forest, name):
    headers, c = forest
    r = client.post(f"/api/household/calculations/{c.id}/upload", headers=headers, files={"file": (name, fx.legacy_xls(), "application/octet-stream")})
    d = r.json()["detail"]
    assert r.status_code == 400 and d["code"] == "file.corrupt" and "password" in d["message"] and ".xlsx" in d["message"] and d["message_np"]
    assert not any(m in json.dumps(d) for m in RAW)


def test_an_over_size_upload_is_a_plain_bilingual_413(client, forest):
    headers, c = forest
    r = client.post(f"/api/household/calculations/{c.id}/upload", headers=headers, files={"file": ("big.csv", fx.oversize(51), "text/csv")})
    assert r.status_code == 413
    body = r.json()
    assert body["error_code"] == "REQUEST_BODY_TOO_LARGE"  # existing clients keep working
    d = body["detail"]
    assert d["code"] == "file.too_large" and "50 MB" in d["message"] and "Split the data" in d["message"] and d["message_np"]
    assert d["findings"][0]["fix_ne"]
