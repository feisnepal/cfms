"""One community-forest code (owner request 2026-10-11): ``cf_code`` and ``cf_national_code`` were the same thing, so there is one --
the national database code of Schedule 11 of the Community Forestry Guidelines 2081 (``PPP/DDD/SS/LL/NNN``)."""
from __future__ import annotations

import uuid

from docx import Document

from app.models.calculation import Calculation
from app.models.forest_metadata import ForestMetadata
from app.models.operational_plan import OperationalPlan
from app.services.operational_plan.variable_registry import VARIABLE_REGISTRY
from app.services.operational_plan.variable_resolver import VariableResolver
from app.services.report.document_builder import build_cover_page


def _text(doc) -> str:
    parts = [p.text for p in doc.paragraphs]
    for table in doc.tables:
        for row in table.rows:
            parts.extend(cell.text for cell in row.cells)
    return "\n".join(parts)


def test_the_cover_page_prints_the_code_once():
    doc = Document()
    build_cover_page(doc, {"cf_national_code": "KOS/TAP/AB/01/007", "forest_name": "F"})
    text = _text(doc)
    assert text.count("KOS/TAP/AB/01/007") == 1
    assert "CF National Database Code" in text
    assert "CF Code" not in text.replace("CF National Database Code", "")


def test_the_model_has_no_second_code_column():
    assert not hasattr(ForestMetadata, "cf_code")
    assert hasattr(ForestMetadata, "cf_national_code")


def _plan(db, user_id, forest_metadata_code=None, typed=None):
    from app.models.user import User  # noqa: F401  (the user row must exist for the calculation's FK)

    calc = Calculation(user_id=user_id, forest_name=f"CF code {uuid.uuid4().hex[:6]}")
    db.add(calc)
    db.flush()
    if forest_metadata_code is not None:
        db.add(ForestMetadata(calculation_id=calc.id, forest_name="F", cf_national_code=forest_metadata_code))
    plan = OperationalPlan(calculation_id=calc.id, forest_name=calc.forest_name,
                           plan_metadata={"user_inputs": {"cf_code": typed}} if typed else {})
    db.add(plan)
    db.commit()
    return calc, plan


def _user(client, db):
    from app.models.user import User

    email = f"cfcode-{uuid.uuid4().hex[:10]}@example.com"
    client.post("/api/auth/register", json={"email": email, "password": "TestPass123!", "full_name": "CF Tester"})
    return db.query(User).filter(User.email == email).first()


def test_the_document_variable_follows_the_saved_forest_code(client, db):
    user = _user(client, db)
    calc, plan = _plan(db, user.id, forest_metadata_code="KOS/TAP/AB/01/007", typed="OLD/TYPED/1")
    resolver = VariableResolver(db, calc.id, plan)
    assert resolver._resolve_user_input(VARIABLE_REGISTRY["cf_code"]) == "KOS/TAP/AB/01/007"  # the forest's code wins


def test_the_document_variable_falls_back_to_what_the_plan_holds(client, db):
    user = _user(client, db)
    calc, plan = _plan(db, user.id, forest_metadata_code=None, typed="MAK/PH/42/33")
    resolver = VariableResolver(db, calc.id, plan)
    assert resolver._resolve_user_input(VARIABLE_REGISTRY["cf_code"]) == "MAK/PH/42/33"
