"""RUSLE soil-loss — bilingual narration for the OP (§2 P4).

Three adaptive paragraphs built from ``data_collector.get_soil_erosion_data``'s
output dict:

* **methodology** — the RUSLE equation, the data layers, the *resolved* method /
  coefficient / class-break values, the assumptions, the citations; flags
  "(parameters customised for this forest)" when any value's provenance is not
  ``default``.
* **findings** — mean vs the tolerable limit, % of area above it, the dominant
  spatial driver, the named hotspot units, the CF-vs-user-group split.
* **prescription** — rule-based: what the plan should do, keyed off the dominant
  factor + whether the catchment (outside the forest) erodes faster.

Each degrades to a single honest sentence when the soil-loss layer is not
available for the forest. Pure functions — no DB, no I/O.
"""

from __future__ import annotations

from typing import Any

from app.services.operational_plan.soil_erosion_config import CITATIONS

_FACTOR_NE = {
    "R": "वर्षाको क्षयकारी शक्ति (R)",
    "K": "माटोको क्षयशीलता (K)",
    "LS": "ढलानको लम्बाइ र भिरालोपन (LS)",
    "C": "भू-आवरण तथा व्यवस्थापन (C)",
}
_FACTOR_EN = {
    "R": "rainfall erosivity (R)",
    "K": "soil erodibility (K)",
    "LS": "slope length & steepness (LS)",
    "C": "cover management (C)",
}

# dominant-factor → (Nepali prescription clause, English prescription clause)
_PRESCRIPTION_BY_FACTOR = {
    "LS": (
        "भिरालो जमिन नै मुख्य कारण भएकाले उच्च-क्षय एकाइहरूमा कटान रोक्ने, भू-प्राविधिक "
        "कार्य (चेक ड्याम, ग्याबिन, समोच्च खाल्डो) गर्ने र भुइँ-आवरण जोगाउने।",
        "steep ground is the main driver, so on the high-erosion units the plan "
        "halts felling, applies bio-engineering (check dams, gabions, contour "
        "trenches) and retains ground cover.",
    ),
    "C": (
        "पातलो भू-आवरण नै मुख्य कारण भएकाले छत्र-घनत्व बढाउने, चरिचरन र डढेलो "
        "नियन्त्रण गर्ने र खेतीयोग्य टुक्रामा कृषि-वानिकी प्रवर्द्धन गर्ने।",
        "thin vegetation cover is the main driver, so the plan closes canopy "
        "gaps, controls grazing and fire, and promotes agroforestry on the "
        "cultivated patches.",
    ),
    "K": (
        "क्षयशील माटो नै मुख्य कारण भएकाले माटो कम खलबल्याउने, मल्चिङ गर्ने र नाङ्गो "
        "जमिन ढाक्ने।",
        "erodible soil is the main driver, so the plan minimises soil "
        "disturbance, mulches, and keeps bare ground covered.",
    ),
    "R": (
        "उच्च वर्षा-क्षयकारिता नै मुख्य कारण भएकाले वर्षभरि भुइँ-आवरण कायम राख्ने र "
        "पानी निकास व्यवस्थापन गर्ने।",
        "high rainfall erosivity is the main driver, so the plan keeps "
        "year-round ground cover and manages drainage.",
    ),
}


def _num(v, nd=1):
    try:
        return f"{float(v):.{nd}f}"
    except (TypeError, ValueError):
        return "—"


# ── methodology ─────────────────────────────────────────────────────────
def methodology(d: dict[str, Any], lang: str = "ne") -> str:
    if not d.get("soil_loss_available"):
        if lang == "ne":
            return (
                "यस वनका लागि RUSLE माटो क्षय विश्लेषण गर्न आवश्यक रास्टर तथ्याङ्क "
                "(DEM वा माटो) उपलब्ध नभएकाले माटो क्षयको अनुमान गरिएको छैन।"
            )
        return (
            "The raster data (DEM or soil) needed for a RUSLE soil-loss "
            "analysis is not available for this forest, so no estimate was made."
        )
    r_method = d.get("soil_loss_r_method", "mfi")
    breaks = d.get("soil_loss_severity_breaks") or [5, 10, 20, 40, 80]
    tol = d.get("soil_loss_tolerable", 10)
    customised = bool(
        [
            k
            for k, v in (d.get("soil_loss_params_provenance") or {}).items()
            if v != "default"
        ]
    )
    if lang == "ne":
        r_txt = (
            "संशोधित फोर्नियर सूचकाङ्क (Arnoldus 1980)"
            if r_method == "mfi"
            else "वार्षिक वर्षा-प्रतिगमन"
        )
        s = (
            "माटो क्षयको अनुमान RUSLE समीकरण (A = R·K·LS·C·P) बाट गरिएको हो, जहाँ "
            "A = वार्षिक माटो क्षय (टन/हेक्टर/वर्ष)। तथ्याङ्क स्रोत: उचाइ (DEM), "
            "माटोको बनावट (SoilGrids/MMU), वर्षा र भू-आवरण (ESA WorldCover)। "
            f"R कारक {r_txt} बाट, K कारक EPIC/Williams समीकरणबाट, LS कारक DEM बाट "
            "र C कारक भू-आवरण वर्गबाट (छत्र उचाइले समायोजित) गणना गरिएको छ। "
            f"गम्भीरता वर्ग सीमा: {', '.join(_num(b, 0) for b in breaks)} टन/हेक्टर/वर्ष; "
            f"सह्य सीमा {_num(tol, 0)} टन/हेक्टर/वर्ष मानिएको छ।"
        )
        for a in d.get("soil_loss_assumptions", [])[:5]:
            s += f"\n• {a}"
        if customised:
            s += "\n(यी प्यारामिटर यस वनका लागि समायोजन गरिएका छन्।)"
        return s
    r_txt = (
        "the Modified Fournier Index (Arnoldus 1980)"
        if r_method == "mfi"
        else "an annual-rainfall regression"
    )
    s = (
        "Soil loss was estimated with the RUSLE equation (A = R·K·LS·C·P), where "
        "A is annual soil loss (t ha-1 yr-1). Data layers: elevation (DEM), soil "
        "texture (SoilGrids/MMU), rainfall, and land cover (ESA WorldCover). "
        f"R is derived from {r_txt}, K from the EPIC/Williams equation, LS from "
        "the DEM, and C from the land-cover class (adjusted by canopy height). "
        f"Severity-class breaks: {', '.join(_num(b, 0) for b in breaks)} t ha-1 yr-1; "
        f"the tolerable limit is taken as {_num(tol, 0)} t ha-1 yr-1."
    )
    for a in d.get("soil_loss_assumptions_en", [])[:5]:
        s += f"\n- {a}"
    s += "\n" + " ".join(
        CITATIONS[k]
        for k in ("nepal_rusle", "r_mfi", "k_williams", "ls")
        if k in CITATIONS
    )
    if customised:
        s += "\n(Parameters customised for this forest.)"
    return s


# ── findings ────────────────────────────────────────────────────────────
def findings(d: dict[str, Any], lang: str = "ne") -> str:
    if not d.get("soil_loss_available"):
        return (
            "माटो क्षयको मात्रात्मक अनुमान उपलब्ध छैन।"
            if lang == "ne"
            else "No quantitative soil-loss estimate is available."
        )
    mean = d.get("soil_loss_mean_t_ha")
    total = d.get("soil_loss_total_t_yr")
    tol = d.get("soil_loss_tolerable", 10)
    pct = d.get("soil_loss_pct_above_tolerable", 0)
    dom = d.get("soil_loss_dominant_factor")
    hot = d.get("soil_loss_hotspot_units_str", "—")
    ug_only = d.get("soil_loss_ug_minus_cf_mean_t_ha")
    delivered = d.get("soil_loss_delivered_t_yr")
    sdr = d.get("soil_loss_basin_sdr")

    if lang == "ne":
        band = "सह्य सीमाभन्दा माथि" if (mean or 0) > tol else "सह्य सीमाभित्र"
        s = (
            f"समुदायिक वनको औसत वार्षिक माटो क्षय {_num(mean)} टन/हेक्टर/वर्ष "
            f"({band}), कुल लगभग {_num(total, 0)} टन/वर्ष रहेको छ। वन क्षेत्रफलको "
            f"{_num(pct)}% भाग सह्य सीमा ({_num(tol, 0)} टन/हेक्टर/वर्ष) भन्दा माथि छ।"
        )
        if dom in _FACTOR_NE:
            s += f" क्षयको स्थानिक भिन्नताको प्रमुख कारक {_FACTOR_NE[dom]} हो।"
        if hot and hot != "—":
            s += f" सबैभन्दा बढी क्षय हुने एकाइहरू: {hot}।"
        if ug_only is not None:
            s += (
                f" वन बाहिरको उपभोक्ता क्षेत्रको बस्ती भूमिमा औसत क्षय "
                f"{_num(ug_only)} टन/हेक्टर/वर्ष रहेको छ — वनभित्रको भन्दा उल्लेख्य "
                "बढी, जसले वनले जलाधार संरक्षणमा पुर्‍याएको योगदान देखाउँछ।"
            )
        if delivered is not None:
            s += (
                f" यसमध्ये अनुमानित {_num(delivered, 0)} टन/वर्ष मात्र नदी-नालासम्म "
                f"पुग्छ (तलछट वितरण अनुपात SDR ≈ {_num(sdr, 2)}); बाँकी वनभित्रै "
                "थिग्रन्छ — घना वन आवरणले तलछट रोकेको सङ्केत।"
            )
        return s
    band = "above" if (mean or 0) > tol else "within"
    s = (
        f"The community forest's mean annual soil loss is {_num(mean)} t ha-1 yr-1 "
        f"({band} the tolerable limit), about {_num(total, 0)} t yr-1 in total. "
        f"{_num(pct)}% of the forest area is above the tolerable limit "
        f"({_num(tol, 0)} t ha-1 yr-1)."
    )
    if dom in _FACTOR_EN:
        s += f" The dominant driver of spatial variation is {_FACTOR_EN[dom]}."
    if hot and hot != "—":
        s += f" The highest-erosion units are: {hot}."
    if ug_only is not None:
        s += (
            f" On the settlement land outside the forest, mean loss is "
            f"{_num(ug_only)} t ha-1 yr-1 — markedly higher than inside, which "
            "shows the forest's contribution to catchment protection."
        )
    if delivered is not None:
        s += (
            f" Of this, an estimated {_num(delivered, 0)} t yr-1 actually reaches "
            f"the stream network (sediment delivery ratio SDR ≈ {_num(sdr, 2)}); "
            "the rest is retained on-site — a signal of the disconnecting effect "
            "of dense forest cover."
        )
    return s


# ── prescription ────────────────────────────────────────────────────────
def prescription(d: dict[str, Any], lang: str = "ne") -> str:
    if not d.get("soil_loss_available"):
        return (
            "माटो क्षय नियन्त्रणका लागि सामान्य असल अभ्यास (भुइँ-आवरण संरक्षण, "
            "भिरालोमा कटान नियन्त्रण) अपनाइनेछ।"
            if lang == "ne"
            else "General good practice for erosion control (retain ground "
            "cover, limit harvesting on steep slopes) will be followed."
        )
    dom = d.get("soil_loss_dominant_factor")
    hot = d.get("soil_loss_hotspot_units_str", "—")
    pct = d.get("soil_loss_pct_above_tolerable", 0)
    ug_only = d.get("soil_loss_ug_minus_cf_mean_t_ha")
    cf_mean = d.get("soil_loss_mean_t_ha") or 0

    ne, en = _PRESCRIPTION_BY_FACTOR.get(dom, _PRESCRIPTION_BY_FACTOR["C"])
    if lang == "ne":
        s = f"कार्ययोजनाले माटो क्षय घटाउन: {ne}"
        if hot and hot != "—":
            s += (
                f" उच्च-क्षय एकाइहरू ({hot}) मा वन-पालन हस्तक्षेप गर्दा छत्र-आवरण "
                "कम्तीमा तोकिएको सीमामा राख्ने र भिरालो भागमा कटान नगर्ने।"
            )
        if (pct or 0) >= 25:
            s += (
                " वन क्षेत्रफलको ठूलो भाग सह्य सीमाभन्दा माथि भएकाले प्राथमिकतासाथ "
                "गल्ली उपचार र भू-संरक्षण कार्य गर्ने।"
            )
        if ug_only is not None and ug_only > 1.4 * cf_mean:
            s += (
                " वन बाहिरको बस्ती भूमिमा क्षय उच्च भएकाले उपभोक्ता समूहसँग "
                "मिलेर कृषि-वानिकी/SALT, वैकल्पिक ऊर्जा (दाउरा माग घटाउन) र "
                "थुनेर पालन (चरन दबाब घटाउन) कार्यक्रम विस्तार गर्ने — विशेषगरी "
                "वन-आश्रित र विपन्न घरधुरीलाई लक्षित गरी।"
            )
        return s
    s = f"To reduce soil loss the plan will: {en}"
    if hot and hot != "—":
        s += (
            f" On the high-erosion units ({hot}), silvicultural interventions "
            "will keep canopy cover at or above the prescribed threshold and "
            "exclude felling on the steep portions."
        )
    if (pct or 0) >= 25:
        s += (
            " Because a large share of the forest is above the tolerable "
            "limit, gully treatment and soil-conservation works are prioritised."
        )
    if ug_only is not None and ug_only > 1.4 * cf_mean:
        s += (
            " Since erosion is high on the settlement land outside the forest, "
            "the user group will extend agroforestry / SALT, alternative energy "
            "(to cut firewood demand) and stall-feeding (to cut grazing "
            "pressure) onto that land — targeting the forest-dependent and "
            "poorest households first."
        )
    return s


def all_narration(d: dict[str, Any]) -> dict[str, str]:
    """The six keys merged into ``get_soil_erosion_data``'s output."""
    return {
        "soil_loss_methodology_narration": methodology(d, "ne"),
        "soil_loss_methodology_narration_en": methodology(d, "en"),
        "soil_loss_findings_narration": findings(d, "ne"),
        "soil_loss_findings_narration_en": findings(d, "en"),
        "soil_loss_prescription_narration": prescription(d, "ne"),
        "soil_loss_prescription_narration_en": prescription(d, "en"),
    }


__all__ = ["methodology", "findings", "prescription", "all_narration"]
