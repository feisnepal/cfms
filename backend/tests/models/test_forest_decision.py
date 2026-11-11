"""FP-1 gate: migration ``116_add_forest_decisions`` / ``ForestDecision``.

One answer per (forest, question, scope), a forest-wide answer (scope NULL) is unique too, deleting the forest
deletes its answers, and deleting the user who answered keeps the answer.
"""
import uuid

import pytest
from sqlalchemy.exc import IntegrityError

from app.models.calculation import Calculation
from app.models.forest_decision import ForestDecision
from app.models.user import User, UserRole


def _user(db):
    user = User(email=f"fp1{uuid.uuid4().hex[:8]}@test.com", full_name="FP-1 Tester", role=UserRole.USER,
                hashed_password="not-a-real-hash")
    db.add(user)
    db.flush()
    return user


def _calc(db, user):
    calc = Calculation(id=str(uuid.uuid4()), user_id=user.id, uploaded_filename="fp1.csv", is_draft=False,
                       structure_locked=False)
    db.add(calc)
    db.flush()
    return calc


def _decision(calc, user, key="landslide_method", scope=None, choice="relative"):
    return ForestDecision(calculation_id=calc.id, key=key, scope=scope, choice=choice, decided_by=user.id)


def test_round_trip_sets_decided_at(db):
    user = _user(db)
    calc = _calc(db, user)
    row = _decision(calc, user)
    db.add(row)
    db.flush()
    db.refresh(row)
    assert row.id is not None and row.decided_at is not None and row.note is None


def test_forest_wide_answer_is_unique_per_key(db):
    user = _user(db)
    calc = _calc(db, user)
    db.add(_decision(calc, user))
    db.flush()
    db.add(_decision(calc, user, choice="needs_calibration"))
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()


def test_same_key_may_have_one_answer_per_scope(db):
    user = _user(db)
    calc = _calc(db, user)
    db.add_all([_decision(calc, user, key="orientation", scope="b1", choice="accept_suggested"),
                _decision(calc, user, key="orientation", scope="b2", choice="custom")])
    db.flush()
    db.add(_decision(calc, user, key="orientation", scope="b1", choice="custom"))
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()


def test_deleting_the_forest_deletes_its_answers(db):
    user = _user(db)
    calc = _calc(db, user)
    db.add(_decision(calc, user))
    db.flush()
    db.delete(calc)
    db.flush()
    assert db.query(ForestDecision).filter(ForestDecision.calculation_id == calc.id).count() == 0
    db.rollback()


def test_deleting_the_user_keeps_the_answer(db):
    owner = _user(db)
    dfo = _user(db)
    calc = _calc(db, owner)
    row = _decision(calc, dfo)
    db.add(row)
    db.flush()
    db.execute(User.__table__.delete().where(User.id == dfo.id))
    db.expire_all()
    kept = db.query(ForestDecision).filter(ForestDecision.id == row.id).one()
    assert kept.decided_by is None
    db.rollback()
