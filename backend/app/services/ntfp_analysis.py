"""NTFP inventory analysis: frequency, density, importance value, conversion factor, yield per hectare and stock (NTFP inventory, phase 4).

Pure: dicts in, dicts out. The database side is ``ntfp_analysis_service``. Formulas are the guideline's (गैरकाष्ठ वन पैदावारको स्रोत सर्वेक्षण मार्गदर्शन
२०६९, part 4 and sections 4.1.1.1, 5.x):

  frequency %           plots where the species was found / plots surveyed for it x 100
  relative frequency %  its frequency / the sum of the frequencies of all the species x 100
  density per ha        plants counted / (plots surveyed x plot area m2) x 10 000
  relative density %    its density / the sum of the densities x 100
  IVI                   relative frequency + relative density (0 to 200)
  conversion factor     dry weight of the samples / fresh weight of the samples
  yield, fresh kg/ha    density per ha x mean fresh weight of one sampled individual (g) / 1000
  yield, dry kg/ha      fresh yield x conversion factor
  stock (kg)            yield per ha x the area surveyed (ha)

What differs from a bare reading of the guideline, and why:
  * IVI here has two parts, frequency and density. The guideline's third part (basal area, or coverage for herbs) is not recorded by the form.
    The result says so (``ivi_parts = 2``) instead of passing it off as the guideline's three-part value.
  * Density and yield are STRATIFIED: each stratum's mean density is weighted by the stratum's area, so a big stratum with few plots counts as big.
  * Precision (95 % half-width as a percentage of the estimate) is given for density and for fresh yield, from the plot-to-plot spread. With fewer
    than two plots in a stratum, or fewer than two weighed samples, it is None: unknown, not zero.
  * A species is only analysed over the plots that were SURVEYED (an observation exists, zero included); ``coverage_pct`` is the share of the forest
    area those plots speak for.
  * The weights are those the team recorded. Where the method takes only a fraction of a part (the method card's ``harvest_fraction_pct``, e.g. a quarter of
    the leaves), the yield is scaled up to the whole part: mean weight x 100 / fraction (``scale_factor``). The recorded mean is kept (``mean_fresh_g``) beside
    the scaled one (``mean_whole_fresh_g``). The precision percentage is the same either way: mean and spread scale together.
"""
from __future__ import annotations

import math
from collections import defaultdict
from typing import Any, Dict, List, Optional, Sequence, Tuple

#: two-sided 95 % Student t by degrees of freedom 1..30
_T95 = [12.706, 4.303, 3.182, 2.776, 2.571, 2.447, 2.365, 2.306, 2.262, 2.228, 2.201, 2.179, 2.160, 2.145, 2.131, 2.120, 2.110, 2.101, 2.093,
        2.086, 2.080, 2.074, 2.069, 2.064, 2.060, 2.056, 2.052, 2.048, 2.045, 2.042]

FEW_PLOTS = 5          # fewer surveyed plots than this: the estimate is shaky (warning)
CF_DIFFERS_PCT = 25.0  # a measured conversion factor this far from the guideline's reference is flagged
SQM_PER_HA = 10_000.0


def t95(df: int) -> float:
    if df < 1:
        return float("nan")
    if df <= 30:
        return _T95[df - 1]
    return 2.03 if df <= 40 else 2.01 if df <= 60 else 1.99 if df <= 120 else 1.96


def _mean(xs: Sequence[float]) -> float:
    return sum(xs) / len(xs)


def _var(xs: Sequence[float]) -> Optional[float]:
    """Sample variance; None for fewer than two values."""
    if len(xs) < 2:
        return None
    m = _mean(xs)
    return sum((x - m) ** 2 for x in xs) / (len(xs) - 1)


def _round(x: Optional[float], n: int = 4) -> Optional[float]:
    return None if x is None else round(x, n)


def _density_estimate(per_stratum: Dict[str, List[float]], areas: Dict[str, float]) -> Dict[str, Any]:
    """Stratified mean density per ha (plants/ha), its standard error and degrees of freedom. Only strata with at least one plot count."""
    strata = [(h, ds) for h, ds in per_stratum.items() if ds and areas.get(h, 0) > 0]
    total_a = sum(areas[h] for h, _ in strata)
    if not strata or total_a <= 0:
        return {"density": None, "se": None, "df": 0, "area_ha": 0.0, "strata": []}
    d = sum(areas[h] * _mean(ds) for h, ds in strata) / total_a
    var, df, known = 0.0, 0, True
    for h, ds in strata:
        v = _var(ds)
        if v is None:
            known = False
            continue
        var += (areas[h] / total_a) ** 2 * v / len(ds)
        df += len(ds) - 1
    return {
        "density": d, "se": math.sqrt(var) if known else None, "df": df if known else 0, "area_ha": total_a,
        "strata": [{"name": h, "area_ha": round(areas[h], 4), "plots_surveyed": len(ds), "density_per_ha": round(_mean(ds), 4)} for h, ds in strata],
    }


def analyse(areas_ha: Dict[str, float], plots: Sequence[Dict[str, Any]], species: Sequence[Dict[str, Any]], observations: Sequence[Dict[str, Any]],
            weights: Sequence[Dict[str, Any]], references: Optional[Dict[str, Dict[str, Any]]] = None) -> Dict[str, Any]:
    """
    ``areas_ha``       stratum name -> area (ha) of the whole stratum
    ``plots``          ``[{plot_number, stratum, species_keys}]`` (the design)
    ``species``        ``[{species_key, label, plot_sqm, growth_class}]`` (the design's species)
    ``observations``   ``[{plot_number, species_key, count_total}]``
    ``weights``        ``[{plot_number, species_key, part_group, fresh_weight_g, dry_weight_g}]``
    ``references``     species_key -> ``{conversion_factor, harvest_fraction_pct, part_groups}`` from the method profile (optional)
    """
    references = references or {}
    stratum_of = {p["plot_number"]: p["stratum"] for p in plots}
    forest_ha = sum(areas_ha.values())
    obs_by: Dict[str, Dict[int, int]] = defaultdict(dict)
    for o in observations:
        obs_by[o["species_key"]][o["plot_number"]] = int(o["count_total"])
    w_by: Dict[Tuple[str, Optional[str]], List[Dict[str, Any]]] = defaultdict(list)
    for w in weights:
        w_by[(w["species_key"], w.get("part_group"))].append(w)
    assigned: Dict[str, int] = defaultdict(int)
    for p in plots:
        for k in p.get("species_keys", []):
            assigned[k] += 1

    rows: List[Dict[str, Any]] = []
    for sp in species:
        key, plot_sqm = sp["species_key"], float(sp["plot_sqm"])
        ref = references.get(key, {})
        counts = obs_by.get(key, {})
        surveyed, present = len(counts), sum(1 for c in counts.values() if c > 0)
        warnings: List[str] = []
        per_stratum: Dict[str, List[float]] = defaultdict(list)
        for pn, c in counts.items():
            per_stratum[stratum_of[pn]].append(c / plot_sqm * SQM_PER_HA)
        est = _density_estimate(per_stratum, areas_ha)
        density = est["density"]
        if surveyed == 0:
            warnings.append("not_surveyed")
        elif surveyed < FEW_PLOTS:
            warnings.append("few_plots")
        if surveyed and surveyed < assigned.get(key, 0):
            warnings.append("survey_incomplete")
        if surveyed and present == 0:
            warnings.append("not_found")
        prec = None
        if density and est["se"] is not None and est["df"] >= 1:
            prec = t95(est["df"]) * est["se"] / density * 100.0
        row: Dict[str, Any] = {
            "species_key": key, "label": sp.get("label", ""), "growth_class": sp.get("growth_class"), "plot_sqm": plot_sqm,
            "plots_assigned": assigned.get(key, 0), "plots_surveyed": surveyed, "plots_present": present,
            "frequency_pct": _round(present / surveyed * 100.0 if surveyed else None, 2), "count_total": sum(counts.values()),
            "density_per_ha": _round(density), "density_se": _round(est["se"]), "density_precision_pct": _round(prec, 1),
            "area_surveyed_ha": round(est["area_ha"], 4), "coverage_pct": _round(est["area_ha"] / forest_ha * 100.0 if forest_ha else None, 1),
            "strata": est["strata"], "parts": [], "warnings": warnings,
        }
        # weights, per part
        parts = sorted({p for (k, p) in w_by if k == key}, key=lambda x: (x is None, x or ""))
        for part in parts:
            ws = w_by[(key, part)]
            fresh = [float(w["fresh_weight_g"]) for w in ws]
            pairs = [(float(w["fresh_weight_g"]), float(w["dry_weight_g"])) for w in ws if w.get("dry_weight_g") is not None]
            frac = ref.get("harvest_fraction_pct")
            scale = 100.0 / frac if frac and 0 < frac < 100 else 1.0     # the recorded weights are of a fraction of the part: scale to the whole part
            recorded_mean = _mean(fresh)
            fresh = [x * scale for x in fresh]
            mean_fresh = _mean(fresh)
            vw = _var(fresh)
            cf = (sum(d for _, d in pairs) / sum(f for f, _ in pairs)) if pairs and sum(f for f, _ in pairs) > 0 else None
            part_warn: List[str] = []
            ref_cf = ref.get("conversion_factor")
            if cf is None:
                part_warn.append("no_dry_weights")
            elif ref_cf and abs(cf - ref_cf) / ref_cf * 100.0 > CF_DIFFERS_PCT:
                part_warn.append("cf_differs_from_guideline")
            if len(ws) < 3:
                part_warn.append("few_samples")
            y_fresh = density * mean_fresh / 1000.0 if density is not None else None
            y_prec = None
            if y_fresh and est["se"] is not None and est["df"] >= 1 and vw is not None and density:
                var_y = (mean_fresh ** 2 * est["se"] ** 2 + density ** 2 * (vw / len(fresh))) / 1_000_000.0
                # degrees of freedom: the smaller of the two sources, the cautious choice
                df = max(1, min(est["df"], len(fresh) - 1))
                y_prec = t95(df) * math.sqrt(var_y) / y_fresh * 100.0
            y_dry = y_fresh * cf if (y_fresh is not None and cf is not None) else None
            area = est["area_ha"]
            row["parts"].append({
                "part_group": part, "samples": len(ws), "dry_pairs": len(pairs), "mean_fresh_g": _round(recorded_mean, 2),
                "scale_factor": _round(scale, 4), "mean_whole_fresh_g": _round(mean_fresh, 2),
                "conversion_factor": _round(cf), "conversion_factor_reference": ref_cf,
                "harvest_fraction_pct": ref.get("harvest_fraction_pct"),
                "yield_fresh_kg_ha": _round(y_fresh, 3), "yield_dry_kg_ha": _round(y_dry, 3), "yield_precision_pct": _round(y_prec, 1),
                "stock_fresh_kg": _round(y_fresh * area if y_fresh is not None else None, 1),
                "stock_dry_kg": _round(y_dry * area if y_dry is not None else None, 1), "warnings": part_warn,
            })
        if not parts and surveyed and present:
            warnings.append("no_weights")
        rows.append(row)

    # relative values and the importance value, over the species that were surveyed
    surveyed_rows = [r for r in rows if r["plots_surveyed"]]
    sum_f = sum(r["frequency_pct"] or 0.0 for r in surveyed_rows)
    sum_d = sum(r["density_per_ha"] or 0.0 for r in surveyed_rows)
    for r in rows:
        r["relative_frequency_pct"] = _round((r["frequency_pct"] or 0.0) / sum_f * 100.0, 2) if sum_f and r in surveyed_rows else None
        r["relative_density_pct"] = _round((r["density_per_ha"] or 0.0) / sum_d * 100.0, 2) if sum_d and r in surveyed_rows else None
        r["ivi"] = _round(r["relative_frequency_pct"] + r["relative_density_pct"], 2) if r["relative_frequency_pct"] is not None and r["relative_density_pct"] is not None else None
    ranked = sorted((r for r in rows if r["ivi"] is not None), key=lambda r: -r["ivi"])
    for i, r in enumerate(ranked, 1):
        r["ivi_rank"] = i
    for r in rows:
        r.setdefault("ivi_rank", None)

    return {
        "forest_area_ha": round(forest_ha, 4), "plots_in_design": len(plots), "species": rows, "ivi_parts": 2,
        "notes": ["ivi_without_basal_area", "weights_scaled_to_the_whole_part"],
    }
