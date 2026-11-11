"""The forest-wide summary behind the workspace's Forest summary panel: eight headline tiles, five themes, a verdict.

Every number is read from the OP data (``data_collector.collect_all_op_data``'s dict), so the panel can never disagree with
the OP document. Nothing here computes anything: a number the OP data does not hold is a tile in state ``not_computed``
(with the workflow step that produces it), never a guess. Figures are the OP's own per-hectare values; they are not
re-multiplied into totals here, because the OP weights them over production units only.

Landslide classes are RELATIVE (``lsi_class_method == 'quantile'``): the wording says so and nothing here judges a share as
high or low. Mean growing stock is stated as a number, with no good/bad judgement, because the SFM code has no forest-wide
stock threshold.
"""
from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

from app.utils.number_format import localize_digits

READY = "ready"
NOT_COMPUTED = "not_computed"
FOREST_ONLY = "forest_only"  # the OP holds this figure for the whole forest only, not for the user group
NO_DATA = "no_data"

FOREST = "forest"
USER_GROUP = "user_group"

CO2_PER_C = 3.67  # same ratio as core.constants.IPCC_CO2R


def _num(value: Any) -> Optional[float]:
    try:
        if value is None or isinstance(value, bool):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _tile(key: str, value: Optional[float], unit: str, state: str, source_map: Optional[str] = None,
          source_step: Optional[int] = None, **extra: Any) -> Dict[str, Any]:
    tile = {"key": key, "value": value if state == READY else None, "unit": unit, "state": state,
            "source_map": source_map, "source_step": source_step}
    tile.update(extra)
    return tile


def _ready_or(key, value, unit, missing_step, source_map=None, **extra):
    return _tile(key, value, unit, READY if value is not None else NOT_COMPUTED, source_map, missing_step, **extra)


# ---- readers over the OP data ---------------------------------------------------------------------------------------

def _fi(op: Dict[str, Any]) -> Dict[str, Any]:
    fi = op.get("field_inventory") or {}
    return fi if fi.get("available") else {}


def _forest_area_ha(op: Dict[str, Any]) -> Optional[float]:
    sqm = _num((op.get("basic_info") or {}).get("total_area_sqm"))
    return round(sqm / 10000.0, 2) if sqm else None


def _grand_aah_per_ha(fi: Dict[str, Any]) -> Optional[float]:
    for row in fi.get("fi_aah_table") or []:
        if str(row.get("block_name", "")).startswith("Grand Total"):
            return _num(row.get("total_aah_m3_per_ha"))
    return None


def condition_shares(op: Dict[str, Any], unit_areas: Optional[Dict[str, float]]) -> Optional[Dict[str, Any]]:
    """Area shares (%) of Good / Moderate / Weak, joining the inventory's per-unit condition to each unit's area by name.

    ``unit_areas`` (unit name -> hectares) comes from the ``forest_blocks`` table, never from the legacy ``result_data`` unit
    snapshots, which go stale (the "result_data units stale trap")."""
    fi = _fi(op)
    summaries = fi.get("fi_block_summaries") or []
    areas = {name: a for name, a in (unit_areas or {}).items() if name and a}
    totals = {"Good": 0.0, "Moderate": 0.0, "Weak": 0.0}
    weak_units: List[str] = []
    for row in summaries:
        cond = row.get("forest_condition")
        area = areas.get(row.get("block_name"))
        if cond in totals and area:
            totals[cond] += area
            if cond == "Weak":
                weak_units.append(str(row.get("block_name")))
    whole = sum(totals.values())
    if not whole:
        return None
    return {"good": round(100 * totals["Good"] / whole, 1), "moderate": round(100 * totals["Moderate"] / whole, 1),
            "weak": round(100 * totals["Weak"] / whole, 1), "weak_units": weak_units}


def _hazard(op: Dict[str, Any]) -> Dict[str, Any]:
    hv = op.get("hazard_vuln") or {}
    return hv if hv.get("hazard_vuln_available", True) and hv.get("lsi_prone_area_pct") is not None else {}


def _soil(op: Dict[str, Any], area: str) -> Optional[float]:
    se = op.get("soil_erosion") or {}
    if not se.get("soil_loss_available"):
        return None
    return _num(se.get("soil_loss_ug_mean_t_ha" if area == USER_GROUP else "soil_loss_mean_t_ha"))


# ---- the summary ------------------------------------------------------------------------------------------------------

def build_summary(
    op: Dict[str, Any],
    households: Optional[Dict[str, Any]],
    area: str = FOREST,
    unit_areas: Optional[Dict[str, float]] = None,
) -> Dict[str, Any]:
    """Tiles, themes and the verdict inputs for one forest, from its OP data, the household aggregate and the units' areas
    (``unit_areas``: name -> hectares of the forest's leaf units, from the ``forest_blocks`` table)."""
    fi = _fi(op)
    forest_only = area == USER_GROUP
    shares = condition_shares(op, unit_areas)
    hz = _hazard(op)
    relative = (hz.get("lsi_class_method") or "quantile") == "quantile"

    if area == USER_GROUP:
        ug_area = _num((op.get("user_group") or {}).get("user_group_area_ha"))
        area_tile = _ready_or("area", ug_area or None, "ha", 2, "user_group", unit_count=None)
    else:
        area_tile = _ready_or("area", _forest_area_ha(op), "ha", 1, None, unit_count=len(unit_areas) if unit_areas else None)

    def forest_figure(key, value, unit, step, source_map=None):
        if forest_only:
            return _tile(key, None, unit, FOREST_ONLY, source_map, step)
        return _ready_or(key, value, unit, step, source_map)

    gs = _num(fi.get("fi_growing_stock_m3_per_ha")) if fi else None
    carbon = _num(fi.get("fi_carbon_stock_tc_per_ha")) if fi else None
    tiles = [
        area_tile,
        forest_figure("growing_stock", gs, "m3/ha", 5, "fi_growing_stock"),
        forest_figure("carbon", carbon, "tC/ha", 5, "fi_carbon"),
        forest_figure("co2e", round(carbon * CO2_PER_C, 2) if carbon is not None else None, "tCO2e/ha", 5, "fi_co2"),
        forest_figure("aah", _grand_aah_per_ha(fi) if fi else None, "m3/ha/yr", 5, "fi_aah"),
        forest_figure("condition_good", shares["good"] if shares else None, "%", 5, "fi_condition"),
        (_tile("landslide_high", None, "%", FOREST_ONLY, "hazard_prone", 11) if forest_only else
         _ready_or("landslide_high", _num(hz.get("lsi_prone_area_pct")), "%", 11, "hazard_prone", relative=relative)),
        _ready_or("species", _num((op.get("species") or {}).get("species_count")) or None, "species", 6),
    ]

    soil = _soil(op, area)
    hh_total = _num((households or {}).get("total_households"))
    themes = [
        {"key": "stock", "headline": "growing_stock",
         "rows": [t for t in tiles if t["key"] in ("growing_stock", "carbon", "co2e", "aah")]},
        {"key": "health", "headline": "condition_good",
         "rows": [forest_figure("condition_good", shares["good"] if shares else None, "%", 5, "fi_condition"),
                  forest_figure("condition_moderate", shares["moderate"] if shares else None, "%", 5, "fi_condition"),
                  forest_figure("condition_weak", shares["weak"] if shares else None, "%", 5, "fi_condition")]},
        {"key": "biodiversity", "headline": "species", "rows": [t for t in tiles if t["key"] == "species"]},
        {"key": "hazard", "headline": "landslide_high",
         "rows": [_ready_or("soil_loss", soil, "t/ha/yr", 11, "hazard_soil"),
                  next(t for t in tiles if t["key"] == "landslide_high"),
                  (_tile("priority_households", None, "households", FOREST_ONLY, "hazard_settle", 11) if forest_only else
                   _ready_or("priority_households", _num(hz.get("hh_priority_count")) if hz else None, "households", 11,
                             "hazard_settle", of=_num(hz.get("hh_count")) if hz else None))]},
        {"key": "people", "headline": "households",
         "rows": [_ready_or("households", hh_total, "households", 2)]},
    ]

    return {
        "area": area,
        "tiles": tiles,
        "themes": themes,
        "verdict_inputs": {
            "good": shares["good"] if shares else None, "moderate": shares["moderate"] if shares else None,
            "weak": shares["weak"] if shares else None, "weak_units": shares["weak_units"] if shares else [],
            "stock": gs if not forest_only else None,
            "landslide_pct": _num(hz.get("lsi_prone_area_pct")) if hz and not forest_only else None,
            "landslide_relative": relative,
        },
        "basis": {"field_inventory": bool(fi), "hazard": bool(hz), "hazard_method": hz.get("lsi_class_method") if hz else None},
    }


# ---- the verdict ------------------------------------------------------------------------------------------------------

Translate = Callable[..., Optional[str]]


def _fmt(value: float, lang: str = "en") -> str:
    """A number as the panel writes it: whole when it is whole, one decimal otherwise, in the language's own digits."""
    text = f"{value:.0f}" if abs(value - round(value)) < 0.05 else f"{value:.1f}"
    return localize_digits(text, lang)


def build_verdict(inputs: Dict[str, Any], translate: Translate, lang: str = "en") -> str:
    """One sentence per available fact, from translation keys, in the caller's language.

    ``translate(key, **params)`` returns the wording with ``{{placeholders}}`` filled, or ``None`` when the key is unknown.
    A fact that is not computed contributes no clause. No clause judges a number against a threshold.
    """
    clauses: List[str] = []

    def add(key: str, **params: Any) -> None:
        text = translate(key, **params)
        if text:
            clauses.append(text)

    if inputs.get("good") is not None:
        add("forestSummary.verdict.condition", good=_fmt(inputs["good"], lang), moderate=_fmt(inputs["moderate"], lang),
            weak=_fmt(inputs["weak"], lang))
        if inputs.get("weak_units"):
            add("forestSummary.verdict.weak_units", units=", ".join(inputs["weak_units"]))
    if inputs.get("stock") is not None:
        add("forestSummary.verdict.stock", stock=_fmt(inputs["stock"], lang))
    if inputs.get("landslide_pct") is not None:
        add("forestSummary.verdict.landslide_relative" if inputs.get("landslide_relative")
            else "forestSummary.verdict.landslide_fixed", pct=_fmt(inputs["landslide_pct"], lang))
    if not clauses:
        add("forestSummary.verdict.empty")
    return " ".join(clauses)


# ---- plain-text export ------------------------------------------------------------------------------------------------

def _value_text(tile: Dict[str, Any], translate: Translate, lang: str = "en") -> str:
    state = tile.get("state")
    if state == READY and tile.get("value") is not None:
        text = f"{_fmt(tile['value'], lang)} {_unit_text(tile['unit'], translate)}"
        if tile.get("of") is not None:
            text += f" / {_fmt(tile['of'], lang)}"
        return text
    if state == FOREST_ONLY:
        return translate("forestSummary.export.forestOnly") or "forest only"
    step = tile.get("source_step")
    base = translate("forestSummary.notComputed") or "not computed"
    return f"{base} ({translate('forestSummary.step') or 'step'} {localize_digits(step, lang)})" if step is not None else base


# The tile's unit as the server sends it -> the translation key of its written form (forestSummary.units.<key>).
_UNIT_KEY = {"ha": "ha", "m3/ha": "m3_ha", "tC/ha": "tc_ha", "tCO2e/ha": "tco2e_ha", "m3/ha/yr": "m3_ha_yr", "t/ha/yr": "t_ha_yr",
             "species": "species", "households": "households", "%": "pct"}


def _unit_text(unit: str, translate: Translate) -> str:
    """The unit in the reader's language (Nepali: हे., घन मि./हे.; English: ha, m³/ha); the raw unit if it has no translation."""
    key = _UNIT_KEY.get(unit)
    return (translate(f"forestSummary.units.{key}") if key else None) or unit


def _tile_label(tile: Dict[str, Any], translate: Translate) -> str:
    key = tile["key"]
    for prefix in ("forestSummary.tiles.", "forestSummary.rows."):
        text = translate(prefix + key)
        if text:
            return text
    return key


def export_text(
    summary: Dict[str, Any],
    decisions: Optional[Dict[str, Any]],
    translate: Translate,
    *,
    forest_name: str,
    date: str,
    lang: str = "en",
) -> str:
    """The summary as plain text for a reader outside the workspace (ministry, NGO). Same figures, verdict and wording as the
    panel: it is rendered from the same ``summary`` dict, through the same translation keys. Never computes anything."""
    scope = translate("forestSummary.areaUserGroup" if summary["area"] == USER_GROUP else "forestSummary.areaForest") or summary["area"]
    out: List[str] = [
        translate("forestSummary.export.title", forest=forest_name) or f"FOREST SUMMARY - {forest_name}",
        translate("forestSummary.export.scope", scope=scope) or f"Area: {scope}",
        translate("forestSummary.export.date", date=localize_digits(date, lang)) or f"Date: {localize_digits(date, lang)}",
        "",
        (translate("forestSummary.export.sectionSummary") or "SUMMARY"),
        summary.get("verdict") or "",
        "",
        (translate("forestSummary.export.sectionNumbers") or "HEADLINE NUMBERS"),
    ]
    for tile in summary["tiles"]:
        extra = f" ({localize_digits(tile['unit_count'], lang)})" if tile["key"] == "area" and tile.get("unit_count") else ""
        out.append(f"{_tile_label(tile, translate)}: {_value_text(tile, translate, lang)}{extra}")
    out += ["", translate("forestSummary.export.sectionThemes") or "BY THEME"]
    for theme in summary["themes"]:
        parts = [f"{_tile_label(r, translate)} {_value_text(r, translate, lang)}" for r in theme["rows"]]
        out.append(f"{translate('forestSummary.themes.' + theme['key']) or theme['key']}: " + "; ".join(parts))
    if decisions is not None:
        out += ["", translate("forestSummary.export.sectionDecisions") or "DECISIONS"]
        for item in decisions["items"]:
            base = f"forestSummary.decisions.{item['key']}"
            params = {"block": item.get("block_name") or "", "suggested": item.get("suggested") or "", "current": item.get("current") or "-"}
            title = translate(f"{base}.title", **params) or item["key"]
            if item["state"] == "answered" and item.get("choice"):
                choice = translate(f"{base}.choice.{item['choice']}", **params) or item["choice"]
                if item["choice"] == "custom" and item.get("note"):
                    choice += f" ({item['note']})"
                who = item.get("decided_by") or {}
                stamp = translate(
                    "forestSummary.decisions.decidedBy", name=who.get("name", ""),
                    kind=translate(f"forestSummary.decisions.kind.{who.get('kind', 'user')}") or "",
                    date=localize_digits((item.get("decided_at") or "")[:10], lang),
                )
                out.append(f"{title}: {choice} - {stamp}")
            else:
                out.append(f"{title}: {translate('forestSummary.decisions.open') or 'open'}")
    out += ["", translate("forestSummary.export.sectionBasis") or "BASIS"]
    basis = summary.get("basis") or {}
    if basis.get("collected_at"):
        out.append(translate("forestSummary.export.collected", date=localize_digits(str(basis["collected_at"])[:10], lang)) or localize_digits(str(basis["collected_at"])[:10], lang))
    if basis.get("hazard_method") == "quantile":
        out.append(translate("forestSummary.relativeNote") or "")
    return "\n".join(out) + "\n"
