"""NTFP field records of a forest: the form to take out, the upload to bring back, and what is stored (NTFP inventory, phase 3).

The form and its checks are ``ntfp_form`` (pure). This module joins them to the stored design and writes the result. An upload is all or
nothing: any error in the file and nothing is written. A row replaces the stored record of its (plot, species); a pair the file does not
mention is left alone.
"""
from __future__ import annotations

import io
import logging
from datetime import date
from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.calculation import Calculation
from app.models.ntfp_method import NtfpMethodProfile, NtfpObservation, NtfpSamplePlot, NtfpSamplingDesign, NtfpWeightSample
from app.services import ntfp_design_service as design_svc
from app.services import ntfp_form as form
from app.services.ntfp_design_service import DesignError

logger = logging.getLogger(__name__)


def _profile_dicts(db: Session, keys: List[str]) -> List[Dict[str, Any]]:
    out = []
    for r in db.query(NtfpMethodProfile).filter(NtfpMethodProfile.species_key.in_(keys)).all():
        out.append({
            "species_key": r.species_key, "nepali_name": r.nepali_name, "scientific_name": r.scientific_name, "part_ne": r.part_ne,
            "part_groups": r.part_groups or [], "sampling_method": r.sampling_method, "maturity_ne": r.maturity_ne,
            "n_individuals_min": r.n_individuals_min, "n_individuals_max": r.n_individuals_max,
            "harvest_fraction_pct": float(r.harvest_fraction_pct) if r.harvest_fraction_pct is not None else None,
            "conversion_factor": float(r.conversion_factor) if r.conversion_factor is not None else None, "procedure_en": r.procedure_en,
        })
    return out


def form_bytes(db: Session, calc: Calculation) -> bytes:
    design = design_svc.load(db, calc.id)
    if design is None:
        raise DesignError("no_design", "Lay out the sample plots first: the form is made from the design.")
    keys = [s["species_key"] for s in design["species"]]
    return form.build_workbook(design, _profile_dicts(db, keys), calc.forest_name or "")


def _plots(db: Session, calc_id: UUID) -> Dict[int, NtfpSamplePlot]:
    return {p.plot_number: p for p in db.query(NtfpSamplePlot).join(NtfpSamplingDesign, NtfpSamplePlot.design_id == NtfpSamplingDesign.id)
            .filter(NtfpSamplingDesign.calculation_id == calc_id).all()}


def import_form(db: Session, calc: Calculation, user_id, data: bytes, today: Optional[date] = None) -> Dict[str, Any]:
    """Check and store an uploaded form. Returns ``{ok, findings, observations_written, weights_written}``; nothing is written unless ok."""
    plots = _plots(db, calc.id)
    if not plots:
        raise DesignError("no_design", "There is no design for this forest.")
    assigned = {(n, key): True for n, p in plots.items() for key in (p.species_keys or [])}
    existing = {}
    for obs in db.query(NtfpObservation).filter(NtfpObservation.plot_id.in_([p.id for p in plots.values()])).all():
        existing[(next(n for n, p in plots.items() if p.id == obs.plot_id), obs.species_key)] = obs.count_total
    keys = sorted({k for _, k in assigned})
    parts = {p["species_key"]: p["part_groups"] for p in _profile_dicts(db, keys)}
    _require_mode(db, calc.id, "upload")
    result = form.read_workbook(data, assigned, existing, parts, today)
    if not result["ok"]:
        return {"ok": False, "findings": result["findings"], "observations_written": 0, "weights_written": 0}
    return _store(db, plots, user_id, result, "upload")


def entry_mode(db: Session, calc_id: UUID) -> Optional[str]:
    """``upload`` or ``manual`` once the forest has records (they are all one way, see ``_require_mode``); ``None`` while it has none."""
    ids = [p.id for p in _plots(db, calc_id).values()]
    if not ids:
        return None
    row = db.query(NtfpObservation.source).filter(NtfpObservation.plot_id.in_(ids)).first()
    return row[0] if row else None


def _require_mode(db: Session, calc_id: UUID, wanted: str) -> None:
    """Records come either from the uploaded form or from entry on the map, never both (owner, 2026-10-22): delete the records to change the way."""
    have = entry_mode(db, calc_id)
    if have is not None and have != wanted:
        way = {"upload": "uploaded from the form", "manual": "entered on the map"}
        raise DesignError("mode_conflict", f"This forest's records were {way[have]}. Delete the records first to {'upload the form' if wanted == 'upload' else 'enter them on the map'}.")


def _store(db: Session, plots: Dict[int, NtfpSamplePlot], user_id, result: Dict[str, Any], source: str, reset_weights: Optional[set] = None) -> Dict[str, Any]:
    """Write checked observations and weights. ``reset_weights``: (plot, species) pairs whose weights are replaced even if the new list is empty."""
    by_pair: Dict[tuple, NtfpObservation] = {}
    for o in result["observations"]:
        plot = plots[o["plot_number"]]
        row = db.query(NtfpObservation).filter(NtfpObservation.plot_id == plot.id, NtfpObservation.species_key == o["species_key"]).first()
        if row is None:
            row = NtfpObservation(plot_id=plot.id, species_key=o["species_key"], entered_by=user_id, count_total=o["count_total"])
            db.add(row)
        row.visit_date = date.fromisoformat(o["visit_date"]) if o["visit_date"] else None
        row.count_total, row.count_mature, row.count_small = o["count_total"], o["count_mature"], o["count_small"]
        row.clumps, row.tillers, row.notes, row.entered_by = o["clumps"], o["tillers"], o["notes"], user_id
        row.source = source
        db.flush()
        by_pair[(o["plot_number"], o["species_key"])] = row
        if row.count_total == 0:  # nothing there: no weights can stand
            db.query(NtfpWeightSample).filter(NtfpWeightSample.observation_id == row.id).delete()

    pairs_with_weights = {(w["plot_number"], w["species_key"]) for w in result["weights"]} | (reset_weights or set())
    for pair in pairs_with_weights:
        row = by_pair.get(pair)
        if row is None:  # a weight for a count stored earlier
            plot = plots[pair[0]]
            row = db.query(NtfpObservation).filter(NtfpObservation.plot_id == plot.id, NtfpObservation.species_key == pair[1]).first()
        db.query(NtfpWeightSample).filter(NtfpWeightSample.observation_id == row.id).delete()
        by_pair[pair] = row
    db.flush()
    for w in result["weights"]:
        db.add(NtfpWeightSample(observation_id=by_pair[(w["plot_number"], w["species_key"])].id, sample_no=w["sample_no"], part_group=w["part_group"],
                                fresh_weight_g=w["fresh_weight_g"], dry_weight_g=w["dry_weight_g"], notes=w["notes"]))
    db.flush()
    return {"ok": True, "findings": result["findings"], "observations_written": len(result["observations"]), "weights_written": len(result["weights"])}


def save_plot(db: Session, calc: Calculation, user_id, plot_number: int, entries: List[Dict[str, Any]], today: Optional[date] = None) -> Dict[str, Any]:
    """Save what was found in ONE plot, typed in on the map. ``entries``: ``[{species_key, visit_date, count_total, count_mature, count_small, clumps, tillers, notes,
    weights: [{sample_no, part_group, fresh_weight_g, dry_weight_g, notes}]}]``. The same checks as the form (the entries are made into a form and read by it); an entry with
    nothing filled in clears that species' record of the plot. All or nothing: any error and nothing is written."""
    plots = _plots(db, calc.id)
    plot = plots.get(plot_number)
    if plot is None:
        raise DesignError("unknown_plot", f"Plot {plot_number} is not in the design.")
    _require_mode(db, calc.id, "manual")
    allowed = set(plot.species_keys or [])
    findings: List[Dict[str, Any]] = []
    seen: set = set()
    keep: List[Dict[str, Any]] = []
    clear: List[str] = []
    for e in entries:
        key = str(e.get("species_key") or "").strip()
        if key not in allowed:
            findings.append({"severity": "error", "sheet": "Plots", "row": None, "column": "species_key", "code": "pair.unknown", "message": f"Plot {plot_number} does not carry '{key}'.", "species_key": key})
        elif key in seen:
            findings.append({"severity": "error", "sheet": "Plots", "row": None, "column": "species_key", "code": "pair.duplicate", "message": f"'{key}' appears twice.", "species_key": key})
        else:
            seen.add(key)
            empty = all(e.get(k) in (None, "") for k in ("visit_date", "count_total", "count_mature", "count_small", "clumps", "tillers", "notes")) and not e.get("weights")
            if empty:
                clear.append(key)
            else:
                keep.append(e)
    if findings:
        return {"ok": False, "findings": findings, "observations_written": 0, "weights_written": 0, "cleared": 0}

    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = form.PLOTS
    ws.append(["plot_number", "species_key"] + form.PLOT_ENTRY)
    for e in keep:
        ws.append([plot_number, e["species_key"]] + [e.get(k) for k in form.PLOT_ENTRY])
    wt = wb.create_sheet(form.WEIGHTS)
    wt.append(form.WEIGHT_COLS)
    weight_species: List[str] = []
    for e in keep:
        for w in e.get("weights") or []:
            wt.append([plot_number, e["species_key"], w.get("sample_no"), w.get("part_group"), w.get("fresh_weight_g"), w.get("dry_weight_g"), w.get("notes")])
            weight_species.append(e["species_key"])
    buf = io.BytesIO()
    wb.save(buf)
    parts = {p["species_key"]: p["part_groups"] for p in _profile_dicts(db, sorted(allowed))}
    assigned = {(plot_number, k): True for k in allowed}
    existing = {}
    for obs in db.query(NtfpObservation).filter(NtfpObservation.plot_id == plot.id).all():
        existing[(plot_number, obs.species_key)] = obs.count_total
    result = form.read_workbook(buf.getvalue(), assigned, existing, parts, today)
    for f in result["findings"]:   # say which species the fabricated sheet's row belongs to
        r = f.get("row")
        if r and f["sheet"] == form.PLOTS and r - 2 < len(keep):
            f["species_key"] = keep[r - 2]["species_key"]
        elif r and f["sheet"] == form.WEIGHTS and r - 2 < len(weight_species):
            f["species_key"] = weight_species[r - 2]
    if not result["ok"]:
        return {"ok": False, "findings": result["findings"], "observations_written": 0, "weights_written": 0, "cleared": 0}
    out = _store(db, plots, user_id, result, "manual", reset_weights={(plot_number, e["species_key"]) for e in keep})
    cleared = 0
    for key in clear:
        cleared += db.query(NtfpObservation).filter(NtfpObservation.plot_id == plot.id, NtfpObservation.species_key == key).delete()
    db.flush()
    return {**out, "cleared": cleared}


def list_records(db: Session, calc_id: UUID) -> Dict[str, Any]:
    plots = _plots(db, calc_id)
    by_id = {p.id: n for n, p in plots.items()}
    out: List[Dict[str, Any]] = []
    if by_id:
        for o in (db.query(NtfpObservation).filter(NtfpObservation.plot_id.in_(list(by_id))).all()):
            out.append({
                "plot_number": by_id[o.plot_id], "species_key": o.species_key, "visit_date": o.visit_date.isoformat() if o.visit_date else None,
                "count_total": o.count_total, "count_mature": o.count_mature, "count_small": o.count_small, "clumps": o.clumps, "tillers": o.tillers,
                "notes": o.notes, "source": o.source,
                "weights": [{"sample_no": w.sample_no, "part_group": w.part_group, "fresh_weight_g": float(w.fresh_weight_g),
                             "dry_weight_g": float(w.dry_weight_g) if w.dry_weight_g is not None else None, "notes": w.notes}
                            for w in sorted(o.weights, key=lambda w: w.sample_no)],
            })
    out.sort(key=lambda r: (r["plot_number"], r["species_key"]))
    pairs = sum(len(p.species_keys or []) for p in plots.values())
    return {"observations": out, "mode": out[0]["source"] if out else None, "pairs_assigned": pairs, "pairs_recorded": len(out),
            "weights": sum(len(o["weights"]) for o in out)}


def plot_points(db: Session, calc_id: UUID) -> List[Dict[str, Any]]:
    """``[{plot_number, lon, lat, status_group}]``: where each sample plot lies and how far its findings are (the print map and the workspace layer).

    ``status_group`` is "Recorded" (every species of the plot has a record), "Partly recorded" or "Not visited"; it reads stored rows only.
    """
    plots = _plots(db, calc_id)
    if not plots:
        return []
    by_id = {p.id: n for n, p in plots.items()}
    recorded: Dict[int, int] = {}
    for (plot_id,) in db.query(NtfpObservation.plot_id).filter(NtfpObservation.plot_id.in_(list(by_id))).all():
        recorded[by_id[plot_id]] = recorded.get(by_id[plot_id], 0) + 1
    from geoalchemy2.shape import to_shape

    out: List[Dict[str, Any]] = []
    for number, p in sorted(plots.items()):
        done, wanted = recorded.get(number, 0), len(p.species_keys or [])
        group = "Not visited" if done == 0 else "Recorded" if done >= wanted else "Partly recorded"
        pt = to_shape(p.location)
        out.append({"plot_number": number, "lon": pt.x, "lat": pt.y, "status_group": group})
    return out


def delete_records(db: Session, calc_id: UUID) -> int:
    ids = [p.id for p in _plots(db, calc_id).values()]
    if not ids:
        return 0
    n = 0
    for o in db.query(NtfpObservation).filter(NtfpObservation.plot_id.in_(ids)).all():
        db.delete(o)
        n += 1
    return n
