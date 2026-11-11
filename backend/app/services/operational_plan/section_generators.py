"""Section content generators for the Operational Plan document tree.

Produces text content for every section of the OP document by reading
collected raw data. Each generator function returns a formatted Nepali
or English string ready for DOCX insertion. Covers basic info, forest
description, land cover, biodiversity, yearly activities, and more.
# business: CFMG — section narrative generators for OP document
# why: Nepali text generated from structured data using templates
# NOTE: falls back to English if Nepali data unavailable

Entry point:
    collect_section_content() — populates all sections from raw_data.

See also:
    .household_section_generators — sub-generators for household sections
    .variable_resolver — resolves {{variable}} patterns in generated content
"""

from typing import Any, Dict, Optional
from collections import Counter
from app.utils.number_format import format_devanagari as fmt
from .household_section_generators import (
    generate_household_narration,
    generate_committee_narration,
    generate_user_group_narration,
    generate_demand_supply_narration,
)
import logging

logger = logging.getLogger(__name__)


def _dim_label_np(raw_data: dict) -> str:
    """Return mode-aware Nepali label from dimension section.

    Returns 'ब्लक' in block mode, 'कम्पार्टमेन्ट' in compartment mode.
    Falls back to 'ब्लक' if no dimension data found (legacy OP cache).
    """
    return raw_data.get("dimension", {}).get("unit_label_np", "ब्लक")


# NOTE: falls back to default if any intermediate key is missing
def _deep_get(data: dict, path: str, default: Any = None) -> Any:
    current = data
    for key in path.split("."):
        if isinstance(current, dict):
            current = current.get(key)
        else:
            return default
        if current is None:
            return default
    return current


def _get_rd(raw_data: dict) -> dict:
    return raw_data.get("result_data", {})


def _bi(raw_data: dict) -> dict:
    return raw_data.get("basic_info", {})


def _ra(raw_data: dict) -> dict:
    return raw_data.get("raster_analysis", {})


# business: forest summary — first section of OP document
# ─── 1. Forest Summary ──────────────────────────────────────────
def generate_forest_summary(raw_data: dict) -> Optional[str]:
    """Generate forest summary section with area, blocks, elevation, carbon, and health."""
    bi = _bi(raw_data)
    raster = _ra(raw_data)
    rd = _get_rd(raw_data)
    blocks = raw_data.get("blocks", {})
    area = bi.get("effective_area_hectares") or bi.get("total_area_hectares") or 0
    bc = rd.get("total_blocks") or blocks.get("total_blocks") or 0
    elev = _deep_get(raster, "elevation.mean_m", 0)
    carbon_mg = _deep_get(raster, "biomass.carbon_stock", 0)
    forest_health = _deep_get(raster, "forest_health.dominant", "")
    HEALTH_MAP = {
        "good": "राम्रो", "fair": "मध्यम", "poor": "कमजोर",
        "degraded": "क्षरित", "very_good": "धेरै राम्रो",
    }
    health_np = HEALTH_MAP.get(forest_health, forest_health or "—")
    if not area and not bc and not elev:
        return None
    return (
        f"यस वनको कुल क्षेत्रफल {fmt(area)} हेक्टर रहेको छ। "
        f"यस वनमा {fmt(bc, 0)} वटा वन खण्डहरू रहेका छन्। "
        f"वनको औसत उचाइ {fmt(elev, 0)} मिटर रहेको छ। "
        f"कुल कार्बन भण्डार {fmt(carbon_mg)} मेगाग्राम रहेको छ। "
        f"वन स्वास्थ्य \"{health_np}\" अवस्थामा रहेको छ।"
    )


# business: 5-class slope classification per CFMG standards
# ─── 2. Slope Analysis ──────────────────────────────────────────
def generate_slope_analysis(raw_data: dict) -> Optional[str]:
    """Generate slope analysis section with dominant class and five-class breakdown."""
    raster = _ra(raw_data)
    slope = raster.get("slope", {})

    dominant = slope.get("dominant_class", "")
    percentages = slope.get("percentages", {})
    if not dominant and not percentages:
        return None
    SLOPE_MAP = {
        "flat": "समतल (Flat)", "gentle": "हल्का (Gentle)",
        "moderate": "मध्यम (Moderate)", "steep": "भिरालो (Steep)",
        "very_steep": "अति भिरालो (Very Steep)",
    }
    dominant_np = SLOPE_MAP.get(dominant, dominant or "—")
    dom_pct = percentages.get(dominant, 0)
    return (
        f"यस वनको प्रमुख भिरालो \"{dominant_np}\" वर्ग रहेको छ, "
        f"जसले कुल क्षेत्रफलको {fmt(dom_pct, 1)}% ओगटेको छ। "
        f"भिरालोको आधारमा जमिनलाई पाँच वर्गमा बाँडिएको छ: समतल (Flat), "
        f"हल्का (Gentle), मध्यम (Moderate), भिरालो (Steep), र अति भिरालो (Very Steep)। "
        f"हल्का भिरालो जमिनमा सजिलै नमुना प्लट राख्न सकिन्छ भने "
        f"भिरालो र अति भिरालो जमिनमा नमुना सङ्कलन गर्न कठिनाई हुन्छ।"
    )


# ─── 3. Elevation Profile ───────────────────────────────────────
def generate_elevation_profile(raw_data: dict) -> Optional[str]:
    """Generate elevation profile section with mean, min, and max elevation."""
    raster = _ra(raw_data)
    elev = raster.get("elevation", {})
    mean = elev.get("mean_m", 0)
    min_ = elev.get("min_m", 0)
    max_ = elev.get("max_m", 0)
    if not mean and not min_ and not max_:
        return None
    range_val = max_ - min_
    return (
        f"यस वनको औसत उचाइ {fmt(mean, 0)} मिटर रहेको छ। "
        f"न्यूनतम उचाइ {fmt(min_, 0)} मिटर र अधिकतम उचाइ {fmt(max_, 0)} मिटर रहेको छ। "
        f"उचाइको फरक {fmt(range_val, 0)} मिटर रहेको छ, जसले यस वनमा "
        f"विविध वनस्पति तथा वातावरणीय अवस्था रहेको संकेत गर्दछ।"
    )


# ─── 4. Aspect Analysis ─────────────────────────────────────────
def generate_aspect_analysis(raw_data: dict) -> Optional[str]:
    """Generate aspect analysis section with dominant direction."""
    raster = _ra(raw_data)
    aspect = raster.get("aspect", {})
    dominant = aspect.get("dominant", "")
    if not dominant:
        return None
    ASPECT_MAP = {
        "N": "उत्तर (North)", "NE": "उत्तर-पूर्व (North-East)",
        "E": "पूर्व (East)", "SE": "दक्षिण-पूर्व (South-East)",
        "S": "दक्षिण (South)", "SW": "दक्षिण-पश्चिम (South-West)",
        "W": "पश्चिम (West)", "NW": "उत्तर-पश्चिम (North-West)",
    }
    dominant_np = ASPECT_MAP.get(dominant, dominant or "—")
    return (
        f"यस वनको प्रमुख दिशा \"{dominant_np}\" रहेको छ। "
        f"दिशा (Aspect) ले भिरालो कुन दिशातिर फर्केको छ भन्ने देखाउँदछ। "
        f"दक्षिणतर्फ फर्केको भिरालोमा घाम बढी लाग्छ भने उत्तरतर्फ फर्केको भिरालोमा चिसो हुन्छ।"
    )


# ─── 5. Forest Health ───────────────────────────────────────────
def generate_forest_health(raw_data: dict) -> Optional[str]:
    """Generate forest health section with dominant NDVI-based class distribution."""
    raster = _ra(raw_data)
    fh = raster.get("forest_health", {})
    dominant = fh.get("dominant", "")
    percentages = fh.get("percentages", {})
    if not dominant and not percentages:
        return None
    HEALTH_MAP = {
        "excellent": "उत्कृष्ट", "good": "राम्रो",
        "fair": "मध्यम", "poor": "कमजोर", "degraded": "क्षरित",
        "stressed": "तनावग्रस्त",
    }
    dominant_np = HEALTH_MAP.get(dominant, dominant or "—")
    dom_pct = percentages.get(dominant, 0)
    return (
        f"यस वनको समग्र स्वास्थ्य अवस्था \"{dominant_np}\" रहेको छ, "
        f"जसले कुल क्षेत्रफलको {fmt(dom_pct, 1)}% ओगटेको छ। "
        f"वन स्वास्थ्यलाई NDVI (Normalized Difference Vegetation Index) को आधारमा "
        f"पाँच वर्गमा विभाजन गरिएको छ: उत्कृष्ट (Excellent), राम्रो (Good), "
        f"मध्यम (Moderate), कमजोर (Poor), र क्षरित (Degraded)।"
    )


# ─── 6. Forest Type ─────────────────────────────────────────────
def generate_forest_type(raw_data: dict) -> Optional[str]:
    """Generate forest type section with dominant FRTC classification."""
    raster = _ra(raw_data)
    ft = raster.get("forest_type", {})
    dominant = ft.get("dominant", "")
    if not dominant:
        return None
    return (
        f"यस वनको प्रमुख वन प्रकार \"{dominant}\" रहेको छ। "
        f"नेपालको FRTC (Forest Resource and Training Centre) वर्गीकरण प्रणाली "
        f"अनुसार यस वनमा विभिन्न प्रकारका वनहरू पाइन्छन्।"
    )


# ─── 7. Potential Species ───────────────────────────────────────
def generate_potential_species(raw_data: dict) -> Optional[str]:
    """Generate potential species section grouped by role and forest type."""
    species = raw_data.get("species", {})
    species_list = species.get("species_list", [])
    if not species_list or not isinstance(species_list, list):
        return None
    total = len(species_list)
    by_role: Dict[str, list] = {}
    by_ft: Dict[str, list] = {}
    for s in species_list:
        role = s.get("role", "Associate")
        name = s.get("local_name") or s.get("scientific_name", "")
        by_role.setdefault(role, []).append(name)
        for ft in (s.get("forest_types") or []):
            by_ft.setdefault(ft, []).append(name)

    role_order = ["Dominant", "Co-dominant", "Associate", "Occasional", "Rare"]
    role_labels = {
        "Dominant": "प्रमुख प्रजाती", "Co-dominant": "सह-प्रमुख प्रजाती",
        "Associate": "सहयोगी प्रजाती", "Occasional": "विरलै हुने प्रजाती",
        "Rare": "दुर्लभ प्रजाती",
    }
    role_lines = []
    for r in role_order:
        names = by_role.get(r, [])
        if names:
            role_lines.append(f"• {role_labels[r]}: {', '.join(names)}")
    role_text = "\n".join(role_lines) if role_lines else ""

    ft_lines = [
        f"• {ft}: {len(names)} प्रजातिहरू"
        for ft, names in sorted(by_ft.items(), key=lambda x: -len(x[1]))
    ]
    ft_text = "\n".join(ft_lines) if ft_lines else ""

    return (
        f"यस वनको वन प्रकार अनुसार जम्मा {fmt(total, 0)} प्रजातिका रूखहरू "
        f"सम्भावित रूपमा पाउन सकिन्छ। यस क्षेत्रमा वृक्षारोपण गर्न सकिने प्रजाती "
        f"छनोट गर्दा यि प्रजातीलाइ प्राथमिकता दिन सकिन्छ।\n\n"
        f"वन प्रकार अनुसार:\n{ft_text}\n\n"
        f"भूमिका अनुसार प्रजातिहरू:\n{role_text}"
    )


# ─── 8. Actual Species (from field inventory) ────────────────────
def generate_actual_species(raw_data: dict) -> Optional[str]:
    """Generate actual species section from field inventory data listing top species per hectare."""
    fi = raw_data.get("field_inventory", {})
    if not fi.get("available"):
        return None
    species_block = fi.get("fi_species_block_growing_stock", [])
    if not species_block:
        return None
    per_species: Dict[str, dict] = {}
    for row in species_block:
        sci = row.get("species_scientific", "")
        loc = row.get("species_local", "") or sci
        if sci not in per_species:
            per_species[sci] = {"loc": loc, "count": 0.0}
        per_species[sci]["count"] += row.get("count_per_ha", 0)
    total_sp = len(per_species)
    sorted_sp = sorted(per_species.values(), key=lambda x: -x["count"])
    top = [f"• {s['loc']}: {fmt(s['count'], 0)} /ha" for s in sorted_sp[:10]]
    top_text = "\n".join(top)
    return (
        f"यस वनको स्थलगत सर्वेक्षणबाट जम्मा {fmt(total_sp, 0)} प्रजातिका "
        f"रूखहरू फेला परेका छन्। प्रमुख प्रजातिहरू:\n{top_text}"
    )


# business: biodiversity narrative from species richness + Shannon index
# ─── 9. Biodiversity ─────────────────────────────────────────────
def generate_biodiversity(raw_data: dict) -> Optional[str]:
    """Generate biodiversity section with species counts, categories, and IUCN status."""
    bio = raw_data.get("biodiversity", {})
    if not bio.get("available"):
        return None

    total = bio.get("total_species", 0)
    if not total:
        return None

    veg_count = bio.get("vegetation_count", 0)
    animal_count = bio.get("animal_count", 0)
    protected_count = bio.get("protected_count", 0)
    invasive_count = bio.get("invasive_count", 0)

    sub_category_breakdown = bio.get("sub_category_breakdown", {})
    iucn_breakdown = bio.get("iucn_breakdown", {})

    cat_list = "\n".join(
        f"• {cat}: {fmt(cnt, 0)}" for cat, cnt in
        sorted(sub_category_breakdown.items(), key=lambda x: -x[1])
    )

    iucn_order = ["CR", "EN", "VU", "NT", "LC", "DD"]
    iucn_labels = {
        "CR": "संकटग्रस्त", "EN": "लोपोन्मुख", "VU": "असुरक्षित",
        "NT": "नजिकै खतरा", "LC": "कम चासो", "DD": "अपर्याप्त",
    }
    iucn_list = "\n".join(
        f"• {iucn_labels.get(ic, ic)}: {fmt(iucn_breakdown.get(ic, 0), 0)}"
        for ic in iucn_order if iucn_breakdown.get(ic, 0) > 0
    )

    parts = [f"यस वनको जैविक विविधता अन्तर्गत जम्मा {fmt(total, 0)} प्रजातिहरू पाइन्छन्।"]

    veg_animal_parts = []
    if veg_count:
        veg_animal_parts.append(f"वनस्पति प्रजाति {fmt(veg_count, 0)}")
    if animal_count:
        veg_animal_parts.append(f"जनावर प्रजाति {fmt(animal_count, 0)}")
    if veg_animal_parts:
        parts[0] += " " + " र ".join(veg_animal_parts) + " रहेका छन्।"
    else:
        parts[0] = parts[0].rstrip("।") + "।"

    if protected_count:
        parts.append(f"संरक्षित प्रजाति {fmt(protected_count, 0)} रहेका छन्।")
    if invasive_count:
        parts.append(f"मिचाहा प्रजाति {fmt(invasive_count, 0)} रहेका छन्।")
    if cat_list:
        parts.append(f"\nप्रकार अनुसार:\n{cat_list}")
    if iucn_list:
        parts.append(f"\nसंरक्षण स्थिति अनुसार:\n{iucn_list}")

    return "\n\n".join(parts)


# ─── 10. Canopy Structure ───────────────────────────────────────
def generate_canopy_structure(raw_data: dict) -> Optional[str]:
    """Generate canopy structure section with dominant class and mean height."""
    raster = _ra(raw_data)
    canopy = raster.get("canopy", {})
    dominant = canopy.get("dominant_class", "")
    mean_h = canopy.get("mean_m", 0)
    if not dominant and not mean_h:
        return None
    CANOPY_MAP = {
        "non_forest": "गैर-वन", "regeneration": "पुनरुत्थान",
        "pole_trees": "पोल रूख", "tree": "रूख",
    }
    dominant_np = CANOPY_MAP.get(dominant, dominant or "—")
    return (
        f"यस वनको प्रमुख वन छत्र वर्ग \"{dominant_np}\" रहेको छ। "
        f"वन छत्रको औसत उचाइ {fmt(mean_h, 1)} मिटर रहेको छ। "
        f"वन छत्रले वनको संरचना र रूखको घनत्व देखाउँदछ।"
    )


# ─── 11. Biomass & Carbon ────────────────────────────────────────
def generate_biomass_carbon(raw_data: dict) -> Optional[str]:
    """Generate biomass and carbon stock section with AGB and carbon storage."""
    raster = _ra(raw_data)
    biomass = raster.get("biomass", {})
    agb_mean = biomass.get("agb_mean", 0)
    agb_total = biomass.get("agb_total", 0)
    carbon = biomass.get("carbon_stock", 0)
    if not agb_mean and not agb_total:
        return None
    return (
        f"यस वनको कुल वायवीय जैविक पदार्थ (Above Ground Biomass) "
        f"{fmt(agb_total)} मेगाग्राम रहेको छ। प्रतिहेक्टर औसत {fmt(agb_mean, 1)} "
        f"मेगाग्राम रहेको छ। कुल कार्बन भण्डार (AGB को ५०%) {fmt(carbon)} "
        f"मेगाग्राम रहेको छ। कार्बन भण्डारले वनले वातावरणमा रहेको कार्बनलाई "
        f"कति मात्रामा सोसेर राखेको छ भन्ने देखाउँदछ।"
    )


# ─── 12. Climate Conditions ──────────────────────────────────────
def generate_climate_conditions(raw_data: dict) -> Optional[str]:
    """Generate climate conditions section with temperature and precipitation data."""
    raster = _ra(raw_data)
    temp = _deep_get(raster, "temperature.mean_c", 0)
    precip = _deep_get(raster, "precipitation.mean_mm", 0)
    if not temp and not precip:
        return None
    return (
        f"यस वनको वार्षिक औसत तापक्रम {fmt(temp, 1)}°C रहेको छ। "
        f"वार्षिक औसत वर्षा {fmt(precip, 0)} मिलिमिटर रहेको छ। "
        f"यी मौसमी अवस्थाहरूले यस वनको वनस्पति, माटो र समग्र "
        f"पारिस्थितिकी प्रणालीलाई प्रभाव पार्दछन्।"
    )


# ─── 13. Land Cover ─────────────────────────────────────────────
def generate_land_cover(raw_data: dict) -> Optional[str]:
    """Generate land cover section with dominant cover type description."""
    raster = _ra(raw_data)
    lc = raster.get("landcover", {})
    dominant = lc.get("dominant", "")
    if not dominant:
        return None
    return (
        f"यस वनको प्रमुख भू-आवरण \"{dominant}\" रहेको छ। भू-आवरणले जमिनको "
        f"प्रयोग र प्राकृतिक अवस्था देखाउँदछ। यस वनमा रूख आवरण (Tree Cover), "
        f"झाडी (Shrubland), घाँसे मैदान (Grassland), खेती योग्य (Cropland), "
        f"बस्ती (Built-up), पानी (Water) लगायत विभिन्न प्रकारका भू-आवरणहरू पाइन्छन्।"
    )


# ─── 13b. Land use in 1984 (historical background) ───────────────
def generate_land_cover_1984(raw_data: dict) -> Optional[str]:
    """The 1984 land use of the forest, from the 1984 topographic-sheet polygons (the layer the 1984 map draws).

    Says what the land was then, class by class, and how it compares with the forest cover today when both are known."""
    from app.core.landcover_1984 import LC1984_LABELS

    hist = _ra(raw_data).get("landcover_historical", {}) or {}
    pct = hist.get("landcover_1984_percentages") or {}
    if not isinstance(pct, dict) or not any(v for v in pct.values()):
        return None
    area = hist.get("landcover_1984_area_ha") or {}
    ne = lambda k: (LC1984_LABELS.get(k) or {}).get("ne") or k  # noqa: E731
    ordered = sorted(((k, v) for k, v in pct.items() if v), key=lambda kv: -kv[1])
    dominant = hist.get("landcover_1984_dominant") or ordered[0][0]
    parts = []
    for k, v in ordered:
        a = area.get(k)
        parts.append(f"{ne(k)} {fmt(v, 2)}%" + (f" ({fmt(a, 2)} हेक्टर)" if a else ""))
    text = (
        f"सन् १९८४ को स्थलगत नक्सा (टोपोसिट) अनुसार यस वनको प्रमुख भू-उपयोग \"{ne(dominant)}\" रहेको थियो। "
        f"त्यस बखतको भू-उपयोग: " + "; ".join(parts) + "।"
    )
    forest_1984 = pct.get("Forest")
    if forest_1984:
        text += f" त्यस समयमा वन क्षेत्र कुल क्षेत्रफलको {fmt(forest_1984, 2)}% थियो।"
    return text


# ─── 13c. Non-timber forest products (NTFP) ──────────────────────
def generate_ntfp(raw_data: dict) -> Optional[str]:
    """Non-timber forest product species recorded in this forest (medicinal, fruit, fodder, fibre, spice, aromatic...)."""
    from app.core.ntfp import breakdown_by_part, ntfp_species

    rows = ntfp_species((raw_data.get("biodiversity") or {}).get("vegetation") or [])
    if not rows:
        return None
    by_part = breakdown_by_part(rows)
    breakdown = ", ".join(f"{p} {fmt(n, 0)}" for p, n in sorted(by_part.items(), key=lambda kv: -kv[1]))
    return (
        f"यस वनमा अभिलेख गरिएका वनस्पतिमध्ये {fmt(len(rows), 0)} प्रजाति वन नियमावली, २०७९ को अनुसूची-७ मा तोकिएका "
        f"गैरकाष्ठ वन पैदावार (जडीबुटी) हुन्। संकलन गरिने भाग अनुसारको संख्या: {breakdown}। "
        f"प्रजातिहरूको विवरण र तोकिएको मूल्य दर तालिकामा दिइएको छ।"
    )


# ─── 13d. NTFP inventory results (optional page) ─────────────────
def generate_ntfp_inventory(raw_data: dict) -> Optional[str]:
    """The NTFP resource survey: how many species were surveyed and which stand out. None unless NTFP records exist."""
    from app.services.operational_plan.ntfp_inventory_op import narrative

    return narrative(raw_data.get("ntfp_inventory") or {})


# ─── 14. Forest Loss ────────────────────────────────────────────
def generate_forest_loss(raw_data: dict) -> Optional[str]:
    """Generate forest loss section with Hansen-based historical loss area."""
    raster = _ra(raw_data)
    fl = raster.get("forest_loss_gain", {})
    loss_ha = fl.get("loss_hectares", 0)
    rd = _get_rd(raw_data)
    area = rd.get("area_hectares", 0) or _bi(raw_data).get("total_area_hectares", 0)
    if not loss_ha:
        loss_ha = rd.get("forest_loss_hectares", 0)
    if not loss_ha:
        return None
    pct = (loss_ha / area * 100) if area else 0
    return (
        f"सन् २००१ देखि २०२४ सम्म यस वनको कुल {fmt(loss_ha, 2)} हेक्टर "
        f"({fmt(pct, 1)}%) क्षेत्रमा वन क्षति भएको छ। यो जानकारी "
        f"Hansen Global Forest Change डाटाबाट प्राप्त गरिएको हो। "
        f"वन क्षति मुख्यतया मानवीय क्रियाकलाप, आगलागी र प्राकृतिक कारणले हुने गर्दछ।"
    )


# ─── 15. Fire Loss ──────────────────────────────────────────────
def generate_fire_loss(raw_data: dict) -> Optional[str]:
    """Generate fire loss section with area damaged by historical fires."""
    rd = _get_rd(raw_data)
    loss_ha = rd.get("fire_loss_hectares", 0)
    if not loss_ha:
        return None
    area = rd.get("area_hectares", 0) or _bi(raw_data).get("total_area_hectares", 0)
    pct = (loss_ha / area * 100) if area else 0
    return (
        f"सन् २००१ देखि २०२४ सम्म यस वनको कुल {fmt(loss_ha, 2)} हेक्टर "
        f"({fmt(pct, 1)}%) क्षेत्र आगलागीबाट क्षतिग्रस्त भएको छ। "
        f"आगलागी वनको लागि प्रमुख जोखिम हो, जसले वनस्पति, वन्यजन्तु "
        f"र माटोको गुणस्तरमा गम्भीर असर पार्दछ।"
    )


# constraint: forest quality classes mapped to Nepali per CFMG §4
# ─── 16. Forest Quality (NASA 2020) ─────────────────────────────
def generate_forest_quality(raw_data: dict) -> Optional[str]:
    """Generate forest quality section with NASA-based primary/secondary forest breakdown."""
    rd = _get_rd(raw_data)
    pct = rd.get("whole_nasa_forest_2020_percentages", {})
    dominant = rd.get("whole_nasa_forest_2020_dominant", "")
    if not pct or not isinstance(pct, dict) or not any(v for v in pct.values()):
        return None
    QUALITY_NP = {
        "Primary Forest": "प्राथमिक वन",
        "Young Secondary Forest": "कम उमेरको दोस्रो पुस्ताको वन",
        "Old Secondary Forest": "पुरानो दोस्रो पुस्ताको वन",
    }
    entries = sorted(
        [(k, v) for k, v in pct.items() if v > 0],
        key=lambda x: -x[1]
    )
    dominant_np = QUALITY_NP.get(dominant, dominant or "—")
    parts = []
    for k, v in entries:
        np = QUALITY_NP.get(k, k)
        desc = (
            "पुरानो वन, सर्वाधिक कार्बन" if "primary" in k.lower()
            else "पुनरुत्थान हुँदै गरेको, कम कार्बन" if "young" in k.lower()
            else "परिपक्क दोस्रो पुस्ताको वन, मध्यम कार्बन" if "old" in k.lower()
            else ""
        )
        parts.append(f"{np} {fmt(v, 1)}% ({desc})")
    breakdown = ", ".join(parts)
    area = rd.get("area_hectares", 0)
    primary_pct = pct.get("Primary Forest", 0) if isinstance(pct, dict) else 0
    primary_area = (area * primary_pct / 100) if area else None
    area_note = (
        f"यस वनको करिब {fmt(primary_area, 2)} हेक्टर क्षेत्र प्राथमिक वनले "
        f"ढाकेको छ, जुन कार्बन भण्डारणको दृष्टिले अत्यन्त महत्वपूर्ण छ।"
    ) if primary_area else ""
    return (
        f"यस वनको प्रमुख वन गुणस्तर \"{dominant_np}\" रहेको छ। वन गुणस्तर "
        f"वितरण यस प्रकार रहेको छ: {breakdown}।\n\n"
        f"प्राथमिक वन (Primary Forest) पुरानो तथा अत्यधिक कार्बन भण्डार भएको "
        f"वन हो। प्राथमिक वनले दोस्रो पुस्ताको वनको तुलनामा २ देखि ३ गुणा बढी "
        f"कार्बन भण्डारण गर्न सक्दछ। {area_note} यो तथ्यांक नासा (NASA/ORNL DAAC) "
        f"३० मिटर रिजोलुसनको २०२० सालको उपग्रह तथ्यांकमा आधारित छ।"
    )


# ─── 17. Soil Analysis ──────────────────────────────────────────
def generate_soil_analysis(raw_data: dict) -> Optional[str]:
    """Generate soil analysis section with texture, composition, pH, and fertility."""
    rd = _get_rd(raw_data)
    texture = rd.get("soil_texture", "")
    if not texture:
        return None
    SOIL_TEXTURE_NP = {
        "sand": "बालुवे", "loamy sand": "बालुवे दोमट",
        "sandy loam": "बालुवे दोमट", "loam": "दोमट",
        "silt loam": "ग्राबेले दोमट", "silt": "ग्राबेले",
        "sandy clay loam": "बालुवे चिल्लो दोमट",
        "clay loam": "चिल्लो दोमट", "silty clay loam": "ग्राबेले चिल्लो दोमट",
        "sandy clay": "बालुवे चिल्लो", "silty clay": "ग्राबेले चिल्लो",
        "clay": "चिल्लो",
    }
    texture_np = SOIL_TEXTURE_NP.get(texture.lower().strip(), texture)
    props = rd.get("soil_properties", {})
    clay = props.get("clay_pct", 0)
    sand = props.get("sand_pct", 0)
    silt = props.get("silt_pct", 0)
    ph = props.get("ph_h2o", rd.get("soil_ph", ""))
    fertility = rd.get("fertility_class", "")
    fert_score = rd.get("fertility_score", "")
    carbon_stock = rd.get("carbon_stock_t_ha", "")
    nitrogen = props.get("nitrogen_cg_kg", "")
    cec = props.get("cec_mmol_kg", "")
    return (
        f"यस वनको माटोको बनावट \"{texture_np}\" रहेको छ। माटोको भौतिक "
        f"संरचनामा माटोको कण (Clay) {fmt(clay, 1)}%, बालुवा (Sand) "
        f"{fmt(sand, 1)}%, र ग्राबेल (Silt) {fmt(silt, 1)}% रहेको छ। "
        f"माटोको pH मान {fmt(ph, 1) if isinstance(ph, (int, float)) else ph} "
        f"रहेको छ। माटोको उर्वराशक्ति \"{fertility}\" ({fert_score}/100) रहेको छ। "
        f"माटोको जैविक कार्बन भण्डार {fmt(carbon_stock, 1) if isinstance(carbon_stock, (int, float)) else carbon_stock} t/ha रहेको छ। "
        f"माटोको नाइट्रोजन {fmt(nitrogen, 1) if isinstance(nitrogen, (int, float)) else nitrogen} cg/kg "
        f"र CEC {fmt(cec, 0) if isinstance(cec, (int, float)) else cec} mmol/kg रहेको छ।"
    )


# ─── 18. Location & Context ─────────────────────────────────────
def generate_location_context(raw_data: dict) -> Optional[str]:
    """Generate location context section with province, district, municipality, and watershed."""
    bi = _bi(raw_data)
    province = bi.get("province", "")
    district = bi.get("district", "")
    municipality = bi.get("municipality", "")
    ward = bi.get("ward", "")
    watershed = bi.get("watershed", "")
    river = bi.get("major_river_basin", "")
    if not district and not municipality:
        return None
    return (
        f"यस वन {province} प्रदेश, {district} जिल्ला, {municipality} - "
        f"वडा नं. {ward} मा अवस्थित छ। यो वन {watershed} जलाधार र {river} "
        f"प्रमुख नदी बेसिन अन्तर्गत पर्दछ।"
    )


# ─── 19. Species Distribution ────────────────────────────────────
def generate_species_distribution(raw_data: dict) -> Optional[str]:
    """Generate species distribution section with total species count."""
    species = raw_data.get("species", {})
    total = species.get("total_species", 0)
    rd = _get_rd(raw_data)
    total2 = rd.get("total_species", 0)
    total = total or total2
    if not total:
        return None
    return (
        f"यस वनमा जम्मा {fmt(total, 0)} प्रजातिका रूखहरू पाइन्छन्। "
        f"यी प्रजातिहरू विभिन्न वन खण्डहरूमा फैलिएका छन्। "
        f"तल प्रमुख प्रजातिहरूको सूची दिइएको छ।"
    )


# ─── 20. Accessible Forest Area ─────────────────────────────────
def generate_accessible_forest(raw_data: dict) -> Optional[str]:
    """Generate accessible forest area section with accessible/inaccessible breakdown."""
    rd = _get_rd(raw_data)
    # The unit set the analysis ran on - blocks or compartments, the leaf view (FS-1a.12).
    from app.services.analysis_polygon_source import PolygonSource

    blocks = PolygonSource.for_result_data(rd).get_polygons()
    if not blocks:
        return None
    total_accessible = sum(
        b.get("accessible_forest_area_ha", 0) or 0 for b in blocks
    )
    total_inaccessible = sum(
        b.get("inaccessible_steep_forest_ha", 0) or 0 for b in blocks
    )
    total_non_forest = sum(
        b.get("non_forest_area_ha", 0) or 0 for b in blocks
    )
    total = total_accessible + total_inaccessible + total_non_forest
    if not total:
        return None
    ap = total_accessible / total * 100 if total else 0
    ip = total_inaccessible / total * 100 if total else 0
    np_ = total_non_forest / total * 100 if total else 0
    return (
        f"यस वनको कुल क्षेत्रफलमध्ये {fmt(total_accessible, 2)} हेक्टर "
        f"({fmt(ap, 1)}%) क्षेत्र नमुना प्लट राख्नको लागि पहुँचयोग्य रहेको छ। "
        f"दुर्गम वन क्षेत्र {fmt(total_inaccessible, 2)} हेक्टर "
        f"({fmt(ip, 1)}%) र वन नभएको क्षेत्र {fmt(total_non_forest, 2)} हेक्टर "
        f"({fmt(np_, 1)}%) रहेको छ।"
    )


# business: full inventory narrative with all per-ha metrics
# ─── 21. Field Inventory Narration ───────────────────────────────
def generate_field_inventory_narration(raw_data: dict) -> Optional[str]:
    """Generate field inventory narration with all per-hectare metrics."""
    fi = raw_data.get("field_inventory", {})
    if not fi.get("available") or not fi.get("total_sample_plots"):
        return None

    plots = fmt(fi.get("total_sample_plots", 0), 0)
    blocks = fmt(fi.get("total_blocks", 0), 0)
    regen = fmt(fi.get("fi_regeneration_per_ha", 0), 0)
    sapling = fmt(fi.get("fi_sapling_per_ha", 0), 0)
    pole = fmt(fi.get("fi_pole_per_ha", 0), 0)
    tree = fmt(fi.get("fi_tree_per_ha", 0), 0)
    gs = fmt(fi.get("fi_growing_stock_m3_per_ha", 0), 2)
    ba = fmt(fi.get("fi_basal_area_m2_per_ha", 0), 2)
    agb = fmt(fi.get("fi_agb_t_per_ha", 0), 2)
    bgb = fmt(fi.get("fi_bgb_t_per_ha", 0), 2)
    tb = fmt(fi.get("fi_total_biomass_t_per_ha", 0), 2)
    c = fmt(fi.get("fi_carbon_stock_tc_per_ha", 0), 2)
    co2 = fmt(fi.get("fi_co2_equivalent_tco2_per_ha", 0), 2)
    mai_pct = fmt(fi.get("fi_mai_percent", 0), 1)
    den = fmt(fi.get("fi_weighted_wood_density", 0), 3)
    fc = fi.get("fi_forest_condition", "—")

    # Get MAI/AAH from grand total row in block summaries
    block_summaries = fi.get("fi_block_summaries", [])
    grand = block_summaries[-1] if len(block_summaries) > 1 and "Grand" in str(block_summaries[-1].get("block_name", "")) else None
    mai_vol = fmt(grand.get("mai_total_m3_per_ha", 0), 2) if grand else "—"
    aah_vol = fmt(grand.get("aah_total_m3_per_ha", 0), 2) if grand else "—"
    aah_pct = fmt(grand.get("aah_multiplier_percent", 0), 0) if grand else "—"

    ul = _dim_label_np(raw_data)
    return (
        f"यस वनको कुल {plots} वटा नमुना प्लटहरू ({blocks} वटा {ul}) मा गरिएको "
        f"क्षेत्र सर्वेक्षण अनुसार प्रति हेक्टर {regen} वटा विरुवा, "
        f"{sapling} वटा लाथ्रा, {pole} वटा खाँवा र {tree} वटा रूख रहेको पाइयो। "
        f"कुल वृद्धि मौज्दात {gs} घनमिटर प्रति हेक्टर र बेसल एरिया "
        f"{ba} वर्गमिटर प्रति हेक्टर रहेको छ। प्रति हेक्टर जमिन माथिको "
        f"बायोमास {agb} टन र जमिन मुनिको बायोमास {bgb} टन "
        f"(जम्मा {tb} टन) रहेको छ। कुल कार्बन भण्डार {c} टन कार्बन "
        f"प्रति हेक्टर र कार्बन डाइअक्साइड समतुल्य {co2} टन प्रति हेक्टर "
        f"रहेको छ। वनको अवस्था \"{fc}\" रहेको छ भने औसत वार्षिक वृद्धि "
        f"{mai_pct}% र काठ घनत्व {den} टन प्रति घनमिटर रहेको छ। "
    )


def generate_sampling_narration(raw_data: dict) -> Optional[str]:
    """Generate sampling narration with plot count, method, and intensity details."""
    sampling = raw_data.get("sampling", {})
    if not sampling.get("available"):
        return None
    designs = sampling.get("designs", [])
    if not designs:
        return None
    d = designs[0]
    pts = d.get("total_points") or 0
    blks = d.get("total_blocks") or 0
    forest_ha = d.get("forest_area_hectares") or 0
    plot_shape = d.get("plot_shape") or "circular"
    plot_size = d.get("plot_area_sqm") or 0
    requested = d.get("requested_intensity_percent") or 0
    actual = d.get("sampling_percentage") or 0
    samp_type = d.get("sampling_type") or "systematic"
    blocks_info = d.get("blocks_info") or []

    if not pts and not blks:
        return None

    SHAPE_MAP = {"circular": "वृत्ताकार", "square": "वर्गाकार", "rectangular": "आयताकार"}
    TYPE_MAP = {"systematic": "व्यवस्थित", "random": "अनियमित", "stratified": "स्तरीकृत", "imported": "बाहिरबाट आयातित"}
    shape_np = SHAPE_MAP.get(plot_shape, plot_shape)
    type_np = TYPE_MAP.get(samp_type, samp_type)

    systematic_count = sum(1 for b in blocks_info if b.get("sampling_method") == "systematic")
    random_count = sum(1 for b in blocks_info if b.get("sampling_method") == "random")

    parts = [
        f"यस सामुदायिक वनको कुल {fmt(blks, 0)} वटा खण्डमा जम्मा {fmt(pts, 0)} "
        f"गोटा नमुना प्लट रहेका छन्। कुल वन क्षेत्रफल {fmt(forest_ha, 2)} हेक्टर मध्ये "
        f"{fmt(requested, 1)} प्रतिशत इन्टेन्सिटीमा स्याम्पलिङ गर्न खोजिएकोमा "
        f"वास्तविक स्याम्पल {fmt(actual, 2)} प्रतिशत हुन आएको छ।"
    ]

    if plot_size:
        parts.append(
            f"प्रत्येक नमुना प्लटको क्षेत्रफल {fmt(plot_size, 0)} वर्गमिटर र "
            f"प्लटको आकार {shape_np} रहेको छ।"
        )

    if systematic_count > 0 or random_count > 0:
        method_parts = []
        if systematic_count > 0:
            method_parts.append(f"{fmt(systematic_count, 0)} वटा खण्डमा व्यवस्थित (Systematic) विधि")
        if random_count > 0:
            method_parts.append(f"{fmt(random_count, 0)} वटा खण्डमा अनियमित (Random) विधि")
        parts.append("स्याम्पलिङका लागि " + " तथा ".join(method_parts) + " प्रयोग गरिएको छ।")

    return " ".join(parts)


def generate_fieldbook_narration(raw_data: dict) -> Optional[str]:
    """Generate fieldbook narration with point count, vertices, perimeter, and elevation."""
    fb = raw_data.get("fieldbook", {})
    if not fb.get("available"):
        return None
    total = fb.get("total_points", 0)
    vtx = fb.get("vertex_count", 0)
    ipol = fb.get("interpolated_count", 0)
    perim = fb.get("perimeter_m", 0)
    avg_el = fb.get("avg_elevation_m")
    min_el = fb.get("min_elevation_m")
    max_el = fb.get("max_elevation_m")

    parts = [
        f"यस सामुदायिक वनको वरिपरि जम्मा {fmt(total, 0)} वटा फिल्डबुक "
        f"बिन्दुहरू रहेका छन्, जसमध्ये {fmt(vtx, 0)} मुख्य बिन्दु (Vertex) र "
        f"{fmt(ipol, 0)} अन्तरसम्मिलित बिन्दु (Interpolated) छन्।"
    ]

    if perim:
        parts.append(
            f"वनको कुल परिधि {fmt(perim, 0)} मिटर लामो रहेको छ।"
        )

    if avg_el is not None and min_el is not None and max_el is not None:
        parts.append(
            f"यस वनको औसत उचाइ {fmt(avg_el, 0)} मिटर रहेको छ, जुन न्यूनतम "
            f"{fmt(min_el, 0)} मिटर देखि अधिकतम {fmt(max_el, 0)} मिटर सम्म रहेको छ।"
        )

    return " ".join(parts)


# business: tree inventory block-wise area breakdown
# ─── 22. T1: Block Area Narration ─────────────────────────────
def generate_ti_block_area_narration(raw_data: dict) -> Optional[str]:
    """Generate T1 block area narration with total and effective area by block."""
    fi = raw_data.get("field_inventory", {})
    tbl = fi.get("ti_block_area_table", [])
    if not tbl:
        return None
    total_row = tbl[-1] if tbl else {}
    total_area = total_row.get("कुल_क्षेत्रफल_हे", 0)
    eff_area = total_row.get("वन_श्रोत_प्रभावित_क्षेत्रफल", 0)
    excluded = total_row.get("बनश्रोत_अप्रभावित_क्षेत्र_हे", 0)
    if not total_area:
        return None
    parts = [
        f"यस सामुदायिक वनको जम्मा क्षेत्रफल {fmt(total_area, 2)} हेक्टर रहेकोमा "
        f"प्रभावकारी वन आवरण {fmt(eff_area, 2)} हेक्टर रहेको छ। "
        f"बनश्रोत अप्रभावित क्षेत्र {fmt(excluded, 2)} हेक्टर रहेको छ।"
    ]
    block_details = []
    for r in tbl:
        bn = r.get("ब्लकको_नाम", "")
        if bn == "जम्मा":
            continue
        eff = r.get("वन_श्रोत_प्रभावित_क्षेत्रफल", 0)
        block_details.append(f"{bn} {fmt(eff, 2)} हेक्टर")
    if block_details:
        ul = _dim_label_np(raw_data)
        parts.append(f"{ul} अनुसार प्रभावकारी क्षेत्रफल: " + ", ".join(block_details) + " रहेको छ।")
    return " ".join(parts)


# ─── 23. T2: Forest Total Narration ──────────────────────────
def generate_ti_forest_total_narration(raw_data: dict) -> Optional[str]:
    """Generate T2 forest total narration with growing stock, regeneration, and carbon totals."""
    fi = raw_data.get("field_inventory", {})
    if not fi.get("ti_available"):
        return None
    plots = fmt(fi.get("ti_total_plots", 0), 0)
    blocks = fmt(fi.get("ti_total_blocks", 0), 0)
    area = fi.get("ti_effective_area_ha", 0)
    gs = fi.get("ti_total_growing_stock_m3", 0)
    regen = fmt(fi.get("ti_total_regeneration", 0), 0)
    sapling = fmt(fi.get("ti_total_sapling", 0), 0)
    pole = fmt(fi.get("ti_total_pole", 0), 0)
    tree = fmt(fi.get("ti_total_tree", 0), 0)
    ba = fi.get("ti_total_basal_area_m2", 0)
    mai = fi.get("ti_total_mai_m3_per_year", 0)
    aah = fi.get("ti_total_aah_m3_per_year", 0)
    biomass = fi.get("ti_total_biomass_tonnes", 0)
    carbon = fi.get("ti_total_carbon_tc", 0)
    if not gs:
        return None
    ul = _dim_label_np(raw_data)
    return (
        f"यस सामुदायिक वनको कुल {plots} वटा नमुना प्लटहरू ({blocks} वटा {ul}) को "
        f"सर्वेक्षणबाट प्राप्त तथ्यांक अनुसार कुल क्षेत्रफल {fmt(area, 2)} हेक्टर र "
        f"कुल वृद्धि मौज्दात {fmt(gs, 2)} घनमिटर रहेको छ। जसमा कुल {regen} वटा "
        f"विरुवा, {sapling} वटा लाथ्रा, {pole} वटा खाँवा र {tree} वटा रूख "
        f"रहेका छन्। कुल बेसल एरिया {fmt(ba, 2)} वर्गमिटर र कुल कार्बन स्टक "
        f"{fmt(carbon, 2)} टन कार्बन रहेको छ। कुल जैविक पदार्थ {fmt(biomass, 2)} टन, "
        f"कुल MAI {fmt(mai, 2)} घनमिटर/वर्ष र कुल AAH {fmt(aah, 2)} घनमिटर/वर्ष रहेको छ।"
    )


# ─── 24. T3: Block Growing Stock Narration ───────────────────
def generate_ti_block_growing_stock_narration(raw_data: dict) -> Optional[str]:
    """Generate T3 block growing stock narration with volume by block and total."""
    fi = raw_data.get("field_inventory", {})
    tbl = fi.get("ti_block_growing_stock", [])
    if not tbl:
        return None
    ul = _dim_label_np(raw_data)
    parts = [f"{ul} अनुसार कुल वृद्धि मौज्दातको विवरण:"]
    block_items = []
    for r in tbl:
        bn = r.get("ब्लकको_नाम", "")
        if bn == "जम्मा":
            continue
        total = r.get("वृद्धि_मौज्दात_जम्मा_कुल_घमी", 0)
        timber = r.get("वृद्धि_मौज्दात_काठ_कुल_घमी", 0)
        fuel = r.get("वृद्धि_मौज्दात_दाउरा_कुल_घमी", 0)
        block_items.append(f"{bn} मा कुल {fmt(total, 2)} घनमिटर (काठ {fmt(timber, 2)} घमी, दाउरा {fmt(fuel, 2)} घमी)")
    if block_items:
        parts.append("। ".join(block_items) + " रहेको छ।")
    total_row = tbl[-1] if len(tbl) > 1 else {}
    gt = total_row.get("वृद्धि_मौज्दात_जम्मा_कुल_घमी", 0)
    if gt:
        parts.append(f"जम्मा {fmt(gt, 2)} घनमिटर रहेको छ।")
    return " ".join(parts)


# ─── 25. T4: Species Stock Narration ─────────────────────────
def generate_ti_species_stock_narration(raw_data: dict) -> Optional[str]:
    """Generate T4 species stock narration with volume by species and percentage."""
    fi = raw_data.get("field_inventory", {})
    comp = fi.get("ti_species_composition_absolute", {})
    tbl = fi.get("ti_species_block_growing_stock", [])
    if not comp and not tbl:
        return None
    total = sum(v for v in comp.values() if isinstance(v, (int, float)))
    if not total:
        return None
    sorted_sp = sorted(comp.items(), key=lambda x: x[1], reverse=True)
    parts = ["प्रजाति अनुसार कुल वृद्धि मौज्दात:"]
    sp_items = []
    for sp, vol in sorted_sp[:6]:
        pct = vol / total * 100
        sp_items.append(f"{sp} {fmt(vol, 2)} घनमिटर ({fmt(pct, 2)}%)")
    if sorted_sp:
        parts.append("। ".join(sp_items))
    if len(sorted_sp) > 6:
        other_vol = sum(v for _, v in sorted_sp[6:])
        other_pct = other_vol / total * 100
        parts.append(f"र अन्य {fmt(other_vol, 2)} घनमिटर ({fmt(other_pct, 2)}%)")
    parts.append(f"रहेको छ। जम्मा {fmt(total, 2)} घनमिटर।")
    return " ".join(parts)


# ─── 26. T5: Species DBH Narration ───────────────────────────
def generate_ti_species_dbh_narration(raw_data: dict) -> Optional[str]:
    """Generate T5 species DBH narration with volume per hectare by DBH class."""
    fi = raw_data.get("field_inventory", {})
    tbl = fi.get("ti_species_dbh_class_table", [])
    if not tbl:
        return None
    by_class: dict = {}
    for r in tbl:
        cls = r.get("DBH_क्लास", "")
        vol = r.get("आयतन_घमी_प्रति_हे", 0)
        if cls not in by_class:
            by_class[cls] = 0.0
        by_class[cls] += vol
    parts = ["प्रजाति अनुसार DBH वर्ग मौज्दात (प्रति हेक्टर):"]
    cls_items = [f"{cls} {fmt(vol, 2)} घमी/हे" for cls, vol in sorted(by_class.items())]
    if cls_items:
        parts.append("। ".join(cls_items) + " रहेको छ।")
    return " ".join(parts)


# ─── Regulation-category species narrations (all categories / classified only) ───
def generate_fi_reg_species_narration(raw_data: dict) -> Optional[str]:
    from .species_regulation_tables import narration
    return narration(raw_data.get("field_inventory", {}), "fi_reg")


def generate_fi_regc_species_narration(raw_data: dict) -> Optional[str]:
    from .species_regulation_tables import narration
    return narration(raw_data.get("field_inventory", {}), "fi_regc")


# ─── 27. T6: Forest DBH Narration ────────────────────────────
def generate_ti_forest_dbh_narration(raw_data: dict) -> Optional[str]:
    """Generate T6 forest DBH narration with per-hectare volume by DBH class."""
    fi = raw_data.get("field_inventory", {})
    tbl = fi.get("ti_forest_dbh_class_table", [])
    if not tbl:
        return None
    parts = ["सम्पूर्ण वन क्षेत्रको DBH वर्ग मौज्दात (प्रति हेक्टर):"]
    cls_items = [f"{r.get('DBH_क्लास', '')} {fmt(r.get('आयतन_घमी_प्रति_हे', 0), 2)} घमी/हे" for r in tbl]
    if cls_items:
        parts.append("। ".join(cls_items) + " रहेको छ।")
    return " ".join(parts)


# ─── 28. T7: DBH Class Total Narration ───────────────────────
def generate_ti_dbh_total_narration(raw_data: dict) -> Optional[str]:
    """Generate T7 DBH class total narration with volume and percentage by class."""
    fi = raw_data.get("field_inventory", {})
    tbl = fi.get("ti_dbh_class_totals_table", [])
    if not tbl:
        return None
    total_row = tbl[-1] if tbl else {}
    total_vol = sum(r.get("आयतन_घमी", 0) for r in tbl if r.get("ब्लकको_नाम") == "जम्मा वन कुल")
    parts = ["DBH वर्ग अनुसार कुल वृद्धि मौज्दात:"]
    cls_items = []
    for r in tbl:
        if r.get("ब्लकको_नाम") != "जम्मा वन कुल":
            continue
        cls = r.get("DBH_क्लास", "")
        vol = r.get("आयतन_घमी", 0)
        pct = vol / total_vol * 100 if total_vol > 0 else 0
        cls_items.append(f"{cls} वर्गमा {fmt(vol, 2)} घनमिटर ({fmt(pct, 2)}%)")
    if cls_items:
        parts.append("। ".join(cls_items) + " रहेको छ।")
    return " ".join(parts)


# ─── 29. T8: DBH Class Per Ha Narration ──────────────────────
def generate_ti_dbh_perha_narration(raw_data: dict) -> Optional[str]:
    """Generate T8 DBH per-hectare narration with volume by class."""
    fi = raw_data.get("field_inventory", {})
    tbl = fi.get("ti_dbh_class_perha_table", [])
    if not tbl:
        return None
    parts = ["प्रति हेक्टर DBH वर्ग अनुसार मौज्दात:"]
    cls_items = []
    for r in tbl:
        if r.get("ब्लकको_नाम") != "जम्मा वन कुल/हे.":
            continue
        cls = r.get("DBH_क्लास", "")
        vol = r.get("आयतन_घमी_प्रति_हे", 0)
        cls_items.append(f"{cls} {fmt(vol, 2)} घनमिटर/हे")
    if cls_items:
        parts.append("। ".join(cls_items) + " रहेको छ।")
    return " ".join(parts)


# ─── 30. T9: DBH Class MAI Narration ─────────────────────────
def generate_ti_dbh_mai_narration(raw_data: dict) -> Optional[str]:
    """Generate T9 DBH MAI narration with annual increment by DBH class."""
    fi = raw_data.get("field_inventory", {})
    tbl = fi.get("ti_dbh_mai_table", [])
    if not tbl:
        return None
    parts = ["DBH वर्ग अनुसार वार्षिक वृद्धि (MAI):"]
    cls_items = []
    total_mai = 0
    for r in tbl:
        if r.get("ब्लकको_नाम") != "जम्मा वन कुल":
            continue
        cls = r.get("DBH_क्लास", "")
        mai = r.get("MAI_घमी_प्रति_वर्ष", 0)
        cls_items.append(f"{cls} वर्गमा {fmt(mai, 2)} घनमिटर/वर्ष")
        total_mai += mai
    if cls_items:
        parts.append("। ".join(cls_items) + f" रहेको छ। जम्मा MAI {fmt(total_mai, 2)} घनमिटर/वर्ष।")
    return " ".join(parts)


# ─── 31. T10: DBH Class AAH Narration ────────────────────────
def generate_ti_dbh_aah_narration(raw_data: dict) -> Optional[str]:
    """Generate T10 DBH AAH narration with annual allowable harvest by DBH class."""
    fi = raw_data.get("field_inventory", {})
    tbl = fi.get("ti_dbh_aah_table", [])
    if not tbl:
        return None
    parts = ["DBH वर्ग अनुसार वार्षिक स्वीकार्य कटान (AAH):"]
    cls_items = []
    total_aah = 0
    for r in tbl:
        if r.get("ब्लकको_नाम") != "जम्मा वन कुल":
            continue
        cls = r.get("DBH_क्लास", "")
        aah = r.get("AAH_घमी_प्रति_वर्ष", 0)
        cls_items.append(f"{cls} वर्गमा {fmt(aah, 2)} घनमिटर/वर्ष")
        total_aah += aah
    if cls_items:
        parts.append("। ".join(cls_items) + f" रहेको छ। जम्मा AAH {fmt(total_aah, 2)} घनमिटर/वर्ष।")
    return " ".join(parts)


# ─── 32. T11: Species Composition Narration ──────────────────
def generate_ti_species_composition_narration(raw_data: dict) -> Optional[str]:
    """Generate T11 species composition narration with dominant species and volume."""
    fi = raw_data.get("field_inventory", {})
    comp = fi.get("ti_species_composition_absolute", {})
    if not comp:
        return None
    total = sum(v for v in comp.values() if isinstance(v, (int, float)))
    if not total:
        return None
    sorted_sp = sorted(comp.items(), key=lambda x: x[1], reverse=True)
    parts = ["यस वनमा प्रजाति संरचना निम्नानुसार रहेको छ:"]
    sp_items = []
    for sp, vol in sorted_sp[:5]:
        pct = vol / total * 100
        sp_items.append(f"{sp} {fmt(vol, 2)} घनमिटर ({fmt(pct, 2)}%)")
    if sorted_sp:
        parts.append("। ".join(sp_items))
    if len(sorted_sp) > 5:
        other_vol = sum(v for _, v in sorted_sp[5:])
        other_pct = other_vol / total * 100
        parts.append(f"र अन्य प्रजातिहरू {fmt(other_vol, 2)} घनमिटर ({fmt(other_pct, 2)}%)")
    dominant = sorted_sp[0][0] if sorted_sp else ""
    if dominant:
        parts.append(f"रहेका छन्। {dominant} प्रमुख प्रजाति हो।")
    return " ".join(parts)


# ─── 33. T12: Productivity Narration ─────────────────────────
def generate_ti_productivity_narration(raw_data: dict) -> Optional[str]:
    """Generate T12 productivity narration with per-hectare growing stock, MAI, and AAH by block."""
    fi = raw_data.get("field_inventory", {})
    tbl = fi.get("ti_block_productivity_table", [])
    if not tbl:
        return None
    ul = _dim_label_np(raw_data)
    parts = [f"{ul} अनुसार उत्पादनसिल संचिती:"]
    block_items = []
    for r in tbl:
        bn = r.get("ब्लकको_नाम", "")
        if bn == "जम्मा":
            continue
        gs_ph = r.get("प्रति_हे_मौज्दात_घमी", 0)
        mai = r.get("MAI_घमी_प्रति_वर्ष", 0)
        aah = r.get("AAH_घमी_प्रति_वर्ष", 0)
        block_items.append(f"{bn} मा प्रति हेक्टर {fmt(gs_ph, 2)} घनमिटर, MAI {fmt(mai, 2)} घमी/वर्ष, AAH {fmt(aah, 2)} घमी/वर्ष")
    if block_items:
        parts.append("। ".join(block_items) + " रहेको छ।")
    best = max(tbl[:-1], key=lambda r: r.get("प्रति_हे_मौज्दात_घमी", 0)) if len(tbl) > 1 else {}
    worst = min(tbl[:-1], key=lambda r: r.get("प्रति_हे_मौज्दात_घमी", 0)) if len(tbl) > 1 else {}
    if best and worst and best.get("ब्लकको_नाम") != worst.get("ब्लकको_नाम"):
        parts.append(
            f"सबैभन्दा बढी उत्पादनसिल संचिती {best.get('ब्लकको_नाम', '')} मा र "
            f"सबैभन्दा कम {worst.get('ब्लकको_नाम', '')} मा रहेको छ।"
        )
    total_row = tbl[-1] if len(tbl) > 1 else {}
    gt_ph = total_row.get("प्रति_हे_मौज्दात_घमी", 0)
    if gt_ph:
        parts.append(f"जम्मा प्रति हेक्टर {fmt(gt_ph, 2)} घनमिटर रहेको छ।")
    return " ".join(parts)


# ─── 34. T13: Economic Narration ─────────────────────────────
def generate_ti_economic_narration(raw_data: dict) -> Optional[str]:
    """Generate T13 economic valuation narration with timber, fuelwood, and carbon value."""
    fi = raw_data.get("field_inventory", {})
    tbl = fi.get("ti_economic_valuation_table", [])
    if not tbl:
        return None
    total_row = tbl[-1] if len(tbl) > 1 else {}
    gs = total_row.get("उत्पादनसिल_संचिती_घमी", 0)
    timber_val = total_row.get("काठ_मूल्य_रु", 0)
    fuel_val = total_row.get("दाउरा_मूल्य_रु", 0)
    carbon_val = total_row.get("कार्बन_मूल्य_रु", 0)
    grand = total_row.get("जम्मा_मूल्य_रु", 0)
    timber_rate = total_row.get("काठ_दर_रु", 2500)
    carbon_rate = total_row.get("कार्बन_दर_रु", 3000)
    if not gs:
        return None
    return (
        f"आर्थिक मूल्याङ्कन: जम्मा वृद्धि मौज्दात {fmt(gs, 2)} घनमिटरको "
        f"स्टम्पेज दर रु. {fmt(timber_rate, 0)}/घमी अनुसार काठको मूल्य "
        f"रु. {fmt(timber_val, 0)} र दाउराको मूल्य रु. {fmt(fuel_val, 0)} "
        f"रहेको छ। कार्बन स्टकको मूल्य दर रु. {fmt(carbon_rate, 0)}/tCO₂ "
        f"अनुसार रु. {fmt(carbon_val, 0)} रहेको छ। जम्मा मूल्य "
        f"रु. {fmt(grand, 0)} रहेको छ।"
    )


# ─── 35. T14: Sustainability Narration ───────────────────────
def generate_ti_sustainability_narration(raw_data: dict) -> Optional[str]:
    """Generate T14 sustainability narration with SI index and harvest pressure."""
    fi = raw_data.get("field_inventory", {})
    tbl = fi.get("ti_sustainability_table", [])
    if not tbl:
        return None
    total_row = tbl[-1] if len(tbl) > 1 else {}
    si = total_row.get("दिगोपन_सूचकांक_SI_प्रतिशत", 0)
    hp = total_row.get("कटान_दबाव_HP_प्रतिशत", 0)
    gs_ph = total_row.get("उत्पादनसिल_संचिती_प्रति_हे_घमी", 0)
    mai_pct = total_row.get("MAI_प्रतिशत", 0)
    if not si and not hp:
        return None

    si_status = "दिगो" if si < 5 else ("मध्यम" if si < 10 else "अति दोहन जोखिम")
    hp_status = "कम दबाब" if hp < 50 else ("मध्यम दबाब" if hp < 80 else "उच्च दबाब")

    return (
        f"दिगोपन सूचकांक: SI (AAH ÷ कुल मौज्दात × १००) {fmt(si, 2)}% रहेको छ, "
        f"जुन {si_status} अवस्थामा रहेको संकेत गर्दछ। "
        f"कटान दबाव HP (AAH ÷ MAI × १००) {fmt(hp, 1)}% रहेको छ, "
        f"जुन {hp_status} हो। प्रति हेक्टर उत्पादनसिल संचिती "
        f"{fmt(gs_ph, 2)} घनमिटर/हे. र MAI प्रतिशत {fmt(mai_pct, 1)}% रहेको छ।"
    )


# business: sampling method hierarchy narration
# ─── 36. Tree Mapping: Hierarchy Narration ─────────────────────
def generate_sm_hierarchy_narration(raw_data: dict) -> Optional[str]:
    """Generate SM hierarchy narration with block and tree counts."""
    sm = raw_data.get("tree_mapping_analysis", {})
    if not sm.get("sm_available"):
        return None
    blocks = sm.get("sm_total_blocks_analyzed", 0)
    trees = sm.get("sm_total_trees_analyzed", 0)
    h_data = sm.get("sm_hierarchy_summary", [])
    levels = len(h_data)
    if not blocks or not trees:
        return None
    return (
        f"स्टेम म्यापिङ् गरिएको रूखहरू विभिन्न ब्लक, कम्पार्मेन्ट, "
        f"सबकम्पार्टमेनट तथा उपक्षेत्रमा परेकोमा उक्त् रूखहरू जम्मा "
        f"{fmt(blocks, 0)} गोटा ब्लकमा रहेका छन्। कुल रूखहरू "
        f"{fmt(trees, 0)} गोटा रहेको देखिएको छ। रूखहरू परेका क्षेत्र "
        f"जम्मा {fmt(levels, 0)} गोटा रहेका छन्। यी प्रत्येक स्थान "
        f"बमोजिम रूखहरूको संख्या, तिनीहरूको आयतन प्रमुख प्रजाति, "
        f"औसत डिवियच र उचाइ भएको तालिकामा समावेस गरीएको छ।"
    )


# ─── 37. Tree Mapping: Species Composition Narration ──────────
def generate_sm_species_narration(raw_data: dict) -> Optional[str]:
    """Generate SM species composition narration with top species and Shannon index."""
    sm = raw_data.get("tree_mapping_analysis", {})
    if not sm.get("sm_available"):
        return None
    s_data = sm.get("sm_species_by_hierarchy", [])
    d_data = sm.get("sm_species_diversity", [])
    if not s_data:
        return None
    species_set = set(r.get("species", "") for r in s_data if r.get("species"))
    sp_count = len(species_set)
    # Top species by count
    sp_counts = Counter(r.get("species", "") for r in s_data)
    top = sp_counts.most_common(3)
    top_str = ", ".join(f"{s} ({fmt(c, 0)})" for s, c in top) if top else "—"
    # Diversity info
    div_str = ""
    if d_data:
        avg_shannon = sum(float(r.get("shannon_index", 0) or 0) for r in d_data) / len(d_data)
        div_str = f" श्यानन विविधता सूचकांक औसत {fmt(avg_shannon, 2)} रहेको छ।"
    return (
        f"रूख म्यापिङमा जम्मा {fmt(sp_count, 0)} प्रजातिहरू फेला परेका छन्। "
        f"सबैभन्दा बढी पाइने प्रजातिहरू: {top_str}।{div_str}"
    )


# ─── 38. Tree Mapping: DBH Class Narration ───────────────────
def generate_sm_dbh_narration(raw_data: dict) -> Optional[str]:
    """Generate SM DBH class narration with tree count by DBH class."""
    sm = raw_data.get("tree_mapping_analysis", {})
    if not sm.get("sm_available"):
        return None
    d_data = sm.get("sm_dbh_by_hierarchy", [])
    if not d_data:
        return None
    total = sum(int(r.get("tree_count", 0) or 0) for r in d_data)
    # Find dominant DBH class
    cls_counts = Counter()
    for r in d_data:
        cls = r.get("dbh_class", "")
        cnt = int(r.get("tree_count", 0) or 0)
        cls_counts[cls] += cnt
    top = cls_counts.most_common(1)
    dominant = f"{top[0][0]} ({fmt(top[0][1], 0)} रूख)" if top else "—"
    return (
        f"DBH वर्ग विश्लेषण अनुसार जम्मा {fmt(total, 0)} वटा रूखहरूको "
        f"वर्गीकरण गरिएको छ। सबैभन्दा बढी रूख भएको DBH वर्ग: {dominant}। "
        f"प्रत्येक स्थानिक स्तरमा DBH वर्ग अनुसार रूख सङ्ख्या, काठ आयतन, "
        f"दाउरा आयतन र स्तर प्रतिशत विवरण तालिकामा समावेश गरिएको छ।"
    )


# ─── 39. Tree Mapping: Stand Type Narration ──────────────────
def generate_sm_stand_type_narration(raw_data: dict) -> Optional[str]:
    """Generate SM stand type narration with regeneration, sapling, pole, and tree counts."""
    sm = raw_data.get("tree_mapping_analysis", {})
    if not sm.get("sm_available"):
        return None
    st_data = sm.get("sm_stand_type_by_hierarchy", [])
    status = sm.get("sm_forest_structure_status", {})
    if not st_data:
        return None
    total_regen = sum(int(r.get("regeneration", 0) or 0) for r in st_data)
    total_sapling = sum(int(r.get("sapling", 0) or 0) for r in st_data)
    total_pole = sum(int(r.get("pole", 0) or 0) for r in st_data)
    total_tree = sum(int(r.get("tree", 0) or 0) for r in st_data)
    grand = total_regen + total_sapling + total_pole + total_tree
    regen_pct = round(total_regen / grand * 100, 1) if grand else 0
    overall = status.get("overall_status", "—")
    return (
        f"वन संरचना विश्लेषण अनुसार जम्मा {fmt(grand, 0)} वटा रूखहरूमध्ये "
        f"पुनरुत्पादन {fmt(total_regen, 0)} ({fmt(regen_pct, 1)}%), "
        f"लाथ्रा {fmt(total_sapling, 0)}, पोल {fmt(total_pole, 0)} र "
        f"रूख {fmt(total_tree, 0)} वटा रहेको छ। समग्र वन संरचना अवस्था "
        f"\"{overall}\" रहेको छ।"
    )


# ─── 40. Tree Mapping: Carbon Stock Narration ────────────────
def generate_sm_carbon_narration(raw_data: dict) -> Optional[str]:
    """Generate SM carbon stock narration with AGB, BGB, and CO2 equivalent."""
    sm = raw_data.get("tree_mapping_analysis", {})
    if not sm.get("sm_available"):
        return None
    c_data = sm.get("sm_carbon_by_hierarchy", [])
    tc = sm.get("sm_total_carbon_tc", 0)
    tco2 = sm.get("sm_total_co2_tco2", 0)
    if not c_data:
        return None
    total_agb = sum(float(r.get("agb_t", 0) or 0) for r in c_data)
    total_bgb = sum(float(r.get("bgb_t", 0) or 0) for r in c_data)
    total_bio = sum(float(r.get("biomass_t", 0) or 0) for r in c_data)
    return (
        f"कार्बन मौज्दात विश्लेषण अनुसार कुल जमिन माथिको बायोमास (AGB) "
        f"{fmt(total_agb, 2)} टन र जमिन मुनिको बायोमास (BGB) "
        f"{fmt(total_bgb, 2)} टन (जम्मा {fmt(total_bio, 2)} टन) रहेको छ। "
        f"कुल कार्बन मौज्दात {fmt(tc, 3)} tC र कार्बन डाइअक्साइड समतुल्य "
        f"{fmt(tco2, 3)} tCO₂ रहेको छ। प्रत्येक स्थानिक स्तरको कार्बन "
        f"विवरण तालिकामा समावेश गरिएको छ।"
    )


# ─── 41. Tree Mapping: Volume Distribution Narration ─────────
def generate_sm_volume_narration(raw_data: dict) -> Optional[str]:
    """Generate SM volume distribution narration with stem, branch, and net volume."""
    sm = raw_data.get("tree_mapping_analysis", {})
    if not sm.get("sm_available"):
        return None
    v_data = sm.get("sm_volume_by_hierarchy", [])
    top_sp = sm.get("sm_top_species_by_volume", [])
    if not v_data:
        return None
    total_stem = sum(float(r.get("stem_volume_m3", 0) or 0) for r in v_data)
    total_branch = sum(float(r.get("branch_volume_m3", 0) or 0) for r in v_data)
    total_vol = sum(float(r.get("total_volume_m3", 0) or 0) for r in v_data)
    total_net = sum(float(r.get("net_volume_m3", 0) or 0) for r in v_data)
    # Top species info
    top_str = ""
    if top_sp:
        top_entries = top_sp[:3]
        top_str = "। आयतन अनुसार शीर्ष प्रजातिहरू: " + ", ".join(
            f"{r.get('local_name', r.get('species', ''))} ({fmt(r.get('total_volume_m3', 0), 2)} m³)"
            for r in top_entries
        )
    return (
        f"आयतन वितरण विश्लेषण अनुसार जम्मा काण्ड आयतन {fmt(total_stem, 2)} m³, "
        f"हाँगा आयतन {fmt(total_branch, 2)} m³ र कुल आयतन {fmt(total_vol, 2)} m³ "
        f"रहेको छ। नेट आयतन {fmt(total_net, 2)} m³ रहेको छ।"
        f"{top_str}"
    )


# ─── 42. Tree Mapping: Mother Tree Coverage Narration ────────
def generate_sm_mother_tree_narration(raw_data: dict) -> Optional[str]:
    """Generate SM mother tree coverage narration with grid coverage and count."""
    sm = raw_data.get("tree_mapping_analysis", {})
    if not sm.get("sm_available"):
        return None
    coverage = sm.get("sm_mother_tree_coverage", {})
    mt_data = sm.get("sm_mother_tree_by_hierarchy", [])
    summary = sm.get("sm_mother_felling_summary", {})
    if not coverage and not mt_data and not summary:
        return None
    grid = coverage.get("grid_spacing_m", "—")
    total_cells = coverage.get("total_grid_cells", 0)
    with_mother = coverage.get("cells_with_mother", 0)
    cov_pct = coverage.get("coverage_percent", 0)
    total_mother = (
        summary.get("total_mother_trees", 0)
        or (sum(int(r.get("mother_trees", 0) or 0) for r in mt_data) if mt_data else 0)
    )
    total_felling = (
        summary.get("total_felling_trees", 0)
        or (sum(int(r.get("felling_trees", 0) or 0) for r in mt_data) if mt_data else 0)
    )
    return (
        f"माँउ रूख कभरेज विश्लेषण: ग्रिड दूरी {grid} मि., कुल ग्रिड सेल "
        f"{fmt(total_cells, 0)} मध्ये {fmt(with_mother, 0)} सेलमा माँउ रूख "
        f"रहेको छ (कभरेज {fmt(cov_pct, 1)}%)। "
        f"जम्मा {fmt(total_mother, 0)} वटा माँउ रूख र "
        f"{fmt(total_felling, 0)} वटा कटानी रूख रहेको छ।"
    )


# ─── 43. Tree Mapping: Felling Tree Analysis Narration ───────
def generate_sm_felling_narration(raw_data: dict) -> Optional[str]:
    """Generate SM felling tree analysis narration with volume by species."""
    sm = raw_data.get("tree_mapping_analysis", {})
    if not sm.get("sm_available"):
        return None
    totals = sm.get("sm_felling_totals", {})
    f_dbh = sm.get("sm_felling_dbh_analysis", [])
    f_sp = sm.get("sm_felling_species_analysis", [])
    if not totals and not f_dbh:
        return None
    total_trees = totals.get("tree_count", 0) or sum(int(r.get("tree_count", 0) or 0) for r in f_dbh)
    total_vol = totals.get("gross_volume_m3", 0) or sum(float(r.get("gross_volume_m3", 0) or 0) for r in f_dbh)
    total_timber = totals.get("timber_m3", 0) or sum(float(r.get("timber_m3", 0) or 0) for r in f_dbh)
    total_fw = totals.get("firewood_m3", 0) or sum(float(r.get("firewood_m3", 0) or 0) for r in f_dbh)
    # Top species
    top_str = ""
    if f_sp:
        top = sorted(f_sp, key=lambda r: float(r.get("gross_volume_m3", 0) or 0), reverse=True)[:3]
        top_str = "। प्रजाति अनुसार: " + ", ".join(
            f"{r.get('local_name', r.get('species', ''))} {fmt(r.get('gross_volume_m3', 0), 2)} m³"
            for r in top
        )
    return (
        f"कटानी रूख विश्लेषण (≥३० से.मी. DBH): जम्मा {fmt(total_trees, 0)} वटा "
        f"कटानी रूखको कुल आयतन {fmt(total_vol, 2)} m³ (काठ {fmt(total_timber, 2)} m³, "
        f"दाउरा {fmt(total_fw, 2)} m³) रहेको छ।"
        f"{top_str}"
    )


SECTION_GENERATORS = {
    "section:forest_summary": generate_forest_summary,
    "section:slope_analysis": generate_slope_analysis,
    "section:elevation_profile": generate_elevation_profile,
    "section:aspect_analysis": generate_aspect_analysis,
    "section:forest_health": generate_forest_health,
    "section:forest_type": generate_forest_type,
    "section:species_potential": generate_potential_species,
    "section:actual_species": generate_actual_species,
    "section:biodiversity": generate_biodiversity,
    "section:canopy_structure": generate_canopy_structure,
    "section:biomass_carbon": generate_biomass_carbon,
    "section:climate_conditions": generate_climate_conditions,
    "section:land_cover": generate_land_cover,
    "section:land_cover_1984": generate_land_cover_1984,
    "section:ntfp": generate_ntfp,
    "section:ntfp_inventory": generate_ntfp_inventory,
    "section:forest_loss": generate_forest_loss,
    "section:fire_loss": generate_fire_loss,
    "section:forest_quality": generate_forest_quality,
    "section:soil_analysis": generate_soil_analysis,
    "section:location_context": generate_location_context,
    "section:species_distribution": generate_species_distribution,
    "section:accessible_forest": generate_accessible_forest,
    "section:field_inventory_narration": generate_field_inventory_narration,
    "section:sampling_narration": generate_sampling_narration,
    "section:fieldbook_narration": generate_fieldbook_narration,
    "section:household_narration": generate_household_narration,
    "section:committee_narration": generate_committee_narration,
    "section:user_group_narration": generate_user_group_narration,
    "section:demand_supply_narration": generate_demand_supply_narration,
    "section:ti_block_area_narration": generate_ti_block_area_narration,
    "section:ti_forest_total_narration": generate_ti_forest_total_narration,
    "section:ti_block_growing_stock_narration": generate_ti_block_growing_stock_narration,
    "section:ti_species_stock_narration": generate_ti_species_stock_narration,
    "section:ti_species_dbh_narration": generate_ti_species_dbh_narration,
    "section:fi_reg_species_narration": generate_fi_reg_species_narration,
    "section:fi_regc_species_narration": generate_fi_regc_species_narration,
    "section:ti_forest_dbh_narration": generate_ti_forest_dbh_narration,
    "section:ti_dbh_total_narration": generate_ti_dbh_total_narration,
    "section:ti_dbh_perha_narration": generate_ti_dbh_perha_narration,
    "section:ti_dbh_mai_narration": generate_ti_dbh_mai_narration,
    "section:ti_dbh_aah_narration": generate_ti_dbh_aah_narration,
    "section:ti_species_composition_narration": generate_ti_species_composition_narration,
    "section:ti_productivity_narration": generate_ti_productivity_narration,
    "section:ti_economic_narration": generate_ti_economic_narration,
    "section:ti_sustainability_narration": generate_ti_sustainability_narration,

    # Tree Mapping Analysis Narrations
    "section:sm_hierarchy_narration": generate_sm_hierarchy_narration,
    "section:sm_species_narration": generate_sm_species_narration,
    "section:sm_dbh_narration": generate_sm_dbh_narration,
    "section:sm_stand_type_narration": generate_sm_stand_type_narration,
    "section:sm_carbon_narration": generate_sm_carbon_narration,
    "section:sm_volume_narration": generate_sm_volume_narration,
    "section:sm_mother_tree_narration": generate_sm_mother_tree_narration,
    "section:sm_felling_narration": generate_sm_felling_narration,
}


# NOTE: entry point — calls all generators and collects results
def collect_section_content(raw_data: dict) -> dict:
    """Run all registered section generators and return collected content by key."""
    sections = {}
    for key, gen_fn in SECTION_GENERATORS.items():
        try:
            result = gen_fn(raw_data)
            sections[key] = result if result else None
        except Exception:
            # A generator that raises produces a None section, which downstream
            # renders as an empty chapter of the operational plan.
            logger.exception(
                "section generator %s failed - that section of the plan will be "
                "empty", key,
            )
            sections[key] = None
    return sections
