"""A method card with its sources: read for the page, and the expert review that confirms or corrects it (NTFP inventory, owner requirement 2026-10-22).

``card`` groups every sourced value of a species by fact (field and part): the chosen value, and the other sources' values beside it, flagged when they disagree.
``apply_review`` is how a reviewer's answers enter: each becomes a new value from a review source (the most authoritative tier), status ``expert_confirmed``, chosen;
the card's profile row is updated to match and its ``card_status`` becomes ``expert_confirmed``.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, Iterable, List, Optional, Tuple

from sqlalchemy.orm import Session

from app.models.ntfp_method import NtfpMethodProfile, NtfpMethodValue, NtfpSource
from app.core.ntfp_sources import FIELDS, STATUSES

_STATUS_RANK = {"expert_confirmed": 0, "documented": 1, "derived": 2, "provisional": 3}


def _num(x) -> Optional[float]:
    return None if x is None else float(x)


def _value_dict(v: NtfpMethodValue, src: Optional[NtfpSource]) -> Dict[str, Any]:
    return {
        "id": str(v.id), "value_num": _num(v.value_num), "value_num2": _num(v.value_num2), "value_text": v.value_text, "unit": v.unit, "calendar": v.calendar,
        "source_key": v.source_key, "source_title": src.title if src else None, "source_year": src.year if src else None, "source_url": src.url if src else None,
        "source_tier": src.tier if src else None, "locator": v.locator, "status": v.status, "chosen": v.chosen, "note": v.note,
        "reviewed_by": v.reviewed_by, "reviewed_at": v.reviewed_at.isoformat() if v.reviewed_at else None,
    }


def _same(a: Dict[str, Any], b: Dict[str, Any]) -> bool:
    return (a["value_num"], a["value_num2"], (a["value_text"] or "").strip()) == (b["value_num"], b["value_num2"], (b["value_text"] or "").strip())


def card(db: Session, species_key: str) -> Optional[Dict[str, Any]]:
    """The profile and every sourced value, by fact; ``None`` when the species is unknown."""
    prof = db.query(NtfpMethodProfile).filter(NtfpMethodProfile.species_key == species_key).first()
    if prof is None:
        return None
    sources = {s.key: s for s in db.query(NtfpSource).all()}
    rows = db.query(NtfpMethodValue).filter(NtfpMethodValue.species_key == species_key).all()
    groups: Dict[Tuple[str, Optional[str]], List[Dict[str, Any]]] = {}
    for v in rows:
        groups.setdefault((v.field, v.part_group), []).append(_value_dict(v, sources.get(v.source_key)))
    facts = []
    order = {f: i for i, f in enumerate(FIELDS)}
    for (field, part), vals in sorted(groups.items(), key=lambda kv: (order.get(kv[0][0], 99), kv[0][1] or "")):
        vals.sort(key=lambda d: (not d["chosen"], _STATUS_RANK[d["status"]], d["source_tier"] or 9))
        chosen = vals[0] if vals[0]["chosen"] else None
        others = vals[1:] if chosen else vals
        facts.append({"field": field, "part_group": part, "chosen": chosen, "others": others, "conflict": bool(chosen) and any(not _same(chosen, o) for o in others)})
    return {
        "species_key": prof.species_key, "nepali_name": prof.nepali_name, "scientific_name": prof.scientific_name, "aliases": prof.aliases or [], "card_status": prof.card_status,
        "has_method_card": prof.has_method_card, "growth_class": prof.growth_class, "part_groups": prof.part_groups or [], "facts": facts,
        "sources": {k: {"title": s.title, "publisher": s.publisher, "year": s.year, "url": s.url, "tier": s.tier, "read_status": s.read_status, "licence": s.licence}
                    for k, s in sources.items() if any(f["chosen"] and f["chosen"]["source_key"] == k or any(o["source_key"] == k for o in f["others"]) for f in facts)},
    }


def sources(db: Session) -> List[Dict[str, Any]]:
    return [{"key": s.key, "title": s.title, "publisher": s.publisher, "year": s.year, "url": s.url, "tier": s.tier, "read_status": s.read_status, "licence": s.licence, "note": s.note}
            for s in db.query(NtfpSource).order_by(NtfpSource.tier, NtfpSource.key).all()]


def chosen_by_species(db: Session, fields: Iterable[str]) -> Dict[str, List[Dict[str, Any]]]:
    """``{species_key: [chosen value dicts]}`` for the given fields: what the species list shows beside each species (the annual allowable harvest, the season)."""
    srcs = {s.key: s for s in db.query(NtfpSource).all()}
    out: Dict[str, List[Dict[str, Any]]] = {}
    for v in db.query(NtfpMethodValue).filter(NtfpMethodValue.chosen.is_(True), NtfpMethodValue.field.in_(list(fields))).all():
        if ":" in v.species_key:
            continue
        out.setdefault(v.species_key, []).append({"field": v.field, "part_group": v.part_group, **_value_dict(v, srcs.get(v.source_key))})
    return out


def aah_for(db: Session, pairs: Iterable[Tuple[str, str]]) -> Dict[Tuple[str, str], Dict[str, Any]]:
    """The chosen annual allowable harvest of each (species_key, part_group): ``{pct_min, pct_max, source_key, locator, status, note}``."""
    pairs = list(pairs)
    keys = {k for k, _ in pairs}
    if not keys:
        return {}
    srcs = {s.key: s for s in db.query(NtfpSource).all()}
    out: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for v in db.query(NtfpMethodValue).filter(NtfpMethodValue.chosen.is_(True), NtfpMethodValue.field == "aah_pct", NtfpMethodValue.species_key.in_(keys)).all():
        if (v.species_key, v.part_group) in pairs:
            out[(v.species_key, v.part_group)] = {
                "pct_min": _num(v.value_num), "pct_max": _num(v.value_num2) if v.value_num2 is not None else _num(v.value_num), "source_key": v.source_key,
                "source_title": srcs[v.source_key].title if v.source_key in srcs else None, "locator": v.locator, "status": v.status, "note": v.note,
            }
    return out


# ── expert review ────────────────────────────────────────────────────────────────────────────────────────────────────────────

class ReviewError(ValueError):
    pass


_REVIEW_FIELDS = {  # review-sheet column -> (field, which number)
    "growth_class": ("growth_class", "text"), "sampling_method": ("sampling_method", "text"), "maturity": ("maturity", "text"), "procedure": ("procedure", "text"),
    "plot_min_sqm": ("plot_area_sqm", "num"), "plot_max_sqm": ("plot_area_sqm", "num2"), "n_individuals_min": ("n_individuals", "num"), "n_individuals_max": ("n_individuals", "num2"),
    "conversion_factor": ("conversion_factor", "num"), "sample_fraction_pct": ("sample_fraction_pct", "num"), "aah_pct_min": ("aah_pct", "num"), "aah_pct_max": ("aah_pct", "num2"),
}
_GROWTH = {"tree", "shrub", "climber", "herb", "fungus", "lichen"}
_METHODS = {"destructive", "semi_destructive", "non_destructive"}


def _review_source(db: Session, reviewer: str, when: datetime) -> NtfpSource:
    key = f"REVIEW-{when:%Y%m%d}-{re.sub(r'[^A-Za-z0-9]+', '', reviewer)[:20] or 'x'}"
    src = db.get(NtfpSource, key)
    if src is None:
        src = NtfpSource(key=key, title=f"Expert review by {reviewer}", publisher=reviewer, year=f"{when:%Y-%m-%d}", url=None, tier=0, read_status="read", licence="-",
                         note="A named reviewer confirmed or corrected the card.")
        db.add(src)
        db.flush()
    return src


def apply_review(db: Session, rows: List[Dict[str, Any]], reviewer: str, when: Optional[datetime] = None) -> Dict[str, Any]:
    """Apply the reviewer's answers. ``rows``: ``[{species_key, confirmed: bool, <review column>: value, ...}]``. A row with ``confirmed`` true and no edits confirms the card as
    it stands; any edited column becomes a new expert-confirmed value (the old value stays as history). Returns ``{cards_confirmed, values_written, skipped: [reasons]}``.
    Nothing is written if any row is invalid (``ReviewError``)."""
    if not reviewer.strip():
        raise ReviewError("The reviewer's name is required.")
    when = when or datetime.now(timezone.utc)
    prepared: List[Tuple[NtfpMethodProfile, Dict[str, Any], bool]] = []
    for r in rows:
        key = str(r.get("species_key") or "").strip()
        prof = db.query(NtfpMethodProfile).filter(NtfpMethodProfile.species_key == key).first()
        if prof is None:
            raise ReviewError(f"Unknown species: {key!r}.")
        edits = {c: r[c] for c in _REVIEW_FIELDS if r.get(c) not in (None, "")}
        confirmed = str(r.get("confirmed", "")).strip().lower() in ("yes", "y", "true", "1")
        if "growth_class" in edits and edits["growth_class"] not in _GROWTH:
            raise ReviewError(f"{key}: growth class must be one of {sorted(_GROWTH)}.")
        if "sampling_method" in edits and edits["sampling_method"] not in _METHODS:
            raise ReviewError(f"{key}: sampling method must be one of {sorted(_METHODS)}.")
        for c in edits:
            if _REVIEW_FIELDS[c][1] in ("num", "num2"):
                try:
                    edits[c] = float(edits[c])
                except (TypeError, ValueError):
                    raise ReviewError(f"{key}: {c} must be a number.") from None
                if edits[c] < 0:
                    raise ReviewError(f"{key}: {c} must be 0 or more.")
        lo, hi = edits.get("plot_min_sqm"), edits.get("plot_max_sqm")
        if lo is not None and hi is not None and lo > hi:
            raise ReviewError(f"{key}: the plot size minimum is above the maximum.")
        prepared.append((prof, edits, confirmed))

    src = _review_source(db, reviewer, when)
    written, confirmed_cards, skipped = 0, 0, []
    for prof, edits, confirmed in prepared:
        if not edits and not confirmed:
            skipped.append(f"{prof.species_key}: not confirmed and nothing changed")
            continue
        if confirmed and not edits:  # confirm the card as it stands: every chosen value becomes expert-confirmed
            for v in db.query(NtfpMethodValue).filter(NtfpMethodValue.species_key == prof.species_key, NtfpMethodValue.chosen.is_(True)).all():
                if v.status != "expert_confirmed":
                    v.status, v.reviewed_by, v.reviewed_at = "expert_confirmed", reviewer, when
                    written += 1
        else:
            by_field: Dict[str, Dict[str, Any]] = {}
            for col, val in edits.items():
                field, slot = _REVIEW_FIELDS[col]
                by_field.setdefault(field, {})[slot] = val
            for field, slots in by_field.items():
                part = None
                if field == "aah_pct":
                    part = (prof.part_groups or [None])[0]
                prev = (db.query(NtfpMethodValue).filter(NtfpMethodValue.species_key == prof.species_key, NtfpMethodValue.field == field,
                                                         NtfpMethodValue.chosen.is_(True), NtfpMethodValue.part_group.is_(part) if part is None else NtfpMethodValue.part_group == part).first())
                if prev is not None:
                    prev.chosen = False
                    db.flush()
                db.add(NtfpMethodValue(species_key=prof.species_key, field=field, part_group=part, value_num=slots.get("num", prev.value_num if prev else None),
                                       value_num2=slots.get("num2", prev.value_num2 if prev else None), value_text=slots.get("text", prev.value_text if prev else None),
                                       unit=prev.unit if prev else None, source_key=src.key, locator="review sheet", status="expert_confirmed", chosen=True,
                                       note="entered by the reviewer", reviewed_by=reviewer, reviewed_at=when))
                written += 1
                _apply_to_profile(prof, field, slots)
        prof.card_status = "expert_confirmed"
        prof.has_method_card = True
        confirmed_cards += 1
    db.flush()
    return {"cards_confirmed": confirmed_cards, "values_written": written, "skipped": skipped}


def _apply_to_profile(prof: NtfpMethodProfile, field: str, slots: Dict[str, Any]) -> None:
    """Keep the profile row (what the design reads) in step with the reviewed value."""
    if field == "growth_class":
        prof.growth_class = slots["text"]
    elif field == "sampling_method":
        prof.sampling_method = slots["text"]
    elif field == "maturity":
        prof.maturity_ne = slots["text"]
    elif field == "procedure":
        prof.procedure_en = slots["text"]
    elif field == "plot_area_sqm":
        if "num" in slots:
            prof.plot_min_sqm = Decimal(str(slots["num"]))
        if "num2" in slots:
            prof.plot_max_sqm = Decimal(str(slots["num2"]))
        if prof.plot_max_sqm is None:
            prof.plot_max_sqm = prof.plot_min_sqm
        if prof.plot_min_sqm is None:
            prof.plot_min_sqm = prof.plot_max_sqm
    elif field == "n_individuals":
        if "num" in slots:
            prof.n_individuals_min = int(slots["num"])
        if "num2" in slots:
            prof.n_individuals_max = int(slots["num2"])
    elif field == "conversion_factor":
        prof.conversion_factor = Decimal(str(slots["num"]))
    elif field == "sample_fraction_pct":
        prof.harvest_fraction_pct = Decimal(str(slots["num"]))


def review_queue(db: Session) -> List[Dict[str, Any]]:
    """The cards still waiting for a reviewer (provisional), the least certain growth class first, with the numbers the review form edits."""
    profiles = db.query(NtfpMethodProfile).filter(NtfpMethodProfile.has_method_card.is_(True), NtfpMethodProfile.card_status == "provisional").all()
    chosen = {(v.species_key, v.field): v for v in db.query(NtfpMethodValue).filter(NtfpMethodValue.chosen.is_(True)).all()}
    out = []
    for p in profiles:
        how = chosen.get((p.species_key, "growth_class"))
        aah = next((v for (k, f), v in chosen.items() if k == p.species_key and f == "aah_pct"), None)
        out.append({
            "species_key": p.species_key, "nepali_name": p.nepali_name, "scientific_name": p.scientific_name, "part_ne": p.part_ne, "part_groups": p.part_groups or [],
            "growth_class": p.growth_class, "growth_how": (how.note if how else None) or "", "growth_guessed": bool(how and how.status == "provisional"),
            "sampling_method": p.sampling_method, "plot_min_sqm": _num(p.plot_min_sqm), "plot_max_sqm": _num(p.plot_max_sqm),
            "n_individuals_min": p.n_individuals_min, "n_individuals_max": p.n_individuals_max, "maturity": p.maturity_ne, "conversion_factor": _num(p.conversion_factor),
            "sample_fraction_pct": _num(p.harvest_fraction_pct), "aah_pct_min": _num(aah.value_num) if aah else None, "aah_pct_max": _num(aah.value_num2) if aah else None,
            "aah_source_key": aah.source_key if aah else None,
        })
    out.sort(key=lambda c: (not c["growth_guessed"], c["species_key"]))
    return out
