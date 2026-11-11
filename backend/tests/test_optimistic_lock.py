"""Compare-and-set on field-data writes (H8.2 · S2-63).

The defect is a **silent lost update**: two enumerators edit the same
household, the second write lands on top of the first, and nothing records that
another version ever existed. It cannot even be found afterwards, because there
was no per-record version to compare.

The report frames this as extending a working geometry mechanism to three more
domains. There was no working mechanism: `calculations.geometry_version` is
incremented in twelve places and compared in none, and the client's
`reconcileVersion()` is reachable only from its own tests. So the test that
matters most here is `TestTheRace` -- a guard that passes both writers is the
thing this replaces, not an improvement on it.
"""
from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException

from app.services import optimistic_lock
from app.services.optimistic_lock import VersionConflict, check_and_bump, current_version
from app.services.optimistic_lock_guard import GUARDED_DOMAINS, LockNotTakenError


@pytest.fixture()
def owner(db):
    from app.models.user import User

    user = User(
        email=f"optlock-{uuid.uuid4().hex[:10]}@example.com",
        hashed_password="not-a-real-hash",
        full_name="Optimistic Lock Fixture",
    )
    db.add(user)
    db.flush()
    return user


@pytest.fixture()
def household(db, owner):
    from app.models.calculation import Calculation
    from app.models.household_information import HouseholdInformation

    calc = Calculation(user_id=owner.id, forest_name="Opt Lock CF")
    db.add(calc)
    db.flush()
    row = HouseholdInformation(
        calculation_id=calc.id,
        house_no=7000 + uuid.uuid4().int % 900,
        surname="Rimal",
        created_by=owner.id,
    )
    db.add(row)
    db.commit()
    return row


@pytest.fixture()
def inventory_calc(db, owner):
    from app.models.calculation import Calculation
    from app.models.inventory import InventoryCalculation

    # an inventory belongs to a forest (owner's rule, 2026-09-21; migration 092)
    forest = Calculation(user_id=owner.id, forest_name=f"OL {uuid.uuid4().hex[:6]}")
    db.add(forest)
    db.flush()
    row = InventoryCalculation(
        user_id=owner.id, uploaded_filename="optlock-probe.csv",
        needs_compartment_assignment=False, status="validated",
        calculation_id=forest.id,
    )
    db.add(row)
    db.commit()
    return row


class TestTakingTheRecord:
    def test_the_right_version_is_accepted_and_bumped(self, db, household):
        before = current_version(db, "household", household.id)
        after = check_and_bump(db, "household", household.id, before)
        assert after == before + 1
        assert current_version(db, "household", household.id) == before + 1

    def test_a_stale_version_is_refused(self, db, household):
        check_and_bump(db, "household", household.id, 0)  # someone else writes
        with pytest.raises(VersionConflict) as exc:
            check_and_bump(db, "household", household.id, 0)  # we were behind
        assert exc.value.status_code == 409

    def test_the_conflict_carries_both_versions(self, db, household):
        """The report is explicit: return both, so the app can PRESENT a
        conflict rather than discard one side.

        A bare 409 leaves a field device unable to show the enumerator what
        changed, which in practice means its retry loop discards a side anyway.
        """
        check_and_bump(db, "household", household.id, 0)
        with pytest.raises(VersionConflict) as exc:
            check_and_bump(db, "household", household.id, 0)
        detail = exc.value.detail
        assert detail["code"] == "VERSION_CONFLICT"
        assert detail["your_version"] == 0
        assert detail["current_version"] == 1
        # Not last-write-wins anywhere; household needs a person to decide.
        assert detail["resolution"] == "operator_resolved"

    def test_a_missing_row_is_404_not_409(self, db):
        """A client that deleted the record and one that lost a race need
        different answers."""
        with pytest.raises(HTTPException) as exc:
            check_and_bump(db, "household", uuid.uuid4(), 0)
        assert exc.value.status_code == 404


class TestTheRace:
    """The property the previous design could not have had.

    `SELECT`, compare in Python, then `UPDATE` is the exact defect H2.17
    removed from the Redis idempotency service: both writers read version 3,
    both pass the check, and both write. Here the comparison is in the WHERE
    clause, so the database decides once.
    """

    def test_only_one_of_two_writers_holding_the_same_version_wins(self, db, household):
        start = current_version(db, "household", household.id)
        first = check_and_bump(db, "household", household.id, start)
        with pytest.raises(VersionConflict):
            check_and_bump(db, "household", household.id, start)
        assert first == start + 1
        # The loser must not have moved it.
        assert current_version(db, "household", household.id) == start + 1

    def test_the_bump_is_relative_not_absolute(self, db, household):
        """`SET version = version + 1`, never `SET version = :n`.

        Writing an absolute value computed in Python reintroduces the race in
        the assignment even when the WHERE clause is right.
        """
        v = current_version(db, "household", household.id)
        for expected in range(v, v + 3):
            assert check_and_bump(db, "household", household.id, expected) == expected + 1


class TestWithoutAVersion:
    def test_the_write_proceeds_and_is_logged(self, db, household, caplog):
        """The web frontend sends no version today.

        Refusing would break the live application to protect a mobile client
        that does not exist yet -- the same call H2.17 made for
        `Idempotency-Key`. The omission is logged, not assumed away.
        """
        import logging

        before = current_version(db, "household", household.id)
        with caplog.at_level(logging.INFO, logger="app.services.optimistic_lock"):
            after = check_and_bump(db, "household", household.id, None)
        assert after == before + 1
        assert any("unguarded" in r.getMessage() for r in caplog.records)

    def test_required_turns_it_into_428(self, db, household):
        with pytest.raises(HTTPException) as exc:
            check_and_bump(db, "household", household.id, None, required=True)
        assert exc.value.status_code == 428
        assert exc.value.detail["code"] == "VERSION_REQUIRED"


class TestTheGuard:
    """G-SYNC-2. The lock is only a guard where somebody calls it.

    Every task in this phase found the same failure -- idempotency reaching 2
    of 194 routes, `correlation_id` never set, `geometry_audits` empty after
    five months, `geometry_version` never compared. So this does not check that
    the lock is called; it checks that a versioned row cannot be written
    without it.
    """

    def test_updating_a_versioned_row_without_the_lock_raises(self, db, household):
        household.surname = "Changed Without Taking The Lock"
        with pytest.raises(LockNotTakenError) as exc:
            db.flush()
        assert "household_information" in str(exc.value)
        assert "surname" in str(exc.value)
        db.rollback()

    def test_taking_the_lock_first_permits_the_write(self, db, household):
        check_and_bump(db, "household", household.id, None)
        household.surname = "Changed With The Lock"
        db.flush()          # must not raise
        db.commit()
        assert household.surname == "Changed With The Lock"

    def test_an_untouched_row_does_not_trip_it(self, db, household):
        """Loading a row and flushing must not look like a write."""
        _ = household.surname
        db.flush()

    def test_inserting_is_not_an_update(self, db, owner):
        from app.models.calculation import Calculation
        from app.models.household_information import HouseholdInformation

        calc = Calculation(user_id=owner.id, forest_name="Insert CF")
        db.add(calc)
        db.flush()
        db.add(HouseholdInformation(
            calculation_id=calc.id, house_no=8123, surname="New",
            created_by=owner.id,
        ))
        db.flush()          # a new record has no version to take
        db.rollback()


class TestTheInventoryDomainReportedBug:
    """`inventory` is a `GUARDED_DOMAINS` member (optimistic_lock_guard.py) that
    had zero call sites anywhere in the codebase -- reproduced here exactly as
    reported: accepting boundary corrections on a tree-inventory upload set
    `inventory.status = 'corrections_applied'` and committed without ever
    taking the lock, raising 'inventory_calculations <id> was updated without
    taking its version (changed: [\'status\'])' where a user expected the
    upload to just proceed. `InventoryService.process_inventory` /
    `process_inventory_simple` had the identical gap on their own
    'processing' / 'completed' transitions.
    """

    def test_updating_status_without_the_lock_raises_reproducing_the_reported_bug(
        self, db, inventory_calc
    ):
        inventory_calc.status = "corrections_applied"
        with pytest.raises(LockNotTakenError) as exc:
            db.flush()
        assert "inventory_calculations" in str(exc.value)
        assert "status" in str(exc.value)
        db.rollback()

    def test_check_and_bump_first_permits_the_corrections_status_write(
        self, db, inventory_calc
    ):
        """The `accept_corrections` fix: a real user decision takes the lock."""
        check_and_bump(db, "inventory", inventory_calc.id, None)
        inventory_calc.status = "corrections_applied"
        db.flush()          # must not raise
        db.commit()
        assert inventory_calc.status == "corrections_applied"

    def test_derived_write_first_permits_the_pipeline_status_write(
        self, db, inventory_calc
    ):
        """The `process_inventory` / `process_inventory_simple` fix: the
        service drives 'processing' -> 'completed' itself end-to-end, so it
        declares the write rather than bumping the version on every step."""
        optimistic_lock.record_derived_write(db, "inventory", inventory_calc.id, "pipeline_processing")
        inventory_calc.status = "processing"
        db.flush()          # must not raise
        db.commit()
        assert inventory_calc.status == "processing"


class TestTheGuardIsActuallyInstalled:
    """The guard installs itself when its module is imported -- so the only
    question that matters is whether anything imports it.

    It was written with `app.main` NOT importing it: the lazy import inside
    `check_and_bump` meant the guard came up only after the first lock call, so
    any unguarded write before that passed unnoticed. Worse, the check that
    "proved" it worked imported the module itself and was therefore circular.
    This test asks the question without answering it by accident.
    """

    def test_importing_the_app_registers_it(self):
        import subprocess
        import sys
        from pathlib import Path

        root = Path(__file__).resolve().parent.parent
        # A separate interpreter: this process already imported the guard, so
        # asking in-process would be the same circular check all over again.
        result = subprocess.run(
            [sys.executable, "-c",
             "import sys; sys.path.insert(0, r'%s');"
             "import app.main;"
             "print('app.services.optimistic_lock_guard' in sys.modules)" % root],
            capture_output=True, text=True, cwd=str(root),
        )
        assert result.stdout.strip().endswith("True"), (
            "app.main does not import optimistic_lock_guard, so G-SYNC-2 is not "
            "armed until the first check_and_bump call. stdout="
            + result.stdout + " stderr=" + result.stderr[-400:]
        )


class TestADerivedWrite:
    """Not every write to a versioned row is somebody's decision.

    Caching computed sample points onto the design that produced them is
    derived data. The guard inspects the row rather than the intent, so without
    a way to say so it would either refuse a legitimate cache write or have to
    be switched off -- and a guard switched off is what this whole phase keeps
    finding.
    """

    def test_it_does_not_bump_the_version(self, db, household):
        """The property that makes it different from taking the lock.

        Bumping here would give a client holding version 4 a 409 on its next
        write because somebody else merely VIEWED the record -- a conflict that
        did not happen.
        """
        before = current_version(db, "household", household.id)
        optimistic_lock.record_derived_write(db, "household", household.id, "cache")
        assert current_version(db, "household", household.id) == before

    def test_it_satisfies_the_guard(self, db, household):
        optimistic_lock.record_derived_write(db, "household", household.id, "cache")
        household.surname = "Derived"
        db.flush()          # must not raise
        db.rollback()

    def test_it_rejects_an_unknown_domain(self, db):
        with pytest.raises(KeyError):
            optimistic_lock.record_derived_write(db, "nope", uuid.uuid4(), "cache")


class TestTheRegistryIsHonest:
    def test_geometry_is_lockable_but_not_guarded(self):
        """A documented limit, not an oversight.

        `geometry_version` lives on `calculations`, a row that also carries
        status, lifecycle, boundary and export state, all updated by paths with
        nothing to do with geometry. The guard inspects the row rather than the
        intent, so guarding that table would fire on a status transition.
        """
        assert "geometry" in optimistic_lock.DOMAINS
        assert "geometry" not in GUARDED_DOMAINS

    def test_every_guarded_domain_is_a_known_domain(self):
        for domain in GUARDED_DOMAINS:
            assert domain in optimistic_lock.DOMAINS

    def test_an_unknown_domain_is_a_programming_error(self, db):
        with pytest.raises(KeyError):
            check_and_bump(db, "not-a-domain", uuid.uuid4(), 0)


class TestThroughTheApi:
    """The endpoint is wired, not just the service.

    Every other finding in this phase was a sound mechanism that nothing
    called, so proving `check_and_bump` works in isolation proves the wrong
    thing on its own.
    """

    def test_a_stale_put_answers_409_with_both_versions(self, client, auth_headers, db):
        from app.models.calculation import Calculation
        from app.models.household_information import HouseholdInformation
        from app.models.user import User

        # The calculation must belong to the authenticated user, or the
        # endpoint answers 403 before it ever reaches the lock.
        me = db.query(User).filter(User.email == "testuser@example.com").first()
        assert me is not None, "conftest's auth_headers user is missing"

        calc = Calculation(user_id=me.id, forest_name="API Opt Lock")
        db.add(calc)
        db.flush()
        row = HouseholdInformation(
            calculation_id=calc.id, house_no=8500, surname="Api",
            created_by=me.id,
        )
        db.add(row)
        db.commit()

        first = client.put(
            f"/api/v1/household/households/{row.id}",
            json={"surname": "First", "version": 0},
            headers=auth_headers,
        )
        assert first.status_code == 200, first.text
        assert first.json()["version"] == 1

        # Second writer still holding version 0.
        stale = client.put(
            f"/api/v1/household/households/{row.id}",
            json={"surname": "Second", "version": 0},
            headers=auth_headers,
        )
        assert stale.status_code == 409, stale.text
        detail = stale.json()["detail"]
        assert detail["code"] == "VERSION_CONFLICT"
        assert detail["your_version"] == 0
        assert detail["current_version"] == 1
        assert detail["resolution"] == "operator_resolved"

    def test_a_put_without_a_version_still_works(self, client, auth_headers, db):
        """The web frontend sends none, and must keep working."""
        from app.models.calculation import Calculation
        from app.models.household_information import HouseholdInformation
        from app.models.user import User

        me = db.query(User).filter(User.email == "testuser@example.com").first()
        calc = Calculation(user_id=me.id, forest_name="API No Version")
        db.add(calc)
        db.flush()
        row = HouseholdInformation(
            calculation_id=calc.id, house_no=8600, surname="NoVer",
            created_by=me.id,
        )
        db.add(row)
        db.commit()

        response = client.put(
            f"/api/v1/household/households/{row.id}",
            json={"surname": "Updated"},
            headers=auth_headers,
        )
        assert response.status_code == 200, response.text
        assert response.json()["surname"] == "Updated"
