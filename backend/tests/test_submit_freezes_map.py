"""Submitting for analysis freezes the map (H-SUBMIT A1–A3).

`structure_locked` used to be set in exactly one place -- `dfo_approve`, at
`completed -> locked`. So the whole span from submission, through the analysis
run, through the DFO review, left the geometry editable. Analysis reads geometry
at run time, so a block edited mid-run produced areas, volumes, biomass and
carbon describing a shape that no longer existed, with nothing marking the
result stale and nothing telling the reviewer the map had moved under them.

The lock is not a trap. `withdraw_submission` gives the map back while analysis
has not started, because requiring a support request to fix a typo thirty
seconds after submitting teaches people not to submit -- which costs more than
it saves. The window closes the moment the state leaves `submitted`.
"""
from __future__ import annotations

import uuid

import pytest

from app.api.deps import ALLOWED_TRANSITIONS
from app.models.calculation import MapLifecycleStatus


@pytest.fixture()
def owned_calc(db):
    """A draft calculation belonging to conftest's authenticated user."""
    from app.models.calculation import Calculation
    from app.models.user import User

    me = db.query(User).filter(User.email == "testuser@example.com").first()
    assert me is not None, "conftest's auth_headers user is missing"
    calc = Calculation(
        user_id=me.id,
        forest_name=f"Submit Freeze {uuid.uuid4().hex[:6]}",
        map_lifecycle_status=MapLifecycleStatus.DRAFT.value,
    )
    db.add(calc)
    db.commit()
    return calc


def _submit(client, headers, calc_id):
    return client.post(f"/api/v1/calculations/{calc_id}/submit-for-calculation",
                       headers=headers)


def _withdraw(client, headers, calc_id):
    return client.post(f"/api/v1/calculations/{calc_id}/withdraw-submission",
                       headers=headers)


class TestSubmitFreezes:
    def test_the_map_is_locked_after_submitting(self, client, auth_headers, db, owned_calc):
        assert owned_calc.structure_locked in (False, None), "precondition"

        response = _submit(client, auth_headers, owned_calc.id)
        assert response.status_code == 200, response.text
        assert response.json()["structure_locked"] is True

        db.expire_all()
        db.refresh(owned_calc)
        assert owned_calc.structure_locked is True
        assert owned_calc.structure_locked_at is not None
        assert owned_calc.map_lifecycle_status == MapLifecycleStatus.SUBMITTED.value

    def test_the_response_says_so(self, client, auth_headers, owned_calc):
        """The client has to know without a second round trip, or the toolbar
        stays enabled and the first edit fails with a 423 instead of being
        disabled."""
        body = _submit(client, auth_headers, owned_calc.id).json()
        assert body["structure_locked"] is True
        assert body["map_lifecycle_status"] == "submitted"


class TestSubmitStartsTheAnalysis:
    """Submitting used to start nothing at all.

    The endpoint's docstring said it handed the map "to the calculation queue";
    it set `map_lifecycle_status` and returned. `run_calculation_task` -- the
    pipeline carrying progress reporting, cost tracking, saga compensation, the
    state machine and H3.5's fail-fast gate -- was **enqueued by nothing
    anywhere in the backend**. Users reached analysis through the legacy page's
    "Re-run Analysis" button, which runs an older path synchronously in the
    request and bypasses the fail-fast gate.
    """

    def test_the_job_is_enqueued(self, client, auth_headers, owned_calc, monkeypatch):
        captured = {}

        class _Pool:
            async def enqueue_job(self, name, *args, **kwargs):
                captured["name"] = name
                captured["args"] = args
                captured["queue"] = kwargs.get("_queue_name")
                return "job-1"

            async def close(self):
                captured["closed"] = True

        async def _fake_create_pool(*_a, **_k):
            return _Pool()

        import arq
        monkeypatch.setattr(arq, "create_pool", _fake_create_pool)

        response = _submit(client, auth_headers, owned_calc.id)
        assert response.status_code == 200, response.text
        assert response.json()["analysis_queued"] is True
        assert captured["name"] == "run_calculation_task"
        assert captured["args"] == (str(owned_calc.id),)
        # The dedicated queue: the reports worker polls the default one and
        # only knows generate_report_task.
        assert captured["queue"] == "arq:calculation"
        assert captured.get("closed") is True

    def test_a_dead_worker_does_not_fail_the_submission(
            self, client, auth_headers, db, owned_calc, monkeypatch):
        """The fallback is the part most likely to matter in practice.

        A worker that is merely not running must not leave the user with a
        frozen map and a 500. The submission succeeded; what failed is the
        hand-off, and the response says so rather than claiming a run began.
        """
        async def _boom(*_a, **_k):
            raise ConnectionError("redis is not listening")

        import arq
        monkeypatch.setattr(arq, "create_pool", _boom)

        response = _submit(client, auth_headers, owned_calc.id)
        assert response.status_code == 200, response.text
        assert response.json()["analysis_queued"] is False
        # The freeze still happened -- that is the guarantee, and it does not
        # depend on the worker.
        assert response.json()["structure_locked"] is True
        db.expire_all()
        db.refresh(owned_calc)
        assert owned_calc.structure_locked is True
        assert owned_calc.map_lifecycle_status == MapLifecycleStatus.SUBMITTED.value

    def test_the_worker_registers_the_job_name_we_enqueue(self):
        """Guards the string.

        `enqueue_job` takes a NAME. If the worker's registered function is
        renamed and this string is not, the job is accepted by Redis and never
        runs -- silently, which is how `run_calculation_task` came to be
        unreachable in the first place.
        """
        from app.calculation_worker import CalculationWorkerSettings

        names = {f.__name__ for f in CalculationWorkerSettings.functions}
        assert "run_calculation_task" in names
        assert CalculationWorkerSettings.queue_name == "arq:calculation"


class TestWithdraw:
    def test_the_owner_can_take_it_back_before_analysis(self, client, auth_headers, db, owned_calc):
        _submit(client, auth_headers, owned_calc.id)

        response = _withdraw(client, auth_headers, owned_calc.id)
        assert response.status_code == 200, response.text
        assert response.json()["map_lifecycle_status"] == "draft"
        assert response.json()["structure_locked"] is False

        db.expire_all()
        db.refresh(owned_calc)
        assert owned_calc.structure_locked is False
        assert owned_calc.map_lifecycle_status == MapLifecycleStatus.DRAFT.value

    def test_the_submission_marks_are_cleared(self, client, auth_headers, db, owned_calc):
        """A withdrawn map was never submitted, as far as the next submission is
        concerned. Leaving `submitted_at` set would make the audit trail claim
        two submissions where there was one."""
        _submit(client, auth_headers, owned_calc.id)
        _withdraw(client, auth_headers, owned_calc.id)
        db.expire_all()
        db.refresh(owned_calc)
        assert owned_calc.submitted_at is None
        assert owned_calc.submitted_by is None

    def test_it_is_refused_once_analysis_has_started(self, client, auth_headers, db, owned_calc):
        """The window is exactly `submitted`.

        From `calculating` a withdrawal would race a running analysis, so it
        becomes the DFO's decision rather than the owner's.
        """
        _submit(client, auth_headers, owned_calc.id)
        owned_calc.map_lifecycle_status = MapLifecycleStatus.CALCULATING.value
        db.commit()

        response = _withdraw(client, auth_headers, owned_calc.id)
        assert response.status_code == 409, response.text
        detail = response.json()["detail"]
        assert detail["code"] == "NOT_WITHDRAWABLE"
        # The message must say what to do next, not merely refuse.
        assert "DFO" in detail["message"]
        assert detail["current_state"] == "calculating"

    def test_it_is_refused_on_a_draft(self, client, auth_headers, owned_calc):
        response = _withdraw(client, auth_headers, owned_calc.id)
        assert response.status_code == 409
        assert response.json()["detail"]["current_state"] == "draft"

    def test_withdrawing_then_resubmitting_works(self, client, auth_headers, owned_calc):
        """The round trip has to be usable, or the escape hatch is theatre."""
        assert _submit(client, auth_headers, owned_calc.id).status_code == 200
        assert _withdraw(client, auth_headers, owned_calc.id).status_code == 200
        again = _submit(client, auth_headers, owned_calc.id)
        assert again.status_code == 200, again.text
        assert again.json()["structure_locked"] is True


class TestTheTransitionTable:
    def test_submitted_may_return_to_draft(self):
        assert "draft" in ALLOWED_TRANSITIONS["submitted"]

    def test_submitted_can_still_proceed(self):
        """The withdrawal path must not have removed the forward ones."""
        assert {"calculating", "failed"} <= ALLOWED_TRANSITIONS["submitted"]


class TestTheLockActuallyBites:
    def test_a_geometry_write_is_refused_while_submitted(self, client, auth_headers, db, owned_calc):
        """The guarantee, end to end.

        `require_draw_role` and `require_unlocked_structure` already answered
        423 on a locked map; what was missing was anything setting the flag at
        submission. This asserts the two halves meet.
        """
        from app.api.deps import require_unlocked_structure

        _submit(client, auth_headers, owned_calc.id)
        db.expire_all()
        db.refresh(owned_calc)

        with pytest.raises(Exception) as exc:
            require_unlocked_structure(calc=owned_calc)
        assert getattr(exc.value, "status_code", None) == 423
        assert exc.value.detail["code"] == "structure_locked"
