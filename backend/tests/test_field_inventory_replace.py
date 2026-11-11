"""An inventory can be deleted and replaced (owner rule 2026-10-10): what was derived from it goes with it, what the user did stays."""
from __future__ import annotations

import uuid

from app.models.biodiversity import BiodiversitySpecies, CalculationBiodiversity
from app.models.calculation import Calculation
from app.models.field_inventory import FieldInventoryCalculation
from app.services.biodiversity_inventory_import import SYNC_MARKER


def _owner(client, db, prefix):
    from app.models.user import User

    email = f"{prefix}-{uuid.uuid4().hex[:10]}@example.com"
    client.post("/api/auth/register", json={"email": email, "password": "TestPass123!", "full_name": "FI Tester"})
    resp = client.post("/api/auth/login", json={"email": email, "password": "TestPass123!"})
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}, db.query(User).filter(User.email == email).first()


def _species(db, sci):
    sp = BiodiversitySpecies(category="vegetation", sub_category="Tree", nepali_name=sci, english_name=sci, scientific_name=sci)
    db.add(sp)
    db.flush()
    return sp


def test_deleting_an_inventory_clears_what_it_derived_and_keeps_what_the_user_did(client, db):
    headers, user = _owner(client, db, "fireplace")
    calc = Calculation(
        user_id=user.id, forest_name=f"Replace CF {uuid.uuid4().hex[:6]}",
        result_data={SYNC_MARKER: {"completed_at": "x"}, "sfm": {"blocks": [{"block_name": "A"}]}, "keep": 1},
    )
    db.add(calc)
    db.flush()
    fi = FieldInventoryCalculation(
        user_id=user.id, calculation_id=calc.id, uploaded_filename="inv.csv", status="completed", column_mapping={},
    )
    db.add(fi)
    auto, manual = _species(db, f"Auto {uuid.uuid4().hex[:6]}"), _species(db, f"Manual {uuid.uuid4().hex[:6]}")
    db.add_all([
        CalculationBiodiversity(calculation_id=calc.id, species_id=auto.id, presence_status="present",
                                notes="From field inventory: 74 stems in 38 of 48 sample plots."),
        CalculationBiodiversity(calculation_id=calc.id, species_id=manual.id, presence_status="present", notes="seen near the stream"),
    ])
    db.commit()

    resp = client.delete(f"/api/field-inventory/{fi.id}", headers=headers)
    assert resp.status_code == 200, resp.text

    db.expire_all()
    left = {b.species_id for b in db.query(CalculationBiodiversity).filter(CalculationBiodiversity.calculation_id == calc.id)}
    assert left == {manual.id}  # the auto-listed species went; the hand-recorded one stayed
    rd = db.get(Calculation, calc.id).result_data
    assert SYNC_MARKER not in rd and "sfm" not in rd  # the replacement inventory lists its own species and rebuilds SFM
    assert rd["keep"] == 1  # nothing else on the calculation is touched
    assert db.query(FieldInventoryCalculation).filter(FieldInventoryCalculation.calculation_id == calc.id).count() == 0
