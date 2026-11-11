"""The automatic user group analysis (settlements, then land cover & biomass) and the status stored with the calculation (UP-1.1, UP-1.2)."""
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.models.calculation import Calculation
from app.services import user_group_auto_analysis as auto
from app.services import user_group_analysis as ugs


@pytest.fixture()
def calc(db):
    from app.models.user import User

    u = User(email=f"ugs-{uuid.uuid4().hex[:8]}@example.com", hashed_password="x", full_name="UG status")
    db.add(u)
    db.flush()
    c = Calculation(user_id=u.id, forest_name="UG status", result_data={"keep": 1})
    db.add(c)
    db.commit()
    return c


def _status(db, c):
    db.expire_all()
    return auto.read_status(db.get(Calculation, c.id).result_data)


class _Svc:
    """A stand-in for UserGroupAnalysisService: records the order of the two steps and can fail either."""

    calls: list = []
    fail_all: Exception | None = None
    fail_land: Exception | None = None

    def __init__(self, db):
        pass

    async def analyze_all(self, calculation_id):
        _Svc.calls.append("settlements")
        if _Svc.fail_all:
            raise _Svc.fail_all
        return []

    async def analyze_land_cover(self, calculation_id, force_refresh=False):
        _Svc.calls.append(("land_cover", force_refresh))
        if _Svc.fail_land:
            raise _Svc.fail_land
        return {}


@pytest.fixture()
def svc(monkeypatch):
    _Svc.calls, _Svc.fail_all, _Svc.fail_land = [], None, None
    monkeypatch.setattr(ugs, "UserGroupAnalysisService", _Svc)
    return _Svc


def test_nothing_ran_reads_as_idle(db, calc):
    assert _status(db, calc) == {"state": "idle", "steps": {}}


def test_land_cover_and_biomass_run_by_themselves_right_after_the_settlements(db, calc, svc):
    asyncio.run(auto._analyse(db, str(calc.id)))
    assert svc.calls == ["settlements", ("land_cover", True)]  # forced: the polygons just changed
    st = _status(db, calc)
    assert st["state"] == "done" and st["steps"] == {"settlements": "done", "land_cover": "done"} and st["finished_at"]


def test_a_land_cover_failure_leaves_the_settlements_done_and_says_which_step_did_not_run(db, calc, svc):
    svc.fail_land = ValueError("No land cover data found. Please ensure raster datasets are available.")
    asyncio.run(auto._analyse(db, str(calc.id)))
    st = _status(db, calc)
    assert st["state"] == "done" and st["steps"] == {"settlements": "done", "land_cover": "failed"} and "No land cover data" in st["message"]


def test_an_over_limit_group_is_reported_as_skipped_with_the_reason(db, calc, svc):
    svc.fail_all = ugs.UserGroupTooLarge(6200, 5000)
    asyncio.run(auto._analyse(db, str(calc.id)))
    st = _status(db, calc)
    assert st["state"] == "skipped" and "5,000 ha" in st["message"] and svc.calls == ["settlements"]  # land cover is not attempted


def test_a_settlement_failure_is_reported_as_failed_and_land_cover_is_not_attempted(db, calc, svc):
    svc.fail_all = RuntimeError("boom")
    asyncio.run(auto._analyse(db, str(calc.id)))
    st = _status(db, calc)
    assert st["state"] == "failed" and st["steps"] == {"settlements": "failed"} and svc.calls == ["settlements"]


def test_writing_the_status_never_clobbers_the_other_keys_of_result_data(db, calc):
    auto.write_status(str(calc.id), db, state="running", started_at=auto._now(), steps={})
    auto.write_status(str(calc.id), db, state="done", finished_at=auto._now())
    db.expire_all()
    rd = db.get(Calculation, calc.id).result_data
    assert rd["keep"] == 1 and rd[auto.STATUS_KEY]["state"] == "done" and rd[auto.STATUS_KEY]["started_at"]  # merged, not replaced


def test_a_running_status_that_is_too_old_is_reported_as_interrupted():
    old = (datetime.now(timezone.utc) - timedelta(minutes=20)).isoformat()
    st = auto.read_status({auto.STATUS_KEY: {"state": "running", "started_at": old}})
    assert st["state"] == "failed" and st["message"] == "interrupted"
    fresh = datetime.now(timezone.utc).isoformat()
    assert auto.read_status({auto.STATUS_KEY: {"state": "running", "started_at": fresh}})["state"] == "running"


def test_the_status_endpoint_reports_the_stored_status_to_the_owner_only(client, db, calc):
    from tests.test_household_upload_overwrite_branches import _owner

    headers, user = _owner(client, db)
    mine = Calculation(user_id=user.id, forest_name="mine", result_data={})
    db.add(mine)
    db.commit()
    auto.write_status(str(mine.id), db, state="done", steps={"settlements": "done", "land_cover": "done"})
    r = client.get(f"/api/calculations/{mine.id}/user-group/analysis-status", headers=headers)
    assert r.status_code == 200 and r.json()["state"] == "done"
    other = client.get(f"/api/calculations/{calc.id}/user-group/analysis-status", headers=headers)  # someone else's forest
    assert other.status_code == 403
