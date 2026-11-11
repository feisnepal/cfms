"""Nepali narration generators for household-related OP sections.

Generates plain-language Nepali paragraphs for Household Data, Forest
Committee, User Group, and Demand-Supply sections of the Operational Plan
document. Each generator reads structured data and returns a Nepali
Unicode string suitable for DOCX embedding.

See also:
    .section_generators — orchestrates these generators in the doc tree
"""

from typing import Any, Dict, Optional
from app.utils.number_format import format_devanagari as fmt


def generate_household_narration(raw_data: dict) -> Optional[str]:
    """Generate Nepali summary paragraph for Household Data section."""
    hh = raw_data.get("households", {})
    if not hh.get("available"):
        return None

    total = hh.get("total_households", 0)
    pop = hh.get("total_population", 0)
    male = hh.get("total_male", 0)
    female = hh.get("total_female", 0)
    timber = hh.get("timber_demand_cft", 0)
    firewood = hh.get("firewood_demand_bhari", 0)
    forest_occ = hh.get("forest_based_occupation", 0)

    prosperity = hh.get("prosperity_distribution", {})
    caste = hh.get("caste_distribution", {})
    prosperous_count = sum(prosperity.values()) if prosperity else 0

    parts = [
        f"यस सामुदायिक वन उपभोक्ता समूहमा जम्मा {fmt(total, 0)} घरधुरी रहेका छन्।",
    ]

    if pop:
        parts.append(
            f"कुल जनसंख्या {fmt(pop, 0)} रहेको छ, "
            f"जसमा पुरुष {fmt(male, 0)} र महिला {fmt(female, 0)} रहेका छन्।"
        )

    if prosperous_count > 0:
        sorted_prosperity = sorted(prosperity.items(), key=lambda x: x[1], reverse=True)
        prosperity_desc = ", ".join(
            f"{k}: {fmt(v, 0)} घरधुरी" for k, v in sorted_prosperity
        )
        parts.append(f"समृद्धि वितरण: {prosperity_desc}।")

    if caste:
        sorted_caste = sorted(caste.items(), key=lambda x: x[1], reverse=True)
        caste_desc = ", ".join(
            f"{k}: {fmt(v, 0)} घरधुरी" for k, v in sorted_caste
        )
        parts.append(f"जातीय वर्गीकरण: {caste_desc}।")

    if forest_occ:
        parts.append(
            f"वनमा आधारित पेशा भएका घरधुरी {fmt(forest_occ, 0)} रहेका छन्।"
        )

    if timber or firewood:
        demand_parts = []
        if timber:
            demand_parts.append(f"काठ: {fmt(timber, 2)} घनफिट")
        if firewood:
            demand_parts.append(f"दाउरा: {fmt(firewood, 2)} भारी")
        parts.append(
            f"वार्षिक वन पैदावार माग: {' ,'.join(demand_parts)} रहेको छ।"
        )

    return " ".join(parts)


def generate_committee_narration(raw_data: dict) -> Optional[str]:
    """Generate Nepali summary paragraph for Forest User Committee section."""
    cm = raw_data.get("committees", {})
    uc = cm.get("user_committee", {})
    ac = cm.get("advisory_committee", {})
    fc = cm.get("financial_committee", {})
    ug = raw_data.get("user_group", {})

    uc_total = uc.get("total_members", 0)
    ac_total = ac.get("total_members", 0)
    fc_total = fc.get("total_members", 0)
    settlements = ug.get("total_settlements", 0)

    if not uc_total and not ac_total and not fc_total:
        return None

    parts = []

    if uc_total:
        uc_members = uc.get("members", [])
        women_count = sum(1 for m in uc_members if m.get("gender") == "महिला")
        men_count = sum(1 for m in uc_members if m.get("gender") == "पुरूष")

        parts.append(
            f"यस सामुदायिक वनको उपभोक्ता समितिमा जम्मा {fmt(uc_total, 0)} जना सदस्य रहेका छन्।"
        )
        if women_count or men_count:
            parts.append(
                f"जसमध्ये महिला {fmt(women_count, 0)} जना र पुरुष {fmt(men_count, 0)} जना रहेका छन्।"
            )

        positions = {}
        for m in uc_members:
            pos = m.get("position", "सदस्य")
            positions[pos] = positions.get(pos, 0) + 1
        if positions:
            pos_desc = ", ".join(f"{k}: {fmt(v, 0)}" for k, v in positions.items())
            parts.append(f"पद वितरण: {pos_desc}।")

    if ac_total:
        parts.append(f"सल्लाहकार समितिमा {fmt(ac_total, 0)} जना सदस्य रहेका छन्।")

    if fc_total:
        parts.append(f"वित्त समितिमा {fmt(fc_total, 0)} जना सदस्य रहेका छन्।")

    if settlements:
        parts.append(
            f"समूहको क्षेत्रमा {fmt(settlements, 0)} वटा बस्तीहरू रहेका छन्।"
        )

    return " ".join(parts)


def generate_user_group_narration(raw_data: dict) -> Optional[str]:
    """Generate Nepali summary paragraph for User Group Map section."""
    ug = raw_data.get("user_group", {})
    buildings_available = ug.get("total_settlements", 0) > 0 or ug.get("total_buildings", 0) > 0
    if not ug.get("available") and not buildings_available:
        return None

    total_settlements = ug.get("total_settlements", 0)
    total_buildings = ug.get("total_buildings", 0)
    area_ha = ug.get("user_group_area_ha", 0)
    total_biomass = ug.get("total_biomass_mg", 0)
    total_volume = ug.get("total_volume_m3", 0)
    avg_biomass = ug.get("avg_biomass_mg_per_ha", 0)
    avg_volume = ug.get("avg_volume_m3_per_ha", 0)

    # Land cover breakdown
    land_cover = ug.get("land_cover_classes", [])
    forest_cover = next(
        (c for c in land_cover if c.get("class_name", "").lower() in ("tree cover", "forest", "वन")),
        None,
    )

    if not total_settlements and not total_buildings and not area_ha:
        return None

    parts = [
        f"यस उपभोक्ता समूहको क्षेत्रमा जम्मा {fmt(total_settlements, 0)} वटा बस्तीहरू "
        f"र {fmt(total_buildings, 0)} वटा भवनहरू रहेका छन्।"
    ]

    if area_ha:
        parts.append(f"उपभोक्ता समूहको कुल क्षेत्रफल {fmt(area_ha, 2)} हेक्टर रहेको छ।")

    if forest_cover:
        forest_area = forest_cover.get("area_ha", 0)
        forest_pct = forest_cover.get("percentage", 0)
        parts.append(
            f"क्षेत्रको {fmt(forest_pct, 1)}% भाग अर्थात {fmt(forest_area, 2)} हेक्टर क्षेत्रमा "
            f"रूख आवरण रहेको छ।"
        )

    if total_biomass or total_volume:
        resource_parts = []
        if total_biomass:
            resource_parts.append(f"कुल जैविक पदार्थ {fmt(total_biomass, 2)} मेगाग्राम")
        if total_volume:
            resource_parts.append(f"कुल आयतन {fmt(total_volume, 2) } घनमिटर")
        parts.append(
            f"{', '.join(resource_parts)} रहेको छ।"
        )

    if avg_biomass or avg_volume:
        avg_parts = []
        if avg_biomass:
            avg_parts.append(f"औसत जैविक पदार्थ {fmt(avg_biomass, 2)} मेगाग्राम/हेक्टर")
        if avg_volume:
            avg_parts.append(f"औसत आयतन {fmt(avg_volume, 2)} घनमिटर/हेक्टर")
        parts.append(
            f"{', '.join(avg_parts)} रहेको छ।"
        )

    return " ".join(parts)


def generate_demand_supply_narration(raw_data: dict) -> Optional[str]:
    """Generate Nepali summary paragraph for Demand & Supply section."""
    ds = raw_data.get("demand_supply", {})
    deficit = ds.get("deficit", {})
    if not deficit:
        return None

    fw = deficit.get("firewood_bhari", 0)
    gr = deficit.get("grass_bhari", 0)
    bd = deficit.get("bedding_bhari", 0)
    tm = deficit.get("timber_cft", 0)
    pl = deficit.get("poles_count", 0)

    def _status(val, unit_np):
        if val is None:
            return "—"
        if val > 0:
            return f"{fmt(abs(val), 1)} {unit_np} बचत"
        elif val < 0:
            return f"{fmt(abs(val), 1)} {unit_np} अभाव"
        return "सन्तुलित"

    return (
        "यस तालिकाले उपभोक्ता समूहका घरधुरीहरूको वन पैदावार माग र आपूर्ति अवस्था देखाउँदछ। "
        "मागको गणना घरधुरी सर्वेक्षण (Household Survey) का आधारमा गरिएको छ। "
        "सामुदायिक वनबाट हुने आपूर्ति दुई भागमा विभाजन गरिएको छ: "
        "(क) नियमित सङ्कलन — दाउरा, घाँस र सोतर जस्ता वर्षभरि सङ्कलन हुने सामान्य वन पैदावारहरू, "
        "जुन क्षेत्र सर्वेक्षणमा उल्लेख गरिएको प्रति १ सय वर्गमिटर वार्षिक उपज (केजी) लाई प्रति हेक्टरमा "
        "रूपान्तरण (× १००) गरी वन ब्लकको क्षेत्रफलले गुणन गरी ३० केजी = १ भारी का दरले भारीमा "
        "गणना गरिएको छ। "
        "(ख) वार्षिक स्वीकार्य कटान (AAH) — काठ र खाँवाको लागि वन अवस्था र वृद्धि दरमा आधारित दिगो उपज। "
        "निजी क्षेत्रबाट हुने आपूर्ति जमिन वर्गीकरण (Land Cover) का आधारमा अनुमान गरिएको छ। "
        f"आपूर्ति र माग बीचको अन्तर: दाउरा ({_status(fw, 'भारी')}), "
        f"घाँस ({_status(gr, 'भारी')}), "
        f"सोतर ({_status(bd, 'भारी')}), "
        f"काठ ({_status(tm, 'क्यू.फि.')}), "
        f"खाँवा ({_status(pl, 'संख्या')})."
    )
