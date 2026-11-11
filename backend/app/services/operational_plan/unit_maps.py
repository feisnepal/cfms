"""Single-number unit maps for the workspace ("Colour by ▸ Field inventory"): growing stock, basal area, AAH, MAI, carbon …

Placeholder: the print map variable of the same name (``thememap:unit__growing_stock`` …). The CLASSES, COLOURS and legend
come from the print renderer's own colour function (``thematic_overlay._colour_map`` / ``_categorical_colours``), with the
user's own colours laid over them exactly as the print map does — so the workspace colouring, the page thumbnail and the
Operational Plan figure cannot disagree. The browser only paints what it is given.

Reads the stored field-inventory summary only; never computes.
"""
from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

logger = logging.getLogger(__name__)

# workspace id -> (print spec key, unit suffix for the compact label)
FI_MAPS: dict[str, tuple[str, str]] = {
    "fi_growing_stock": ("unit__growing_stock", "m³/ha"),
    "fi_basal_area": ("unit__basal_area", "m²/ha"),
    "fi_aah": ("unit__aah", "m³/ha/yr"),
    "fi_mai": ("unit__mai", "m³/ha/yr"),
    "fi_mai_pct": ("unit__mai_percent", "%"),
    "fi_carbon": ("unit__carbon", "tC/ha"),
    "fi_biomass": ("unit__biomass", "t/ha"),
    "fi_co2": ("unit__co2", "tCO₂/ha"),
    "fi_regeneration": ("unit__regeneration_stems", "/ha"),
    "fi_pole": ("unit__pole_per_ha", "/ha"),
    "fi_tree": ("unit__tree_per_ha", "/ha"),
    "fi_stems": ("unit__stems_total", "/ha"),
    "fi_condition": ("unit__forest_condition", ""),
    "fi_regen_condition": ("unit__regeneration_condition", ""),
    "fi_working_circle": ("unit__working_circle", ""),
    "fi_satellite": ("unit__satellite_stock", "m³/ha"),
    "fi_field_vs_satellite": ("unit__field_vs_satellite", "m³/ha"),
    "fi_pole_tree": ("unit__pole_tree_share", "% trees"),
    "fi_condition_reason": ("unit__condition_reason", ""),
    "fi_condition_stocking": ("unit__condition_x_stocking", ""),
    "fi_species": ("unit__species_dominant", ""),
}
BY_SPEC = {spec: (mid, suffix) for mid, (spec, suffix) in FI_MAPS.items()}

# the raw per-unit values the workspace table / labels read (property name -> field-inventory measure)
VALUE_MEASURES = {
    "fi_stock": "total_growing_stock_m3_per_ha",
    "fi_basal_area": "basal_area_m2_per_ha",
    "fi_aah": "aah_total_m3_per_ha",
    "fi_mai": "mai_total_m3_per_ha",
    "fi_mai_pct": "mai_percent",
    "fi_carbon": "carbon_stock_tc_per_ha",
    "fi_biomass": "total_biomass_t_per_ha",
    "fi_co2": "co2_equivalent_tco2_per_ha",
    "fi_regeneration": "regeneration_per_ha",
    "fi_sapling": "sapling_per_ha",
    "fi_pole": "pole_per_ha",
    "fi_tree": "tree_per_ha",
    "fi_plots": "total_sample_plots",
    "fi_condition": "forest_condition",
    "fi_regen_condition": "regeneration_condition",
}


_DEV = str.maketrans("०१२३४५६७८९", "0123456789")


def _en(label: str) -> str:
    """The print legend writes numbers in Devanagari digits; the English view wants ordinary ones."""
    return label.translate(_DEV)


def _area_ha(geom: Any) -> float:
    """A unit's area in hectares (the print renderer's own estimate); 0 when there is no usable geometry."""
    from app.services.operational_plan import thematic_overlay as to

    try:
        return round(float(to._geodesic_area_ha(geom)), 2) if geom is not None and not geom.is_empty else 0.0
    except Exception:  # noqa: BLE001 -- an area is a nicety on the legend, never a reason to fail the map
        return 0.0


def _fmt(v: Any, suffix: str) -> str | None:
    if v is None or v == "":
        return None
    try:
        n = float(v)
    except (TypeError, ValueError):
        return str(v)
    txt = f"{n:.0f}" if abs(n) >= 100 else f"{n:.1f}".rstrip("0").rstrip(".")
    return f"{txt} {suffix}".strip()


_COND_NE = {"Good": "राम्रो", "Moderate": "मध्यम", "Weak": "कमजोर"}


def condition_reason(rec: dict) -> tuple[str, str]:
    """Why a unit has the forest and regeneration condition it has: the stored numbers against the rule's own limits
    (``core.constants``; the same ones ``field_inventory_service`` applied). English and Nepali."""
    from app.core import constants as c

    regen, sap = float(rec.get("regeneration_per_ha") or 0), float(rec.get("sapling_per_ha") or 0)
    gs = float(rec.get("total_growing_stock_m3_per_ha") or 0)
    fc, rc = str(rec.get("forest_condition") or ""), str(rec.get("regeneration_condition") or "")
    band_en = (f"above {c.GS_GOOD_M3_PER_HA:.0f}" if gs > c.GS_GOOD_M3_PER_HA
               else f"{c.GS_MODERATE_M3_PER_HA:.0f}–{c.GS_GOOD_M3_PER_HA:.0f}" if gs >= c.GS_MODERATE_M3_PER_HA
               else f"below {c.GS_MODERATE_M3_PER_HA:.0f}")
    band_ne = band_en.replace("above", "माथि").replace("below", "तल")
    en = (f"Regeneration {regen:,.0f}/ha and saplings {sap:,.0f}/ha → regeneration {rc} "
          f"(Good needs ≥{c.REGEN_GOOD_PER_HA:,} and ≥{c.SAPLING_GOOD_PER_HA:,}; Moderate ≥{c.REGEN_MODERATE_PER_HA:,} and ≥{c.SAPLING_MODERATE_PER_HA:,}). "
          f"Growing stock {gs:,.0f} m³/ha (band {band_en}) → forest {fc}.")
    ne = (f"पुनरुत्पादन {regen:,.0f}/हे. र लाथ्रा {sap:,.0f}/हे. → पुनरुत्पादन {_COND_NE.get(rc, rc)} "
          f"(राम्रोका लागि ≥{c.REGEN_GOOD_PER_HA:,} र ≥{c.SAPLING_GOOD_PER_HA:,}; मध्यम ≥{c.REGEN_MODERATE_PER_HA:,} र ≥{c.SAPLING_MODERATE_PER_HA:,})। "
          f"वन मौज्दात {gs:,.0f} घ.मि./हे. (दायरा {band_ne}) → वन {_COND_NE.get(fc, fc)}।")
    return en, ne


def condition_why(rec: dict) -> dict[str, str]:
    """The short CAUSE of the two conditions, for the attribute table: ``{regen_en, regen_ne, forest_en, forest_ne}``.

    Regeneration is decided by seedlings (regeneration, 0-4 cm) AND saplings (4-10 cm) per hectare against two limits each; a
    Weak result names the limit(s) missed. The forest condition is growing stock band x regeneration condition. The limits are
    ``core.constants`` -- the ones ``field_inventory_service`` applied -- so this can never disagree with the rule.
    """
    from app.core import constants as c

    seed, sap = float(rec.get("regeneration_per_ha") or 0), float(rec.get("sapling_per_ha") or 0)
    gs = float(rec.get("total_growing_stock_m3_per_ha") or 0)
    rc = str(rec.get("regeneration_condition") or "")
    fc = str(rec.get("forest_condition") or "")

    def _n(v: float) -> str:
        return f"{v:,.0f}"

    if rc == "Good":
        lim_s, lim_p = c.REGEN_GOOD_PER_HA, c.SAPLING_GOOD_PER_HA
    else:
        lim_s, lim_p = c.REGEN_MODERATE_PER_HA, c.SAPLING_MODERATE_PER_HA
    if rc in ("Good", "Moderate"):
        r_en = f"seedlings {_n(seed)}/ha ≥ {_n(lim_s)}, saplings {_n(sap)}/ha ≥ {_n(lim_p)}"
        r_ne = f"बिरुवा {_n(seed)}/हे. ≥ {_n(lim_s)}, लाथ्रा {_n(sap)}/हे. ≥ {_n(lim_p)}"
    else:  # Weak: name what fell short of the Moderate limits
        miss_en, miss_ne = [], []
        if seed < c.REGEN_MODERATE_PER_HA:
            miss_en.append(f"seedlings {_n(seed)}/ha < {_n(c.REGEN_MODERATE_PER_HA)}")
            miss_ne.append(f"बिरुवा {_n(seed)}/हे. < {_n(c.REGEN_MODERATE_PER_HA)}")
        if sap < c.SAPLING_MODERATE_PER_HA:
            miss_en.append(f"saplings {_n(sap)}/ha < {_n(c.SAPLING_MODERATE_PER_HA)}")
            miss_ne.append(f"लाथ्रा {_n(sap)}/हे. < {_n(c.SAPLING_MODERATE_PER_HA)}")
        r_en = ", ".join(miss_en) or f"seedlings {_n(seed)}/ha, saplings {_n(sap)}/ha"
        r_ne = ", ".join(miss_ne) or f"बिरुवा {_n(seed)}/हे., लाथ्रा {_n(sap)}/हे."

    band = (f"> {c.GS_GOOD_M3_PER_HA:.0f}" if gs > c.GS_GOOD_M3_PER_HA
            else f"{c.GS_MODERATE_M3_PER_HA:.0f}–{c.GS_GOOD_M3_PER_HA:.0f}" if gs >= c.GS_MODERATE_M3_PER_HA
            else f"< {c.GS_MODERATE_M3_PER_HA:.0f}")
    f_en = f"growing stock {_n(gs)} m³/ha ({band}) + regeneration {rc}" if rc else f"growing stock {_n(gs)} m³/ha ({band})"
    f_ne = (f"वन मौज्दात {_n(gs)} घ.मि./हे. ({band}) + पुनरुत्पादन {_COND_NE.get(rc, rc)}" if rc
            else f"वन मौज्दात {_n(gs)} घ.मि./हे. ({band})")
    return {"regen_en": r_en, "regen_ne": r_ne, "forest_en": f_en if fc else "", "forest_ne": f_ne if fc else ""}


def pole_tree_detail(rec: dict) -> tuple[str, str]:
    """Poles (10-30 cm) and trees (30+ cm): stems and stock per ha, with MAI and AAH. MAI and AAH are held per BLOCK
    (growing stock x MAI %, then x AAH %), so each size group gets its share in proportion to its stock."""
    gs = float(rec.get("total_growing_stock_m3_per_ha") or 0)
    mai_f = float(rec.get("mai_total_m3_per_ha") or 0) / gs if gs > 0 else 0.0
    aah_f = float(rec.get("aah_total_m3_per_ha") or 0) / gs if gs > 0 else 0.0
    en, ne = [], []
    for key, label_en, label_ne in (("pole", "Poles 10–30 cm", "खाँवा १०–३० सेमी"), ("tree", "Trees 30+ cm", "रुख ३०+ सेमी")):
        n, v = float(rec.get(f"{key}_per_ha") or 0), float(rec.get(f"{key}_total_m3_per_ha") or 0)
        en.append(f"{label_en}: {n:,.0f} stems/ha · GS {v:,.1f} · MAI {v * mai_f:.2f} · AAH {v * aah_f:.2f} m³/ha")
        ne.append(f"{label_ne}: {n:,.0f} बोट/हे. · मौज्दात {v:,.1f} · MAI {v * mai_f:.2f} · AAH {v * aah_f:.2f} घ.मि./हे.")
    en.append("MAI and AAH are shared over the sizes in proportion to their stock.")
    ne.append("MAI र AAH मौज्दातको अनुपातमा बाँडिएको हो।")
    return chr(10).join(en), chr(10).join(ne)


def build_unit_map(units: list[dict], values: dict, spec: Any, suffix: str = "") -> dict[str, Any]:
    """Pure: units (``name`` + geometry), field-inventory ``values`` per unit name, the spec (carrying any user colours)."""
    from app.core import semantic_palettes as sp
    from app.services.operational_plan import thematic_overlay as to

    units = [u for u in units if u.get("name") in values]
    if not units:
        return {"state": "no_data"}
    own = spec.colour_overrides or {}
    legend: list[dict] = []
    feat: dict[str, str | None]
    if spec.viz == "bivariate":
        feat, rows = to._colour_map(units, values, spec)
        counts = {}
        for c in feat.values():
            counts[c] = counts.get(c, 0) + 1
        legend = [{"key": str(i), "color": c, "label": lbl, "label_ne": lbl, "label_en": _en(lbl), "count": counts.get(c, 0), "editable": False}
                  for i, (c, lbl) in enumerate(rows) if counts.get(c, 0) > 0]
    elif spec.palette == "species_dynamic":  # one colour per species of THIS forest; keyed by the species key
        feat, rows = to._colour_map(units, values, spec)
        classes = to._species_classes(values)
        seen: dict[str, int] = {}
        for u in units:
            k = (values.get(u["name"]) or {}).get(spec.measure)
            if k:
                seen[str(k)] = seen.get(str(k), 0) + 1
        for c in classes:
            if c["key"] in seen:
                col = own.get(c["key"]) or c["color"]
                legend.append({"key": c["key"], "color": col, "label": c["name"], "label_ne": c["name"], "label_en": c["name"],
                               "count": seen[c["key"]], "editable": True})
        n_other = sum(n for k, n in seen.items() if k not in {c["key"] for c in classes})
        if n_other:
            legend.append({"key": "other_species", "color": own.get("other_species") or to.OTHER_SPECIES_COLOUR, "label": to.OTHER_SPECIES_LABEL_NE,
                           "label_ne": to.OTHER_SPECIES_LABEL_NE, "label_en": "Other species", "count": n_other, "editable": True})
    elif spec.value_kind == "categorical":
        feat = {}
        seen: dict[str, int] = {}
        for u in units:
            raw = (values.get(u["name"]) or {}).get(spec.measure)
            key = "" if raw in (None, "") else str(raw)
            feat[u["name"]] = own.get(key) or sp.color_for_category(spec.palette, key)
            if key:
                seen[key] = seen.get(key, 0) + 1
        scheme = sp.CATEGORICAL.get(spec.palette, {})
        for k in scheme:
            if k in seen:
                lbl = sp.category_label(spec.palette, k)
                legend.append({"key": k, "color": own.get(k) or scheme[k], "label": lbl, "label_ne": lbl,
                               "label_en": (("Forest " + k.replace("|", " · regeneration ")) if spec.palette == "condition_pair" else str(k).replace("_", " ").capitalize()),
                               "count": seen[k], "editable": True})
        missing = sum(1 for u in units if (values.get(u["name"]) or {}).get(spec.measure) in (None, ""))
        if missing:
            legend.append({"key": "_none", "color": sp.NO_DATA_FILL, "label": sp.NO_DATA_LABEL_NE, "label_ne": sp.NO_DATA_LABEL_NE,
                           "label_en": "No data", "count": missing, "editable": False})
    else:
        feat, rows = to._colour_map(units, values, spec)
        counts = {}
        for c in feat.values():
            counts[c] = counts.get(c, 0) + 1
        for i, (c, lbl) in enumerate(rows):
            if c == sp.NO_DATA_FILL and counts.get(c, 0) == 0:
                continue
            if counts.get(c, 0) > 0:
                legend.append({"key": str(i), "color": c, "label": lbl, "label_ne": lbl,
                               "label_en": _en(lbl) if c != sp.NO_DATA_FILL else "No data",
                               "count": counts[c], "editable": c != sp.NO_DATA_FILL})
    names = {c["key"]: c["name"] for c in to._species_classes(values)} if spec.palette == "species_dynamic" else {}
    areas = {u["name"]: _area_ha(u.get("geometry")) for u in units}
    out_units = {}
    for u in units:
        name = u["name"]
        raw = (values.get(name) or {}).get(spec.measure)
        text = (names.get(str(raw)) or (to.OTHER_SPECIES_LABEL_NE if raw else None)) if names or spec.palette == "species_dynamic" else _fmt(raw, suffix)
        out_units[name] = {"color": feat.get(name) or sp.NO_DATA_FILL, "value": raw if isinstance(raw, (int, float, str)) else None,
                           "text": text, "area_ha": areas[name]}
        if spec.measure == "tree_share_pct":
            out_units[name]["reason"], out_units[name]["reason_ne"] = pole_tree_detail(values.get(name) or {})
        if spec.palette == "condition_pair" and raw:
            out_units[name]["text"] = "F " + str(raw).replace("Moderate", "Mod").replace("|", " · R ")  # F = forest, R = regeneration; short, the map label is small
        if spec.palette == "condition_pair":
            out_units[name]["reason"], out_units[name]["reason_ne"] = condition_reason(values.get(name) or {})
    for entry in legend:  # the area each class covers (a class is a colour: its units' areas add up)
        entry["area_ha"] = round(sum(areas[n] for n, uo in out_units.items() if (uo["color"] or "").lower() == (entry["color"] or "").lower()), 2)
    return {"state": "ready", "token": f"thememap:{spec.key}", "custom_colours": bool(own), "units": out_units, "legend": legend}


def unit_map(db: Any, calculation_id: UUID, spec_key: str) -> dict[str, Any]:
    from app.services.operational_plan import hazard_tiles as ht
    from app.services.operational_plan import thematic_overlay as to
    from app.services.operational_plan.thematic_map_spec import BUILTIN_THEMEMAP_SPECS

    if spec_key not in BY_SPEC:
        raise KeyError(spec_key)
    values = to._load_unit_values(db, calculation_id)
    if not values:
        return {"state": "not_computed"}
    spec = to._with_user_colours(db, calculation_id, BUILTIN_THEMEMAP_SPECS[spec_key])
    return build_unit_map(ht.units_for_summary(db, calculation_id), values, spec, BY_SPEC[spec_key][1])


def unit_values(db: Any, calculation_id: UUID) -> dict[str, Any]:
    """The raw per-unit field-inventory numbers the attribute table and labels use: ``{"units": {name: {fi_*: value}}}``."""
    from app.services.operational_plan import thematic_overlay as to

    values = to._load_unit_values(db, calculation_id)
    if not values:
        return {"state": "not_computed", "units": {}}
    # The inventory is worked out on the leaf stands; a divided parent shows the area-weighted roll-up of its sub-units.
    try:
        from app.services import unit_rollup

        values = unit_rollup.rollup_field_inventory(unit_rollup.unit_tree(db, calculation_id), values)
    except Exception:  # noqa: BLE001 -- the leaf values still serve; the parents just stay without a roll-up (logged)
        import logging

        logging.getLogger(__name__).exception("unit_values: parent roll-up failed")
    units: dict[str, dict] = {}
    for name, rec in values.items():
        row = {}
        for prop, measure in VALUE_MEASURES.items():
            v = rec.get(measure)
            if v is None or v == "":
                continue
            row[prop] = v if isinstance(v, str) else round(float(v), 2)
        if row.get("fi_regen_condition") or row.get("fi_condition"):
            why = condition_why(rec)
            if row.get("fi_regen_condition"):
                row["fi_regen_condition_why"], row["fi_regen_condition_why_ne"] = why["regen_en"], why["regen_ne"]
            if row.get("fi_condition") and why["forest_en"]:
                row["fi_condition_why"], row["fi_condition_why_ne"] = why["forest_en"], why["forest_ne"]
        units[name] = row
    return {"state": "ready", "units": units}
