"""Nepali and English narrative text for management plan chapters.

Provides get_chapter_narrative() which returns the narrative text for
each chapter of the 10-year management plan in both Nepali (Unicode)
and English. Topics include: introduction, location, forest condition,
biodiversity, carbon stock, financial plan, monitoring, and governance.

See also:
    .plan_chapter_builders — calls these narratives when building the DOCX
    .plan_raster_descriptions — related descriptions for map sections
"""

from typing import Dict, List, Any


def ch1_introduction(basic_info: Dict, blocks_count: int) -> Dict[str, str]:
    """Generate Nepali/English narrative for the Introduction chapter."""
    name = basic_info.get("forest_name", "———")
    district = basic_info.get("district", "———")
    area = basic_info.get("total_area_hectares", 0)
    return {
        "ne": (
            f"यो व्यवस्थापन योजना {name} सामुदायिक वनको लागि तयार पारिएको हो। "
            f"यो वन {district} जिल्लामा अवस्थित छ र जम्मा {area:.2f} हेक्टर "
            f"क्षेत्रफलमा फैलिएको छ। वनलाई {blocks_count} वटा ब्लकमा विभाजन "
            f"गरिएको छ। यो १० वर्षे योजना (आर्थिक वर्ष २०८२/८३ देखि २०९१/९२ सम्म) "
            f"ले वनको दिगो व्यवस्थापन, संरक्षण र उपभोक्ताको आवश्यकता पूर्ति गर्ने "
            f"उद्देश्य राख्दछ।"
        ),
        "en": (
            f"This management plan is prepared for {name} Community Forest. "
            f"The forest is located in {district} district with a total area of "
            f"{area:.2f} hectares, divided into {blocks_count} blocks. "
            f"This 10-year plan (FY 2082/83 to 2091/92) aims at sustainable forest "
            f"management, conservation, and meeting community needs."
        ),
    }


def ch2_location(basic_info: Dict, boundary: Dict) -> Dict[str, str]:
    """Generate Nepali/English narrative for the Location chapter."""
    district = basic_info.get("district", "———")
    municipality = basic_info.get("municipality", "———")
    ward = basic_info.get("ward", "———")
    prov = basic_info.get("province", "———")
    area = basic_info.get("total_area_hectares", 0)
    blocks = boundary.get("blocks", [])
    block_names = ", ".join([b.get("name", "") for b in blocks[:5]])
    features = boundary.get("features", {})
    north = ", ".join([f.get("name", "") for f in features.get("north", [])[:3]])
    south = ", ".join([f.get("name", "") for f in features.get("south", [])[:3]])
    east = ", ".join([f.get("name", "") for f in features.get("east", [])[:3]])
    west = ", ".join([f.get("name", "") for f in features.get("west", [])[:3]])
    return {
        "ne": (
            f"यो वन प्रदेश नं. {prov}, {district} जिल्ला, {municipality}–{ward} मा "
            f"अवस्थित छ। जम्मा क्षेत्रफल {area:.2f} हेक्टर रहेको छ। "
            f"ब्लकहरू: {block_names}। "
            f"पूर्व: {east}, पश्चिम: {west}, उत्तर: {north}, दक्षिण: {south}।"
        ),
        "en": (
            f"The forest is located in Province {prov}, {district} district, "
            f"{municipality}–{ward}. Total area is {area:.2f} ha. "
            f"Blocks: {block_names}. "
            f"East: {east}, West: {west}, North: {north}, South: {south}."
        ),
    }


def ch3_physical(raster: Dict) -> Dict[str, str]:
    """Generate Nepali/English narrative for the Physical Environment chapter."""
    elev = raster.get("elevation", {})
    mean_e = elev.get("mean_m", 0)
    sl = raster.get("slope", {})
    dom_slope = sl.get("dominant_class", "")
    temp = raster.get("temperature", {})
    mean_t = temp.get("mean_c", 0)
    precip = raster.get("precipitation", {})
    mean_p = precip.get("mean_mm", 0)
    return {
        "ne": (
            f"वनको औसत उचाइ {mean_e:.0f} मिटर रहेको छ। भिरालो वर्गीकरण अनुसार "
            f"'{dom_slope}' प्रमुख छ। औसत तापक्रम {mean_t:.1f}°C र वार्षिक "
            f"वर्षा {mean_p:.0f} मिमि रहेको छ। यी भौतिक अवस्थाहरूले वनको वृद्धि "
            f"र प्रजाति संरचनामा प्रभाव पार्दछन्।"
        ),
        "en": (
            f"The mean elevation is {mean_e:.0f}m. '{dom_slope}' is the dominant "
            f"slope class. Mean temperature is {mean_t:.1f}°C with annual "
            f"precipitation of {mean_p:.0f}mm. These physical conditions influence "
            f"forest growth and species composition."
        ),
    }


def ch4_forest_type(raster: Dict, species_data: Dict) -> Dict[str, str]:
    """Generate Nepali/English narrative for the Forest Type chapter."""
    ft = raster.get("forest_type", {})
    dom_ft = ft.get("dominant", "")
    species_count = species_data.get("total_species", 0)
    lc = raster.get("landcover", {})
    dom_lc = lc.get("dominant", "")
    return {
        "ne": (
            f"'{dom_ft}' प्रमुख वन प्रकार हो। जम्मा {species_count} प्रजातिहरू "
            f"पाइन्छन्। '{dom_lc}' प्रमुख भू-आवरण हो। वन प्रकार र प्रजाति "
            f"संरचना अनुसार व्यवस्थापन गर्नुपर्दछ।"
        ),
        "en": (
            f"'{dom_ft}' is the dominant forest type with {species_count} total "
            f"species. '{dom_lc}' is the dominant land cover. Management should "
            f"be based on forest type and species composition."
        ),
    }


def ch5_health(raster: Dict, biodiversity: Dict) -> Dict[str, str]:
    """Generate Nepali/English narrative for the Forest Health chapter."""
    fh = raster.get("forest_health", {})
    dom_fh = fh.get("dominant", "")
    flg = raster.get("forest_loss_gain", {})
    loss = flg.get("loss_hectares", 0)
    gain = flg.get("gain_hectares", 0)
    bio_avail = biodiversity.get("available", False)
    bio_count = biodiversity.get("total_species", 0)
    return {
        "ne": (
            f"वनको स्वास्थ्य अवस्था '{dom_fh}' रहेको छ। "
            f"वन क्षति {loss:.2f} हेक्टर र वन वृद्धि {gain:.2f} हेक्टर रहेको छ। "
            + (f"जैविक विविधता अन्तर्गत {bio_count} प्रजातिहरू रेकर्ड गरिएका छन्।"
               if bio_avail else "जैविक विविधता डाटा उपलब्ध छैन।") +
            f" वन स्वास्थ्य सुधारको लागि आवश्यक कार्यक्रमहरू सिफारिस गरिन्छ।"
        ),
        "en": (
            f"Forest health condition is '{dom_fh}'. Forest loss is {loss:.2f} ha "
            f"and gain is {gain:.2f} ha. "
            + (f"{bio_count} biodiversity species recorded."
               if bio_avail else "Biodiversity data not available.") +
            f" Programs for health improvement are recommended."
        ),
    }


def ch6_resource_survey(mgmt_data: Dict) -> Dict[str, str]:
    """Generate Nepali/English narrative for the Resource Survey chapter."""
    sc = mgmt_data.get("species_composition", {})
    fw = sc.get("forest_wide", [])
    species_count = len(fw)
    bc = mgmt_data.get("block_comparison", {})
    ranked = bc.get("ranked", [])
    total_gs = sum(b.get("growing_stock_m3ha", 0) * b.get("area_ha", 0) for b in ranked)
    carb = mgmt_data.get("carbon_per_block", {})
    ft = carb.get("forest_total", {})
    co2e = ft.get("co2e_t", 0)
    return {
        "ne": (
            f"वन सर्वेक्षणमा {species_count} प्रजातिहरू पाइएका छन्। "
            f"जम्मा growing stock {total_gs:.1f} m³ रहेको छ। "
            f"कुल कार्बन भण्डार CO₂e {co2e:.1f} टन रहेको छ। "
            f"यी तथ्यांकहरूले वनको उत्पादकत्व र व्यवस्थापनको आधार निर्धारण गर्दछन्।"
        ),
        "en": (
            f"The forest survey recorded {species_count} species. "
            f"Total growing stock is {total_gs:.1f} m³. "
            f"Total carbon stock is {co2e:.1f} t CO₂e. "
            f"These figures determine forest productivity and management basis."
        ),
    }


def ch7_aah(mgmt_data: Dict) -> Dict[str, str]:
    """Generate Nepali/English narrative for the AAH chapter."""
    bc = mgmt_data.get("block_comparison", {})
    ranked = bc.get("ranked", [])
    total_aah_timber = sum(b.get("aah_timber_m3yr", 0) for b in ranked)
    total_aah_fuel = sum(b.get("aah_fuelwood_m3yr", 0) for b in ranked)
    good_blocks = sum(1 for b in ranked if b.get("condition") == "Good")
    mod_blocks = sum(1 for b in ranked if b.get("condition") == "Moderate")
    weak_blocks = sum(1 for b in ranked if b.get("condition") == "Weak")
    return {
        "ne": (
            f"वार्षिक स्वीकार्य कटान (AAH) गणना अनुसार जम्मा काठ {total_aah_timber:.1f} m³/वर्ष "
            f"र दाउरा {total_aah_fuel:.1f} m³/वर्ष रहेको छ। "
            f"ब्लकहरू: {good_blocks} राम्रो, {mod_blocks} मध्यम, {weak_blocks} कमजोर अवस्थामा छन्। "
            f"AAH निर्धारणले दिगो कटान सुनिश्चित गर्दछ।"
        ),
        "en": (
            f"Annual Allowable Harvest is {total_aah_timber:.1f} m³/yr timber "
            f"and {total_aah_fuel:.1f} m³/yr fuelwood. "
            f"Blocks: {good_blocks} Good, {mod_blocks} Moderate, {weak_blocks} Weak. "
            f"AAH determination ensures sustainable harvesting."
        ),
    }


def ch8_ten_year_plan(mgmt_data: Dict, ten_year: Dict) -> Dict[str, str]:
    """Generate Nepali/English narrative for the Ten-Year Plan chapter."""
    ranked = mgmt_data.get("block_comparison", {}).get("ranked", [])
    total_blocks = len(ranked)
    summary = ten_year.get("summary", {})
    total_harvest = summary.get("total_harvest_m3_10yr", 0)
    total_budget = summary.get("total_budget_10yr", 0)

    # Build per-block rationale
    block_schedule = ten_year.get("block_schedule", {})
    block_lines = []
    for blk_name, schedule in list(block_schedule.items())[:5]:
        year_str = ", ".join(str(y) for y in schedule.get("harvest_years", []))
        block_lines.append(
            f"ब्लक '{blk_name}' — कटान वर्ष: {year_str}। "
            f"कारण: {schedule.get('rationale', 'योजना अनुसार')}।"
        )
    block_text = "\n".join(block_lines)
    return {
        "ne": (
            f"यो १० वर्षे योजनाले {total_blocks} वटा ब्लकहरूको दिगो व्यवस्थापन गर्नेछ। "
            f"जम्मा कटान {total_harvest:.1f} m³ र कुल बजेट रू. {total_budget:,.0f} रहेको छ।\n\n"
            f"ब्लक योजना:\n{block_text}"
        ),
        "en": (
            f"This 10-year plan will manage {total_blocks} blocks sustainably. "
            f"Total harvest is {total_harvest:.1f} m³ with a budget of NRs. {total_budget:,.0f}.\n\n"
            f"Block schedule:\n{block_text}"
        ),
    }


def ch9_conservation(raster: Dict, mgmt_data: Dict) -> Dict[str, str]:
    """Generate Nepali/English narrative for the Conservation chapter."""
    fh = raster.get("forest_health", {})
    dom = fh.get("dominant", "")
    fc = mgmt_data.get("forest_condition_summary", {})
    regen = fc.get("regeneration", [])
    total_regen = sum(r.get("total_nha", 0) for r in regen)
    return {
        "ne": (
            f"वन स्वास्थ्य '{dom}' रहेकोले निम्न संरक्षण कार्यहरू सिफारिस गरिन्छ: "
            f"(क) वन डढेलो नियन्त्रण, (ख) चरिचरन व्यवस्थापन, "
            f"(ग) मिचाहा प्रजाति नियन्त्रण, (घ) पानीका मुहान संरक्षण। "
            f"पुनरुत्पादन अवस्था: कुल {total_regen:.0f} विरुवा/हेक्टर।"
        ),
        "en": (
            f"Forest health is '{dom}'. Recommended conservation activities: "
            f"(a) fire control, (b) grazing management, "
            f"(c) invasive species control, (d) water source conservation. "
            f"Regeneration status: total {total_regen:.0f} seedlings/ha."
        ),
    }


def ch10_activities_budget(activities: Dict, ten_year: Dict) -> Dict[str, str]:
    """Generate Nepali/English narrative for the Activities & Budget chapter."""
    avail = activities.get("available", False)
    total_acts = activities.get("total_activities", 0)
    total_budget_acts = activities.get("total_budget", 0)
    summary = ten_year.get("summary", {})
    plan_budget = summary.get("total_budget_10yr", 0)

    if avail:
        text_ne = (
            f"कुल {total_acts} वटा क्रियाकलापहरू प्रस्ताव गरिएका छन्। "
            f"योजना अवधिको कुल बजेट रू. {plan_budget:,.0f} रहेको छ। "
            f"प्रत्येक वर्षको बजेट र क्रियाकलाप विवरण तलको तालिकामा दिइएको छ।"
        )
        text_en = (
            f"A total of {total_acts} activities are proposed. "
            f"Total budget for the plan period is NRs. {plan_budget:,.0f}. "
            f"Year-wise budget and activities are shown in the table below."
        )
    else:
        text_ne = "क्रियाकलाप डाटा उपलब्ध छैन। वार्षिक कार्यक्रम पछि निर्धारण गरिनेछ।"
        text_en = "Activity data not available. Annual programs will be determined later."
    return {"ne": text_ne, "en": text_en}


def ch11_financial(activities: Dict) -> Dict[str, str]:
    """Generate Nepali/English narrative for the Financial Analysis chapter."""
    avail = activities.get("available", False)
    budget = activities.get("total_budget", 0)
    text_ne = (
        f"योजना अवधिको कुल बजेट रू. {budget:,.0f} रहेको छ। "
        f"आय-आर्जनका मुख्य स्रोतहरू: काठ बिक्री, दाउरा बिक्री, "
        f"र अन्य वन पैदावार हुन्। विस्तृत वित्तीय विश्लेषण तालिकामा दिइएको छ।"
        if avail else "वित्तीय डाटा उपलब्ध छैन।"
    )
    text_en = (
        f"Total budget for the plan period is NRs. {budget:,.0f}. "
        f"Main income sources: timber sales, fuelwood sales, and other forest products. "
        f"Detailed financial analysis is in the table."
        if avail else "Financial data not available."
    )
    return {"ne": text_ne, "en": text_en}


def ch12_monitoring() -> Dict[str, str]:
    """Generate Nepali/English narrative for the Monitoring chapter."""
    return {
        "ne": (
            f"योजनाको अनुगमन प्रत्येक ६ महिनामा गरिनेछ। "
            f"मुख्य सूचकहरू: (क) कटान मात्रा, (ख) पुनरुत्पादन अवस्था, "
            f"(ग) बजेट खर्च, (घ) उपभोक्ता सन्तुष्टि। "
            f"वार्षिक प्रतिवेदन डिभिजन वन कार्यालयमा पेस गरिनेछ।"
        ),
        "en": (
            f"Monitoring will be conducted every 6 months. "
            f"Key indicators: (a) harvest quantity, (b) regeneration status, "
            f"(c) budget expenditure, (d) user satisfaction. "
            f"Annual reports will be submitted to the Division Forest Office."
        ),
    }


def get_chapter_narrative(chapter: int, basic_info: Dict = None,
                          boundary: Dict = None, raster: Dict = None,
                          species_data: Dict = None, mgmt_data: Dict = None,
                          biodiversity: Dict = None, activities: Dict = None,
                          ten_year: Dict = None) -> Dict[str, str]:
    """Dispatch to the appropriate chapter narrative function by chapter number."""
    if basic_info is None:
        basic_info = {}
    if boundary is None:
        boundary = {}
    if raster is None:
        raster = {}
    if species_data is None:
        species_data = {}
    if mgmt_data is None:
        mgmt_data = {}
    if biodiversity is None:
        biodiversity = {}
    if activities is None:
        activities = {}
    if ten_year is None:
        ten_year = {}

    narrators = {
        1:  lambda: ch1_introduction(basic_info, len(boundary.get("blocks", []))),
        2:  lambda: ch2_location(basic_info, boundary),
        3:  lambda: ch3_physical(raster),
        4:  lambda: ch4_forest_type(raster, species_data),
        5:  lambda: ch5_health(raster, biodiversity),
        6:  lambda: ch6_resource_survey(mgmt_data),
        7:  lambda: ch7_aah(mgmt_data),
        8:  lambda: ch8_ten_year_plan(mgmt_data, ten_year),
        9:  lambda: ch9_conservation(raster, mgmt_data),
        10: lambda: ch10_activities_budget(activities, ten_year),
        11: lambda: ch11_financial(activities),
        12: lambda: ch12_monitoring(),
    }
    fn = narrators.get(chapter)
    if fn:
        return fn()
    return {"ne": "", "en": ""}
