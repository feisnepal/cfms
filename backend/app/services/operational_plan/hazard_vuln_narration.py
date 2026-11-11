"""Landslide hazard + household vulnerability — bilingual narration for the OP.

``HOUSEHOLD_VULNERABILITY_ANALYSIS_PLAN.md`` §2 / phase P6.

Three adaptive paragraphs built from ``data_collector.get_hazard_vuln_data``:

* **methodology** — the LSI weighted overlay (factors, weight source, AHP CR),
  the infinite-slope FS equation + monsoon scenario, the household composite;
  the assumptions and citations; flags "(parameters customised)" when any
  value's provenance is not ``default``.
* **findings** — the LSI class split and prone-area extent, the worst units,
  the FS unstable / marginal share, the CF-vs-user-group prone split, the
  household count / priority count / dominant driver; states plainly when the
  physical-hazard layer did not discriminate between households.
* **prescription** — rule-based: bio-engineering on High-LSI units, no felling
  on unstable ground, gully / drainage works where FS is marginal, and
  alternative-energy / stall-feeding / relocation-discussion targeting for the
  named priority toles.

Each degrades to a single honest sentence when the hazard layer is not
available. Pure functions — no DB, no I/O.
"""

from __future__ import annotations

from typing import Any

from app.services.operational_plan.hazard_vuln_config import CITATIONS

_DRIVER_ACTION_NE = {
    "Social marginalisation": (
        "सामाजिक रूपमा सीमान्तीकृत (दलित/जनजाती) घरधुरी बढी जोखिममा भएकाले "
        "लक्षित सहभागिता, सिप विकास र आय-आर्जन कार्यक्रममा प्राथमिकता दिने"
    ),
    "Economic status": (
        "विपन्न घरधुरी बढी जोखिममा भएकाले वैकल्पिक आयस्रोत, अनुदान र "
        "जीविकोपार्जन सहयोग कार्यक्रम केन्द्रित गर्ने"
    ),
    "Forest dependence": (
        "वन-निर्भरता उच्च भएकाले वैकल्पिक ऊर्जा (सुधारिएको चुलो/बायोग्यास — "
        "दाउरा माग घटाउन), थुनेर पशुपालन (चरन दबाब घटाउन) र निजी वन/कृषि-वानिकी "
        "प्रवर्द्धन गर्ने"
    ),
    "Demographic sensitivity": (
        "महिला-नेतृत्वको वा ठूलो परिवार भएका घरधुरीलाई सामाजिक सुरक्षा र "
        "आपत्कालीन तयारीमा समावेश गर्ने"
    ),
    "Physical hazard exposure": (
        "पहिरो-प्रवण भिरमुनि रहेका घरधुरीका लागि भू-प्राविधिक सुरक्षा कार्य र "
        "आवश्यक परे स्थानान्तरणबारे छलफल गर्ने"
    ),
}
_DRIVER_ACTION_EN = {
    "Social marginalisation": (
        "socially marginalised (Dalit / Janajati) households carry the most "
        "vulnerability, so targeted participation, skills training and "
        "income-generation are prioritised for them"
    ),
    "Economic status": (
        "the poorest households are the most vulnerable, so alternative "
        "income, grants and livelihood support are concentrated on them"
    ),
    "Forest dependence": (
        "forest dependence is high, so the plan promotes alternative energy "
        "(improved stoves / biogas — to cut firewood demand), stall-feeding "
        "(to cut grazing pressure) and private-forest / agroforestry"
    ),
    "Demographic sensitivity": (
        "female-headed and large households are drawn into social protection "
        "and emergency-preparedness planning"
    ),
    "Physical hazard exposure": (
        "households below landslide-prone slopes get bio-engineering "
        "protection works and, where needed, a relocation discussion"
    ),
}


def _num(v, nd=1):
    try:
        return f"{float(v):.{nd}f}"
    except (TypeError, ValueError):
        return "—"


def _dominant_driver(d: dict[str, Any]) -> tuple[str | None, int]:
    counts = d.get("hh_driver_counts") or []
    best, best_n = None, 0
    for row in counts:
        n = int(row.get("घरधुरी") or 0)
        if n > best_n:
            best, best_n = row.get("कारक"), n
    return best, best_n


def _priority_toles(d: dict[str, Any], k: int = 3) -> list[str]:
    rows = d.get("hh_settlement_rollup_table") or []
    top = [r for r in rows if (r.get("प्राथमिकता") or 0) > 0][:k] or rows[:k]
    return [str(r.get("टोल")) for r in top if r.get("टोल")]


# ── methodology ─────────────────────────────────────────────────────────
def _landslide_decision_note(d: dict[str, Any], lang: str) -> str:
    """The recorded plan decision about the landslide classes (Forest summary > Decisions needed), as one sentence."""
    choice = d.get("decision_landslide_method")
    if choice == "needs_calibration":
        return (
            "समितिले पहिरो वर्गहरू क्यालिब्रेट गर्न (पहिरो सूची वा विशेषज्ञद्वारा) अनुरोध गरेको छ; "
            "त्यसअघि वर्गहरू यही वनको तुलनामा सापेक्ष रहन्छन्।"
            if lang == "ne"
            else "Calibration of the landslide classes (with a landslide inventory or an expert) has been requested; "
            "until then the classes stay relative to this forest."
        )
    if choice == "relative":
        return (
            "पहिरो वर्गहरू यही वनको तुलनामा सापेक्ष राख्ने निर्णय भएको छ।"
            if lang == "ne"
            else "It has been decided to keep the landslide classes relative to this forest."
        )
    return ""


def methodology(d: dict[str, Any], lang: str = "ne") -> str:
    if not d.get("hazard_vuln_available"):
        if lang == "ne":
            return (
                "यस वनका लागि पहिरो संवेदनशीलता विश्लेषण गर्न आवश्यक तथ्याङ्क "
                "(DEM वा भूगर्भ) उपलब्ध नभएकाले जोखिमको अनुमान गरिएको छैन।"
            )
        return (
            "The data (DEM or geology) needed for a landslide-susceptibility "
            "analysis is not available for this forest, so no estimate was made."
        )
    customised = bool(d.get("lsi_customised"))
    fs_on = bool(d.get("fs_enabled"))
    cr = d.get("lsi_consistency_ratio")
    method = d.get("lsi_class_method", "quantile")

    if lang == "ne":
        s = (
            "पहिरो संवेदनशीलता सूचकाङ्क (LSI) भिरालोपन, शिलावर्ग (भूगर्भ), "
            "वक्रता/भू-आर्द्रता (TWI), जलनिकास र सडकसम्मको दूरी, भू-आवरण तथा "
            "भू-आवरण परिवर्तन, मोहडा, वर्षा र माटोको बनावट — यी दश कारकलाई "
            "१–५ मा पुनर्वर्गीकृत गरी भारित योगबाट गणना गरिएको हो। पहिरोको "
            "ऐतिहासिक अभिलेख नभएकाले यो सापेक्ष संवेदनशीलता हो, सम्भाव्यता होइन। "
            f"वर्गीकरण विधि: {method}।"
        )
        if cr is not None:
            s += f" AHP संगति अनुपात CR ≈ {_num(cr, 3)} (< ०.१ स्वीकार्य)।"
        if fs_on:
            note = d.get("fs_scenario_note") or (
                "स्थायित्व गुणांक (FS) अनन्त-ढलान मोडेलबाट, मनसुनी संतृप्त परिदृश्यमा, "
                "अनुमानित रेगोलिथ गहिराइ सहित गणना गरिएको।"
            )
            s += " " + note
        s += (
            " घरधुरी जोखिम अंक = भौतिक प्रकोप एक्सपोजर × सामाजिक-आर्थिक "
            "संवेदनशीलता (आर्थिक अवस्था, सामाजिक सीमान्तीकरण, वन-निर्भरता, "
            "जनसांख्यिक) — प्रत्येक आयाम सामान्यीकृत गरी भारित योग।"
        )
        for a in (d.get("hazard_assumptions") or [])[:4]:
            s += f"\n• {a}"
        if customised:
            s += "\n(यी प्यारामिटर यस वनका लागि समायोजन गरिएका छन्।)"
        note = _landslide_decision_note(d, "ne")
        if note:
            s += "\n" + note
        return s

    s = (
        "The Landslide Susceptibility Index (LSI) is a weighted sum of ten "
        "factors — slope, lithology (geology), curvature / topographic wetness "
        "(TWI), distance to drainage and road, land cover and land-cover "
        "change, aspect, rainfall and soil texture — each reclassed to 1-5. "
        "With no historical landslide inventory this is relative susceptibility, "
        f"not a probability. Classification method: {method}."
    )
    if cr is not None:
        s += f" AHP consistency ratio CR ~ {_num(cr, 3)} (< 0.1 acceptable)."
    if fs_on:
        note = d.get("fs_scenario_note_en") or (
            "The Factor of Safety (FS) is computed from the infinite-slope "
            "model under a saturated-monsoon scenario with an assumed regolith "
            "depth."
        )
        s += " " + note
    s += (
        " The household vulnerability score is physical-hazard exposure x "
        "socio-economic sensitivity (economic status, social marginalisation, "
        "forest dependence, demographics) - each dimension normalised, then a "
        "weighted sum."
    )
    for a in (d.get("hazard_assumptions_en") or [])[:4]:
        s += f"\n- {a}"
    s += "\n" + " ".join(
        CITATIONS[k]
        for k in ("lsi_weights", "lsi_ahp", "infinite_slope", "sovi")
        if k in CITATIONS
    )
    if customised:
        s += "\n(Parameters customised for this forest.)"
    note = _landslide_decision_note(d, "en")
    if note:
        s += "\n" + note
    return s


# ── findings ────────────────────────────────────────────────────────────
def findings(d: dict[str, Any], lang: str = "ne") -> str:
    if not d.get("hazard_vuln_available"):
        return (
            "पहिरो जोखिमको मात्रात्मक अनुमान उपलब्ध छैन।"
            if lang == "ne"
            else "No quantitative landslide-hazard estimate is available."
        )
    prone_ha = d.get("lsi_prone_area_ha")
    prone_pct = d.get("lsi_prone_area_pct", 0)
    hi_units = d.get("lsi_high_units_str", "—")
    fs_unstable = d.get("fs_unstable_pct")
    fs_marginal = d.get("fs_marginal_pct")
    aoi = d.get("hazard_aoi_comparison") or []
    hh_n = d.get("hh_count", 0)
    hh_prio = d.get("hh_priority_count", 0)
    hh_informative = d.get("hh_hazard_layer_informative")
    coord_src = d.get("hh_coord_source", "survey")
    on_buildings = d.get("hh_basis") == "buildings"
    # quantile / equal-interval classes are relative to this forest; only fixed thresholds mean something absolute
    relative = d.get("lsi_class_method", "quantile") != "fixed"
    driver, driver_n = _dominant_driver(d)

    cf_row = next((r for r in aoi if "सामुदायिक" in str(r.get("क्षेत्र", ""))), None)
    ug_only_row = next((r for r in aoi if "बाहिर" in str(r.get("क्षेत्र", ""))), None)

    if lang == "ne":
        s = (
            f"समुदायिक वनको लगभग {_num(prone_pct)}% क्षेत्रफल ({_num(prone_ha, 0)} "
            "हेक्टर) उच्च वा अति-उच्च पहिरो संवेदनशीलता वर्गमा पर्छ।"
        )
        if relative:
            s += (
                " (यो वर्गीकरण यही वनभित्रको सापेक्ष क्रम हो — प्रत्येक वर्गमा करिब बराबर क्षेत्रफल पर्छ — "
                "त्यसैले यसले पूर्ण जोखिम होइन, वनका भागहरूको तुलनात्मक क्रम मात्र देखाउँछ।)"
            )
        if hi_units and hi_units != "—":
            s += f" सबैभन्दा बढी संवेदनशील एकाइहरू: {hi_units}।"
        if d.get("fs_enabled"):
            s += (
                f" मनसुनी संतृप्त परिदृश्यमा वन क्षेत्रफलको {_num(fs_marginal)}% "
                f"सीमान्त स्थायित्व र {_num(fs_unstable)}% अस्थिर देखिन्छ।"
            )
        if cf_row and ug_only_row:
            s += (
                f" वन बाहिरको बस्ती भूमिको {_num(ug_only_row.get('सापेक्ष_उच्च_%'))}% "
                f"सापेक्ष रूपमा उच्च संवेदनशील वर्गमा पर्छ (वनभित्रको {_num(cf_row.get('सापेक्ष_उच्च_%'))}% सँग "
                "तुलनायोग्य)।"
            )
        if hh_n:
            s += (
                f" भू-निर्देशांकित {_num(hh_n, 0)} घरधुरीमध्ये {_num(hh_prio, 0)} "
                "घरधुरी उच्च जोखिममा वर्गीकृत।"
            )
            if driver:
                dn = {
                    "Social marginalisation": "सामाजिक सीमान्तीकरण",
                    "Economic status": "आर्थिक अवस्था",
                    "Forest dependence": "वन निर्भरता",
                    "Demographic sensitivity": "जनसांख्यिक संवेदनशीलता",
                    "Physical hazard exposure": "भौतिक प्रकोप एक्सपोजर",
                }.get(driver, driver)
                s += f" धेरैजसो घरधुरीको प्रमुख जोखिम कारक {dn} हो।"
            if on_buildings:
                s += (
                    " (घरधुरी विवरण उपलब्ध नभएकाले प्रत्येक भवन खाकालाई एक घरधुरी मानिएको छ; "
                    "त्यसैले क्रमबद्धता भौतिक प्रकोप जोखिममा मात्र आधारित छ।)"
                )
            elif coord_src == "mixed":
                s += (
                    " (सर्वेक्षण निर्देशांक संकलन गरिएका घरधुरीमा ती नै प्रयोग गरिएको छ; "
                    "निर्देशांक नभएका घरधुरीलाई उसको बस्तीको भवन खाकाबाट प्रतिनिधि बिन्दुमा राखिएको छ।)"
                )
            elif coord_src in ("building_footprint", "settlement_centroid"):
                s += (
                    " (घरधुरीलाई सर्वेक्षण निर्देशांकको सट्टा प्रत्येक "
                    "घरधुरीलाई उसको बस्तीको भवन खाकाबाट प्रतिनिधि बिन्दुमा राखिएको छ; "
                    "त्यसैले भौतिक प्रकोपको क्रमबद्धता बस्ती स्तरको हो।)"
                )
            elif hh_informative is False:
                s += (
                    " (घरधुरीका निर्देशांक पर्याप्त सटीक नभएकाले भौतिक प्रकोप "
                    "तहले घरधुरीबीच विभेद गर्न सकेन — माथिको क्रमबद्धता "
                    "सामाजिक-आर्थिक संवेदनशीलतामा आधारित छ।)"
                )
        return s

    s = (
        f"About {_num(prone_pct)}% of the community forest ({_num(prone_ha, 0)} "
        "ha) falls in the High or Very-High landslide-susceptibility class."
    )
    if relative:
        s += (
            " (This classification ranks the parts of THIS forest against each other - each class holds about the "
            "same area - so it shows relative order, not absolute hazard.)"
        )
    if hi_units and hi_units != "—":
        s += f" The most susceptible units are: {hi_units}."
    if d.get("fs_enabled"):
        s += (
            f" Under a saturated-monsoon scenario, {_num(fs_marginal)}% of the "
            f"forest is marginally stable and {_num(fs_unstable)}% unstable."
        )
    if cf_row and ug_only_row:
        s += (
            f" On the settlement land outside the forest, "
            f"{_num(ug_only_row.get('सापेक्ष_उच्च_%'))}% falls in the relatively high-susceptibility class "
            f"(vs {_num(cf_row.get('सापेक्ष_उच्च_%'))}% inside the forest)."
        )
    if hh_n:
        s += (
            f" Of {_num(hh_n, 0)} geocoded households, {_num(hh_prio, 0)} are "
            "classified high-vulnerability."
        )
        if driver:
            s += f" The dominant vulnerability driver for most households is {driver.lower()}."
        if on_buildings:
            s += (
                " (No household data was available, so each building footprint was treated as one "
                "household — the ranking reflects physical hazard exposure only.)"
            )
        elif coord_src == "mixed":
            s += (
                " (Households with surveyed coordinates use them; the others "
                "were placed at a representative building in their settlement.)"
            )
        elif coord_src in ("building_footprint", "settlement_centroid"):
            s += (
                " (Household survey coordinates are not used, so each "
                "household was placed at a representative building in its "
                "settlement — the physical-hazard ranking is therefore at "
                "settlement granularity.)"
            )
        elif hh_informative is False:
            s += (
                " (Household coordinates were not precise enough for the "
                "physical-hazard layer to discriminate between households, so "
                "the ranking above reflects socio-economic vulnerability only.)"
            )
    return s


# ── prescription ────────────────────────────────────────────────────────
def prescription(d: dict[str, Any], lang: str = "ne") -> str:
    if not d.get("hazard_vuln_available"):
        return (
            "पहिरो जोखिम न्यूनीकरणका लागि सामान्य असल अभ्यास (भिरालोमा कटान "
            "नियन्त्रण, भू-प्राविधिक कार्य, भुइँ-आवरण संरक्षण) अपनाइनेछ।"
            if lang == "ne"
            else "General good practice for landslide-risk reduction (limit "
            "harvesting on steep slopes, bio-engineering, retain ground cover) "
            "will be followed."
        )
    prone_pct = d.get("lsi_prone_area_pct", 0)
    absolute = d.get("lsi_class_method", "quantile") == "fixed"
    hi_units = d.get("lsi_high_units_str", "—")
    fs_unstable = d.get("fs_unstable_pct") or 0
    fs_marginal = d.get("fs_marginal_pct") or 0
    toles = _priority_toles(d)
    driver, _ = _dominant_driver(d)
    aoi = d.get("hazard_aoi_comparison") or []
    cf_row = next((r for r in aoi if "सामुदायिक" in str(r.get("क्षेत्र", ""))), None)
    ug_only_row = next((r for r in aoi if "बाहिर" in str(r.get("क्षेत्र", ""))), None)

    if lang == "ne":
        s = "कार्ययोजनाले पहिरो जोखिम घटाउन:"
        if hi_units and hi_units != "—":
            s += (
                f" उच्च-संवेदनशीलता एकाइहरू ({hi_units}) मा कटान रोक्ने वा "
                "छनौट-कटानमात्र गर्ने, भिरालो भागमा भू-प्राविधिक कार्य (चेक ड्याम, "
                "ग्याबिन, समोच्च खाल्डो, वनस्पति-बल्ली) लागू गर्ने।"
            )
        if fs_unstable > 0 or fs_marginal >= 10:
            s += (
                " मनसुनमा अस्थिर/सीमान्त देखिएका ढलानमा गल्ली उपचार, सतही पानी "
                "निकास व्यवस्थापन र माटो-अवरोधक रोपण प्राथमिकतासाथ गर्ने।"
            )
        if prone_pct >= 25 and absolute:
            s += " वन क्षेत्रफलको ठूलो भाग पहिरो-प्रवण भएकाले जोखिम नक्सालाई वार्षिक कार्यतालिकामा एकीकृत गर्ने।"
        if driver in _DRIVER_ACTION_NE:
            s += f" घरधुरी जोखिम सम्बोधनमा — {_DRIVER_ACTION_NE[driver]}।"
        if toles:
            s += (
                f" प्राथमिकता टोलहरू ({' · '.join(toles)}) लाई माथिका कार्यक्रममा "
                "पहिलो चरणमा समेट्ने।"
            )
        if (
            cf_row
            and ug_only_row
            and (ug_only_row.get("सापेक्ष_उच्च_%") or 0)
            >= (cf_row.get("सापेक्ष_उच्च_%") or 0)
        ):
            s += (
                " वन बाहिरको बस्ती भूमिमा पनि जोखिम उच्च भएकाले उपभोक्ता "
                "समूहसँग मिलेर भू-संरक्षण र वैकल्पिक जीविकोपार्जन कार्यक्रम "
                "त्यस भूमिमा विस्तार गर्ने।"
            )
        return s

    s = "To reduce landslide risk the plan will:"
    if hi_units and hi_units != "—":
        s += (
            f" on the high-susceptibility units ({hi_units}), halt felling or "
            "allow selection felling only, and apply bio-engineering (check "
            "dams, gabions, contour trenches, live staking) on the steep "
            "portions;"
        )
    if fs_unstable > 0 or fs_marginal >= 10:
        s += (
            " on the slopes that read unstable / marginal in the monsoon "
            "scenario, prioritise gully treatment, surface-water drainage and "
            "soil-binding planting;"
        )
    if prone_pct >= 25 and absolute:
        s += (
            " because a large share of the forest is landslide-prone, fold the "
            "hazard map into the annual operations schedule;"
        )
    if driver in _DRIVER_ACTION_EN:
        s += f" for the household dimension, {_DRIVER_ACTION_EN[driver]};"
    if toles:
        s += f" the priority toles ({' · '.join(toles)}) are addressed first."
    if (
        cf_row
        and ug_only_row
        and (ug_only_row.get("सापेक्ष_उच्च_%") or 0)
        >= (cf_row.get("सापेक्ष_उच्च_%") or 0)
    ):
        s += (
            " Since the settlement land outside the forest is also hazard-prone, "
            "the user group will extend soil-conservation and alternative-"
            "livelihood work onto that land."
        )
    return s


def all_narration(d: dict[str, Any]) -> dict[str, str]:
    """The six keys merged into ``get_hazard_vuln_data``'s output."""
    return {
        "hazard_methodology_narration": methodology(d, "ne"),
        "hazard_methodology_narration_en": methodology(d, "en"),
        "hazard_findings_narration": findings(d, "ne"),
        "hazard_findings_narration_en": findings(d, "en"),
        "hazard_prescription_narration": prescription(d, "ne"),
        "hazard_prescription_narration_en": prescription(d, "en"),
    }


__all__ = ["methodology", "findings", "prescription", "all_narration"]
