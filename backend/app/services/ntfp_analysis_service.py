"""NTFP inventory results of a forest: the stored design and records run through ``ntfp_analysis`` (NTFP inventory, phase 4).

Read-only. Nothing is stored: the figures are recomputed from the records every time, so a corrected count or weight shows at once and no copy can
go stale. The price rate of each part is attached from ``core/ntfp_price`` (Schedule-7, or a labelled estimate) for the plan to use; no money is
computed here.
"""
from __future__ import annotations

from typing import Any, Dict, List
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.ntfp_price import prices_for
from app.models.calculation import Calculation
from app.models.ntfp_method import NtfpMethodProfile
from app.services import ntfp_analysis as analysis
from app.services import ntfp_design_service as design_svc
from app.services import ntfp_records_service as records_svc
from app.services.ntfp_design_service import DesignError


def results(db: Session, calc: Calculation) -> Dict[str, Any]:
    design = design_svc.load(db, calc.id)
    if design is None:
        raise DesignError("no_design", "Lay out the sample plots first.")
    rec = records_svc.list_records(db, calc.id)
    keys = [s["species_key"] for s in design["species"]]
    profiles = {p.species_key: p for p in db.query(NtfpMethodProfile).filter(NtfpMethodProfile.species_key.in_(keys)).all()}
    references = {k: {"conversion_factor": float(p.conversion_factor) if p.conversion_factor is not None else None,
                      "harvest_fraction_pct": float(p.harvest_fraction_pct) if p.harvest_fraction_pct is not None else None,
                      "part_groups": p.part_groups or []} for k, p in profiles.items()}
    areas = {s["name"]: float(s["area_ha"]) for s in design["strata"]}
    observations: List[Dict[str, Any]] = []
    weights: List[Dict[str, Any]] = []
    for o in rec["observations"]:
        observations.append({"plot_number": o["plot_number"], "species_key": o["species_key"], "count_total": o["count_total"]})
        for w in o["weights"]:
            weights.append({"plot_number": o["plot_number"], "species_key": o["species_key"], **{k: w[k] for k in ("part_group", "fresh_weight_g", "dry_weight_g")}})
    out = analysis.analyse(areas, design["plots"], design["species"], observations, weights, references)
    for row in out["species"]:
        p = profiles.get(row["species_key"])
        row["nepali_name"] = p.nepali_name if p else row["label"]
        row["scientific_name"] = p.scientific_name if p else None
        for part in row["parts"]:
            if p is None or part["part_group"] is None:
                continue
            price = next((e for e in prices_for(p.species_key, p.scientific_name, p.regulation_name, [part["part_group"]], None)), None)
            if price:
                part["price"] = {"npr_per_unit": price["price"], "unit": price["unit"], "basis": price["basis"], "estimated": price["estimated"], "note": price["basis_note"]}
    out["survey"] = {"pairs_assigned": rec["pairs_assigned"], "pairs_recorded": rec["pairs_recorded"], "weights": rec["weights"]}
    return out
