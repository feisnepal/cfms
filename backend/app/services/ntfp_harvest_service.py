"""The annual harvest plan of a forest's NTFPs, and its two links: cost-benefit and the yearly plan (NTFP inventory, phase 5b).

The guideline gives no harvest rule. The owner types the annual quantity of each (species, part); the page offers a share-of-stock helper, nothing
here decides a share. Two things are read from it:

* cost-benefit: one benefit row per (species, part), quantity x unit price, every year of the plan (``cost_benefit/repopulate.py``, source_link
  ``ntfp:<species_key>:<part>``). The price is the owner's own when given, else the Schedule-7 rate or its labelled estimate (``core/ntfp_price``).
  Schedule-7 note 2: the rate is the same whether the herb is green or dry, so the basis of the quantity (fresh or dry) is the owner's explicit choice
  and is written into the row's description.
* the yearly plan: one collection line (the master list's "NTFP collection", kilograms) with the total kilograms a year, made once; an existing line
  is the owner's and is not overwritten.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.ntfp_price import prices_for
from app.models.calculation import Calculation
from app.models.ntfp_method import NtfpHarvestPlan, NtfpMethodProfile
from app.models.yearly_activities import PotentialActivity
from app.services import ntfp_analysis_service as analysis_svc
from app.services import yearly_plan_service as plan_svc
from app.services.ntfp_design_service import DesignError

COLLECTION_ACTIVITY_EN = "Non-timber forest product (NTFP) collection"
UNITS = ("kg", "piece")
BASES = ("fresh", "dry")


def _candidates(db: Session, calc: Calculation) -> List[Dict[str, Any]]:
    """Every (species, part) the survey has weights for: the rows a harvest can be planned on, with stock and rate."""
    results = analysis_svc.results(db, calc)
    out: List[Dict[str, Any]] = []
    for sp in results["species"]:
        for part in sp["parts"]:
            if part["part_group"] is None:
                continue
            price = part.get("price")
            out.append({
                "species_key": sp["species_key"], "nepali_name": sp["nepali_name"], "scientific_name": sp["scientific_name"], "part_group": part["part_group"],
                "stock_fresh_kg": part["stock_fresh_kg"], "stock_dry_kg": part["stock_dry_kg"], "yield_precision_pct": part["yield_precision_pct"],
                "price": price,
            })
    return out


def _rate(db: Session, species_key: str, part_group: str, override: Optional[Decimal]) -> Optional[Dict[str, Any]]:
    """The price a row is valued at: the owner's override, else the Schedule-7 rate or its estimate."""
    if override is not None:
        return {"npr_per_unit": float(override), "unit": "kg", "basis": "owner", "estimated": False, "note": "entered by the owner"}
    p = db.query(NtfpMethodProfile).filter(NtfpMethodProfile.species_key == species_key).first()
    if p is None:
        return None
    line = next(iter(prices_for(p.species_key, p.scientific_name, p.regulation_name, [part_group], None)), None)
    if line is None:
        return None
    return {"npr_per_unit": line["price"], "unit": line["unit"], "basis": line["basis"], "estimated": line["estimated"], "note": line["basis_note"]}


def list_plan(db: Session, calc: Calculation) -> Dict[str, Any]:
    """The rows of the plan page: each surveyed (species, part) with its stock, its rate and the owner's plan if any, plus the totals."""
    stored = {(r.species_key, r.part_group): r for r in db.query(NtfpHarvestPlan).filter(NtfpHarvestPlan.calculation_id == calc.id).all()}
    rows: List[Dict[str, Any]] = []
    seen = set()
    for c in _candidates(db, calc):
        key = (c["species_key"], c["part_group"])
        seen.add(key)
        rows.append(_row(db, c, stored.get(key)))
    for key, r in stored.items():  # a plan row whose survey rows are gone stays visible, so it can be removed
        if key not in seen:
            p = db.query(NtfpMethodProfile).filter(NtfpMethodProfile.species_key == key[0]).first()
            rows.append(_row(db, {"species_key": key[0], "nepali_name": p.nepali_name if p else key[0], "scientific_name": p.scientific_name if p else None,
                                  "part_group": key[1], "stock_fresh_kg": None, "stock_dry_kg": None, "yield_precision_pct": None, "price": None}, r))
    from app.services import ntfp_card_service as cards

    aah = cards.aah_for(db, [(r["species_key"], r["part_group"]) for r in rows])
    for r in rows:
        r["aah"] = aah.get((r["species_key"], r["part_group"]))
    planned = [r for r in rows if r["plan"]]
    return {
        "rows": rows,
        "totals": {
            "rows_planned": len(planned),
            "kg_per_year": round(sum(r["plan"]["annual_quantity"] for r in planned if r["plan"]["unit"] == "kg"), 2),
            "value_npr_per_year": round(sum(r["value_npr_per_year"] or 0 for r in planned), 2),
        },
    }


def _row(db: Session, c: Dict[str, Any], r: Optional[NtfpHarvestPlan]) -> Dict[str, Any]:
    plan = None
    value = None
    rate = c.get("price")
    if r is not None:
        plan = {"annual_quantity": float(r.annual_quantity), "unit": r.unit, "weight_basis": r.weight_basis,
                "price_override": float(r.price_override) if r.price_override is not None else None, "notes": r.notes}
        rate = _rate(db, r.species_key, r.part_group, r.price_override)
        if rate is not None:
            value = round(float(r.annual_quantity) * float(rate["npr_per_unit"]), 2)
    return {**c, "price": rate, "plan": plan, "value_npr_per_year": value}


def save_plan(db: Session, calc: Calculation, user_id, rows: List[Dict[str, Any]]) -> None:
    """Replace the plan with ``rows`` (``[{species_key, part_group, annual_quantity, unit?, weight_basis?, price_override?, notes?}]``).

    Refused (``DesignError``): a pair the survey has no weights for, a negative or absurd number, a repeated pair, and a quantity above the standing stock
    in the same basis (nobody harvests more in a year than is there). Nothing is written on a refusal. The caller commits."""
    cands = {(c["species_key"], c["part_group"]): c for c in _candidates(db, calc)}
    seen = set()
    clean: List[Dict[str, Any]] = []
    for r in rows:
        key = (str(r.get("species_key") or ""), str(r.get("part_group") or ""))
        if key in seen:
            raise DesignError("harvest.duplicate", f"{key[0]} / {key[1]} is listed twice.")
        seen.add(key)
        c = cands.get(key)
        if c is None:
            raise DesignError("harvest.unknown_row", f"{key[0]} / {key[1]} has no survey weights: a harvest can only be planned on a surveyed part.")
        qty = Decimal(str(r.get("annual_quantity", 0)))
        unit, basis = r.get("unit") or "kg", r.get("weight_basis") or "dry"
        if unit not in UNITS or basis not in BASES:
            raise DesignError("harvest.bad_value", "The unit is kg or piece; the basis is fresh or dry.")
        if qty < 0 or qty > Decimal("1e9"):
            raise DesignError("harvest.bad_value", f"The annual quantity of {c['nepali_name']} must be 0 or more.")
        po = r.get("price_override")
        po = None if po in (None, "") else Decimal(str(po))
        if po is not None and (po < 0 or po > Decimal("1e7")):
            raise DesignError("harvest.bad_value", f"The price of {c['nepali_name']} must be 0 or more.")
        stock = c["stock_dry_kg"] if basis == "dry" else c["stock_fresh_kg"]
        if unit == "kg" and stock is not None and float(qty) > float(stock):
            raise DesignError("harvest.exceeds_stock", f"{c['nepali_name']}: {qty} kg a year is more than the whole {basis} stock ({stock} kg).")
        if qty > 0:
            clean.append({"species_key": key[0], "part_group": key[1], "annual_quantity": qty, "unit": unit, "weight_basis": basis, "price_override": po,
                          "notes": (str(r["notes"]).strip()[:500] if r.get("notes") else None)})
    db.query(NtfpHarvestPlan).filter(NtfpHarvestPlan.calculation_id == calc.id).delete(synchronize_session=False)
    for r in clean:
        db.add(NtfpHarvestPlan(calculation_id=calc.id, updated_by=user_id, **r))
    db.flush()


def to_yearly_plan(db: Session, calc: Calculation) -> Dict[str, Any]:
    """Make the yearly plan's NTFP collection line, with the total kilograms a year, unless the owner already has one. The line is made with a
    budget of 0 (the cost of collecting is not known here); the plan's own health check then says it is missing."""
    plan = list_plan(db, calc)
    kg = plan["totals"]["kg_per_year"]
    if kg <= 0:
        raise DesignError("harvest.nothing_planned", "Plan an annual harvest in kilograms first.")
    master = db.query(PotentialActivity).filter(PotentialActivity.name_en == COLLECTION_ACTIVITY_EN).first()
    if master is None:
        raise DesignError("harvest.no_activity", "The master list has no NTFP collection activity.")
    line, created, _years = plan_svc.get_or_create_line(
        db, calc.id, master.id, numbers=plan_svc.PlanNumbers(quantity=Decimal(str(kg)), budget=Decimal(0)), years=list(plan_svc.PLAN_YEARS))
    return {"created": created, "line_id": str(line.id), "quantity": float(line.default_quantity), "kg_planned": kg, "activity": master.activities}


def benefit_rows(db: Session, calc_id: UUID) -> List[Dict[str, Any]]:
    """The cost-benefit benefit rows of the harvest plan: ``[{source_link, description, quantity, unit_price}]`` (every year of the plan)."""
    from app.models.ntfp_method import NtfpMethodProfile as P

    out: List[Dict[str, Any]] = []
    for r in db.query(NtfpHarvestPlan).filter(NtfpHarvestPlan.calculation_id == calc_id).all():
        rate = _rate(db, r.species_key, r.part_group, r.price_override)
        if rate is None or float(rate["npr_per_unit"]) <= 0 or float(r.annual_quantity) <= 0:
            continue
        p = db.query(P).filter(P.species_key == r.species_key).first()
        name = (p.nepali_name if p else None) or r.species_key
        basis_ne = "सुक्खा" if r.weight_basis == "dry" else "ताजा"
        note = " (अनुमानित दर)" if rate["estimated"] else ""
        out.append({
            "source_link": f"ntfp:{r.species_key}:{r.part_group}",
            "description": f"गैरकाष्ठ वन पैदावार: {name} ({basis_ne} तौल){note}",
            "quantity": float(r.annual_quantity), "unit_price": float(rate["npr_per_unit"]),
        })
    return out
