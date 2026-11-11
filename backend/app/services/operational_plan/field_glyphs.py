"""Field-inventory chart glyphs for the workspace: one small chart per unit, drawn over the map.

Each chart stands for a print map variable (its PLACEHOLDER) in ``CHARTS``. The numbers, the class order and the COLOURS come from
the very functions the print map uses (``thematic_overlay._load_unit_values`` / ``_composition`` / ``_glyph_point``) and from
the same user-colour overlay (``_with_user_colours``), so the workspace chart, the page thumbnail and the Operational Plan
figure cannot drift apart. The browser only draws what it is given (stacked bar, pie, waffle, sparkline, ternary dot, radar).

The headline chart is "where is the timber?" — timber m³/ha by tree size class. A class a forest does not have simply does not
appear: any class may be empty in any forest. Count-based charts are served as the print placeholders define them (note that
seedlings outnumber trees by orders of magnitude, so a pie of stem COUNTS is dominated by regeneration).
"""
from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

logger = logging.getLogger(__name__)

# slug (the URL) -> workspace id, print spec key, how the browser draws it
CHARTS: dict[str, dict[str, str]] = {
    "timber-by-size": {"id": "chart_timber", "spec": "unit__dbh_class_stock__stackbar", "kind": "stackbar"},
    "dbh-stems": {"id": "chart_dbh_stems", "spec": "unit__dbh_class_count__stackbar", "kind": "stackbar"},
    "dbh-gs-mai-aah": {"id": "chart_dbh_gs_mai_aah", "spec": "unit__dbh_gs_mai_aah__stackbar", "kind": "triplebar"},
    "dbh-pie": {"id": "chart_dbh_pie", "spec": "unit__dbh_class_count__pie", "kind": "pie"},
    "reverse-j": {"id": "chart_reverse_j", "spec": "unit__dbh_class_count__sparkline", "kind": "sparkline"},
    "dbh-waffle": {"id": "chart_dbh_waffle", "spec": "unit__dbh_composition__waffle", "kind": "waffle"},
    "regen-pole-tree": {"id": "chart_regen_pole_tree", "spec": "unit__regen_pole_tree__ternary", "kind": "ternary"},
    "health-radar": {"id": "chart_health", "spec": "unit__health_fingerprint", "kind": "radar"},
    "timber-firewood": {"id": "chart_timber_firewood", "spec": "unit__timber_firewood__stackbar", "kind": "stackbar"},
    "biomass-split": {"id": "chart_biomass", "spec": "unit__agb_bgb__stackbar", "kind": "stackbar"},
    "species-pie": {"id": "chart_species", "spec": "unit__species_composition__pie", "kind": "pie"},
}
KINDS = tuple(CHARTS)
SPEC_KEY = CHARTS["timber-by-size"]["spec"]  # the headline chart (kept for callers / tests)

# classes whose lower bound is 40 cm or more (the harvest-eligible trees)
GE40_KEYS = ("40_50", "50_60", "60_plus")

LABELS_EN = {
    "0_4": "Regeneration (0–4 cm)",
    "4_10": "Sapling (4–10 cm)",
    "10_20": "Small pole (10–20 cm)",
    "20_30": "Large pole (20–30 cm)",
    "30_40": "Small tree (30–40 cm)",
    "40_50": "Medium tree (40–50 cm)",
    "50_60": "Large tree (50–60 cm)",
    "60_plus": "Very large tree (60+ cm)",
}
# components of the chart specs that are not DBH classes
COMP_EN = {
    "regeneration_per_ha": "Regeneration", "pole_per_ha": "Poles", "tree_per_ha": "Trees",
    "_timber_total": "Timber", "_firewood_total": "Firewood",
    "agb_t_per_ha": "Above-ground", "bgb_t_per_ha": "Below-ground",
}
COMP_NE = {
    "regeneration_per_ha": "पुनरुत्पादन", "pole_per_ha": "खाँवा", "tree_per_ha": "रूख",
    "_timber_total": "काठ", "_firewood_total": "दाउरा",
    "agb_t_per_ha": "माथिल्लो (भूमिमाथि)", "bgb_t_per_ha": "तल्लो (भूमिमुनि)",
}
RADAR_AXES_EN = {
    "forest_condition": "Forest condition", "regeneration_condition": "Regeneration condition", "mai_percent": "MAI %",
    "basal_area_m2_per_ha": "Basal area", "carbon_stock_tc_per_ha": "Carbon",
}
RADAR_AXES_NE = {
    "forest_condition": "वन अवस्था", "regeneration_condition": "पुनरुत्पादन अवस्था", "mai_percent": "MAI %",
    "basal_area_m2_per_ha": "आधार क्षेत्र", "carbon_stock_tc_per_ha": "कार्बन",
}


def _n(v: float) -> str:
    return f"{v:,.0f}" if abs(v) >= 100 else f"{v:.1f}".rstrip("0").rstrip(".")


def _texts(slug: str, total: float, segs: list[dict], ge40_pct: float | None) -> tuple[str, str]:
    """The compact label at two zoom levels: (short, long). Server-side so every chart says the same thing everywhere."""
    if slug == "timber-by-size":
        return _n(total), f"{_n(total)} m³/ha" + (f" · {ge40_pct:.0f}% ≥40" if ge40_pct is not None else "")
    if slug == "dbh-stems":
        return _n(total), f"{_n(total)} stems/ha"
    if slug in ("dbh-pie", "dbh-waffle", "reverse-j"):
        return "", f"{_n(total)} stems/ha"
    if slug == "regen-pole-tree":
        shares = " · ".join(f"{100 * s['value'] / total:.0f}" for s in segs) if total > 0 else ""
        return "", f"{shares} %" if shares else ""
    if slug == "timber-firewood":
        timber = next((s["value"] for s in segs if s["key"] == "_timber_total"), 0.0)
        return _n(total), f"{_n(total)} m³/ha" + (f" · {100 * timber / total:.0f}% timber" if total > 0 else "")
    if slug == "biomass-split":
        bgb = next((s["value"] for s in segs if s["key"] == "bgb_t_per_ha"), 0.0)
        return _n(total), f"{_n(total)} t/ha" + (f" · {100 * bgb / total:.0f}% below" if total > 0 else "")
    return "", ""


def _radar_fractions(values: dict, axes: list[str], spec: Any) -> dict[str, list[float]]:
    """Each axis scaled 0..1 over ALL units — the same rule as the print map's radar."""
    from app.services.operational_plan import thematic_overlay as to

    rank = to._COND_RANK

    def val(rec: dict, a: str):
        v = rec.get(a)
        return rank.get(str(v)) if v in rank else (float(v) if to._is_num(v) else None)

    span = {}
    for a in axes:
        real = [x for x in (val(r, a) for r in values.values()) if x is not None]
        span[a] = (min(real) if real else 0.0, max(real) if real else 1.0)
    out: dict[str, list[float]] = {}
    for name, rec in values.items():
        row = []
        for a in axes:
            x = val(rec, a)
            lo, hi = span[a]
            row.append(0.0 if x is None or hi <= lo else max(0.0, min(1.0, (x - lo) / (hi - lo))))
        out[name] = row
    return out


def _build_species(units: list[dict], values: dict, spec: Any, slug: str) -> dict[str, Any]:
    """Species composition per unit: each unit's top five species by share of volume, the rest as "other". The classes are the
    forest's OWN species (not a fixed list), so a saved colour is keyed by the species key, not by a position."""
    from app.services.operational_plan import thematic_overlay as to

    own = spec.colour_overrides or {}
    classes = {c["key"]: c for c in to._species_classes(values)}
    out_units: list[dict] = []
    seen: set[str] = set()
    for u in units:
        name = u.get("name") or ""
        rec = values.get(name)
        geom = u.get("geometry")
        if not rec or geom is None or geom.is_empty:
            continue
        lon, lat = to._glyph_point(geom)
        segs: list[dict] = []
        other = 0.0
        for i, sh in enumerate(rec.get("species_shares") or []):
            c = classes.get(sh["key"])
            if i < 5 and c:
                segs.append({"index": len(segs), "key": sh["key"], "label_ne": sh["name"], "label_en": sh["name"],
                             "value": round(float(sh["value"]), 2), "color": own.get(sh["key"]) or c["color"]})
                seen.add(sh["key"])
            else:
                other += float(sh["value"])
        if other > 0:
            segs.append({"index": len(segs), "key": to.OTHER_SPECIES_KEY, "label_ne": to.OTHER_SPECIES_LABEL_NE, "label_en": "Other species",
                         "value": round(other, 2), "color": own.get(to.OTHER_SPECIES_KEY) or to.OTHER_SPECIES_COLOUR})
            seen.add(to.OTHER_SPECIES_KEY)
        top = segs[0] if segs else None
        out_units.append({
            "name": name, "anchor": [round(lon, 6), round(lat, 6)], "plots": int(rec.get("total_sample_plots") or 0),
            "segments": segs, "total": 100.0 if segs else 0.0, "total_m3_per_ha": 0.0, "ge40_pct": None,
            "text_short": "", "text_long": f"{top['label_en']} {top['value']:.0f}%" if top else "",
        })
    if not out_units:
        return {"state": "no_data", "kind": slug}
    legend = [{"index": i, "key": c["key"], "override_key": c["key"], "label_ne": c["name"], "label_en": c["name"], "color": own.get(c["key"]) or c["color"]}
              for i, c in enumerate(classes.values()) if c["key"] in seen]
    if to.OTHER_SPECIES_KEY in seen:
        legend.append({"index": len(legend), "key": to.OTHER_SPECIES_KEY, "override_key": to.OTHER_SPECIES_KEY, "label_ne": to.OTHER_SPECIES_LABEL_NE,
                       "label_en": "Other species", "color": own.get(to.OTHER_SPECIES_KEY) or to.OTHER_SPECIES_COLOUR})
    return {"state": "ready", "kind": slug, "shape": "pie", "id": CHARTS[slug]["id"], "token": f"thememap:{CHARTS[slug]['spec']}",
            "editable": True, "custom_colours": bool(own), "max_total": 100.0, "units": out_units, "legend": legend}


def _triple_bars(rec: dict, segs: list[dict]) -> list[dict]:
    """GS, MAI and AAH as three bars over the same classes. The field inventory holds MAI and AAH per BLOCK (growing stock x MAI %,
    then x AAH %), so each class gets its share of them in proportion to its own stock; the bars say so in the hover."""
    gs = sum(s["value"] for s in segs)
    block_gs = float(rec.get("total_growing_stock_m3_per_ha") or 0)
    mai_f = float(rec.get("mai_total_m3_per_ha") or 0) / block_gs if block_gs > 0 else 0.0
    aah_f = float(rec.get("aah_total_m3_per_ha") or 0) / block_gs if block_gs > 0 else 0.0
    out = []
    for key, factor in (("gs", 1.0), ("mai", mai_f), ("aah", aah_f)):
        sg = [{**s, "value": round(s["value"] * factor, 3)} for s in segs]
        out.append({"key": key, "total": round(gs * factor, 3), "segments": sg})
    return out


def build_glyphs(units: list[dict], values: dict, spec: Any, slug: str) -> dict[str, Any]:
    """Pure: ``units`` (``name`` + shapely ``geometry``), the field-inventory ``values`` per unit name and the spec (carrying any
    user colours) → the response. A unit with no field-inventory summary is left out; one with a summary but no data is kept
    (an empty glyph is a finding, not a gap)."""
    from app.core import semantic_palettes as sp
    from app.services.operational_plan import thematic_overlay as to

    meta = CHARTS[slug]
    kind = meta["kind"]
    if spec.measure == "species:share":
        return _build_species(units, values, spec, slug)
    comps_spec = list(spec.components or [])
    palette = (list(sp.CATEGORICAL["dbh_classes_10plus"]) if spec.measure == "dbh10:stock"
               else list(sp.CATEGORICAL.get("dbh_classes", {}).keys()) if spec.measure.startswith("dbh:") else comps_spec)

    def label_en(key: str) -> str:
        return LABELS_EN.get(key) or COMP_EN.get(key) or key

    out_units: list[dict] = []
    present: set[int] = set()
    radar_axes = list(spec.glyph_axes or to._RADAR_AXES) if kind == "radar" else []
    radar = _radar_fractions(values, radar_axes, spec) if kind == "radar" else {}
    for u in units:
        name = u.get("name") or ""
        rec = values.get(name)
        geom = u.get("geometry")
        if not rec or geom is None or geom.is_empty:
            continue
        lon, lat = to._glyph_point(geom)
        row: dict[str, Any] = {"name": name, "anchor": [round(lon, 6), round(lat, 6)], "plots": int(rec.get("total_sample_plots") or 0)}
        if kind == "radar":
            row.update(segments=[], total=0.0, radar=[round(x, 3) for x in radar.get(name, [])],
                       text_short="", text_long="", total_m3_per_ha=0.0, ge40_pct=None)
            out_units.append(row)
            continue
        segs: list[dict] = []
        total = ge40 = 0.0
        for i, (label_ne, value, hexv) in enumerate(to._composition(name, values, spec)):
            key = palette[i] if i < len(palette) else str(i)
            v = float(value or 0.0)
            total += v
            if key in GE40_KEYS:
                ge40 += v
            if v > 0 or kind == "ternary":
                present.add(i)
            if v > 0 or kind in ("sparkline", "ternary"):
                segs.append({"index": i, "key": key, "label_ne": COMP_NE.get(key, label_ne), "label_en": label_en(key),
                             "value": round(v, 2), "color": hexv})
        ge40_pct = round(100.0 * ge40 / total, 0) if total > 0 and slug == "timber-by-size" else None
        short, long_ = _texts(slug, total, segs, ge40_pct)
        if kind == "triplebar":
            row["bars"] = _triple_bars(rec, segs)
        row.update(total_m3_per_ha=round(total, 1), total=round(total, 1), ge40_pct=ge40_pct, segments=segs,
                   text_short=short, text_long=long_)
        if kind == "triplebar":
            b = {x["key"]: x["total"] for x in row["bars"]}
            row.update(text_short=_n(b["gs"]), text_long=f"GS {_n(b['gs'])} · MAI {b['mai']:.1f} · AAH {b['aah']:.1f} m³/ha")
        out_units.append(row)
    if not out_units:
        return {"state": "no_data", "kind": slug}
    if kind == "radar":
        legend = [{"index": i, "override_key": str(i), "key": a, "label_ne": RADAR_AXES_NE.get(a, a), "label_en": RADAR_AXES_EN.get(a, a), "color": ""}
                  for i, a in enumerate(radar_axes)]
    else:
        full = to._composition(out_units[0]["name"], values, spec)
        legend = [
            {"index": i, "override_key": str(i), "key": (palette[i] if i < len(palette) else str(i)), "label_ne": COMP_NE.get(palette[i] if i < len(palette) else "", full[i][0]),
             "label_en": label_en(palette[i] if i < len(palette) else str(i)), "color": full[i][2]}
            for i in sorted(present)
        ]
    return {
        "state": "ready",
        "kind": slug,
        "shape": kind,
        "id": meta["id"],
        "token": f"thememap:{meta['spec']}",
        "editable": kind not in ("radar", "sparkline"),  # their colours are fixed in the print map too
        "custom_colours": bool(getattr(spec, "colour_overrides", None)),
        "max_total": max((u["total"] for u in out_units), default=0.0),
        "units": out_units,
        "legend": legend,
        **({"bar_max": {k: max((x["total"] for u in out_units for x in u["bars"] if x["key"] == k), default=0.0) for k in ("gs", "mai", "aah")}}
           if kind == "triplebar" else {}),
    }


def build_timber_glyphs(units: list[dict], values: dict, spec: Any) -> dict[str, Any]:
    """The headline chart (kept for callers and tests)."""
    return build_glyphs(units, values, spec, "timber-by-size")


def chart(db: Any, calculation_id: UUID, slug: str) -> dict[str, Any]:
    """The response for one forest and one chart. Reads the field-inventory summary only; never computes anything."""
    from app.services.operational_plan import hazard_tiles as ht
    from app.services.operational_plan import thematic_overlay as to
    from app.services.operational_plan.thematic_map_spec import BUILTIN_THEMEMAP_SPECS

    values = to._load_unit_values(db, calculation_id)
    if not values:
        return {"state": "not_computed", "kind": slug}
    spec = to._with_user_colours(db, calculation_id, BUILTIN_THEMEMAP_SPECS[CHARTS[slug]["spec"]])
    return build_glyphs(ht.units_for_summary(db, calculation_id), values, spec, slug)


def timber_by_size(db: Any, calculation_id: UUID) -> dict[str, Any]:
    return chart(db, calculation_id, "timber-by-size")
