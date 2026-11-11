"""
Prompt builder for AI report generation
Constructs prompts for each section with injected data
"""
# business: AI-assisted report generation prompt
# constraint: GPT-4 token limit 8192
# why: prompt structured as section-by-section instructions
import json
from typing import Dict, Any, Optional


SYSTEM_PROMPT = """तपाईं नेपालको वन विभागका अनुभवी अधिकारी हुनुहुन्छ। तपाईंले सामुदायिक वन कार्ययोजना प्रतिवेदन तयार पार्नुपर्छ।

नियमहरू:
1. Nepali भाषामा लेख्नुहोस् (Devanagari script)
2. Technical terms (elevation, slope, biomass, carbon, canopy, DBH, etc.) English मा हुन सक्छन्
3. Official government report style मा लेख्नुहोस्
4. Data लाई table format मा present गर्नुहोस् जहाँ उपयुक्त छ
5. Forest Regulation 2079 को reference दिनुहोस् जहाँ applicable
6. Placeholder छोड्नुहोस् जहाँ data available छैन: "[_________]"
7. Numbers लाई Arabic numerals (१,२,३ होइन 1,2,3) मा लेख्नुहोस्
8. Area लाई हेक्टर (hectares) मा उल्लेख गर्नुहोस्
9. Professional, formal tone प्रयोग गर्नुहोस्"""


def _format_data_for_prompt(data: Dict[str, Any], max_length: int = 5000) -> str:
    """Format data as readable JSON for AI prompt"""
    json_str = json.dumps(data, indent=2, ensure_ascii=False, default=str)
    if len(json_str) > max_length:
        return json_str[:max_length] + "\n... (data truncated)"
    return json_str


def build_section_1_prompt(metadata: Dict, data: Dict) -> str:
    """परिचय (Introduction)"""
    basic = data.get("basic_info", {})
    return f"""{SYSTEM_PROMPT}

तलको data प्रयोग गरेर "परिचय" section लेख्नुहोस्। यसमा सामुदायिक वनको परिचय, उद्देश्य, र पृष्ठभूमि समावेश गर्नुहोस्।

METADATA:
{json.dumps(metadata, indent=2, ensure_ascii=False)}

FOREST DATA:
- Forest Name: {basic.get('forest_name', '')}
- District: {basic.get('district', '')}
- Municipality: {basic.get('municipality', '')}
- Ward: {basic.get('ward', '')}
- Province: {basic.get('province', '')}
- Total Area: {basic.get('total_area_hectares', 0)} hectares
- Watershed: {basic.get('watershed', '')}
- Major River Basin: {basic.get('major_river_basin', '')}

Output length: 150-250 words"""


def build_section_2_prompt(metadata: Dict, data: Dict) -> str:
    """भौगोलिक अवस्थिति (Geographical Location)"""
    basic = data.get("basic_info", {})
    boundary = data.get("boundary", {})
    raster = data.get("raster_analysis", {})

    north = boundary.get('features', {}).get('north') or ['_________']
    east = boundary.get('features', {}).get('east') or ['_________']
    south = boundary.get('features', {}).get('south') or ['_________']
    west = boundary.get('features', {}).get('west') or ['_________']

    return f"""{SYSTEM_PROMPT}

तलको data प्रयोग गरेर "सामुदायिक वन र समूहको भौगोलिक अवस्थिति" section लेख्नुहोस्।
चारकिल्लाको लागि placeholder छोड्नुहोस्।

FOREST DATA:
- Forest Name: {basic.get('forest_name', '')}
- District: {basic.get('district', '')}
- Municipality: {basic.get('municipality', '')}
- Ward: {basic.get('ward', '')}
- Province: {basic.get('province', '')}
- Total Area: {basic.get('total_area_hectares', 0)} hectares
- Effective Area: {basic.get('effective_area_hectares', 0)} hectares
- Number of Blocks: {basic.get('total_blocks', 0)}
- Elevation Range: {raster.get('elevation', {}).get('min_m', 0)}m - {raster.get('elevation', {}).get('max_m', 0)}m
- Mean Elevation: {raster.get('elevation', {}).get('mean_m', 0)}m
- UTM Zone: {basic.get('utm_zone', 0)}

BOUNDARY FEATURES:
- North: {', '.join(north)}
- East: {', '.join(east)}
- South: {', '.join(south)}
- West: {', '.join(west)}

BLOCKS:
{_format_data_for_prompt(boundary.get('blocks', []), 2000)}

Output length: 200-350 words"""


def build_section_3_prompt(metadata: Dict, data: Dict) -> str:
    """वनको किसिम/प्रजाति (Forest Types and Species)"""
    species = data.get("species", {})
    raster = data.get("raster_analysis", {})

    return f"""{SYSTEM_PROMPT}

तलको data प्रयोग गरेर "वनको किसिम मुख्य प्रजाति" section लेख्नुहोस्।

FOREST TYPE:
- Dominant Forest Type: {raster.get('forest_type', {}).get('dominant', '')}
- Forest Type Distribution: {json.dumps(raster.get('forest_type', {}).get('percentages', {}), ensure_ascii=False)}

SPECIES DATA:
- Total Species Found: {species.get('total_species', 0)}
- Species by Role:
{_format_data_for_prompt(species.get('species_by_role', {}), 4000)}

प्रत्येक प्रजातिको scientific name, local name, altitude range, growth rate, economic value उल्लेख गर्नुहोस्।

Output length: 300-500 words"""


def build_section_4_prompt(metadata: Dict, data: Dict) -> str:
    """माग र आपूर्ति (Demand and Supply)"""
    households = data.get("households", {})
    inventory = data.get("inventory", {})
    raster = data.get("raster_analysis", {})

    hh_available = households.get("available", False)
    inv_available = inventory.get("available", False)

    return f"""{SYSTEM_PROMPT}

तलको data प्रयोग गरेर "वन पैदावारको माग र आपूर्तिको अवस्था" section लेख्नुहोस्।

HOUSEHOLD DEMAND (Available: {hh_available}):
{json.dumps(households, indent=2, ensure_ascii=False) if hh_available else "Household survey data not available. Use placeholder for demand data."}

FOREST SUPPLY (Available: {inv_available}):
- Total Timber Volume: {inventory.get('total_volume_m3', 0)} m³
- Total Net Volume: {inventory.get('total_net_volume_m3', 0)} m³ ({inventory.get('total_net_volume_cft', 0)} cft)
- Total Firewood: {inventory.get('total_firewood_m3', 0)} m³ ({inventory.get('total_firewood_chatta', 0)} chatta)
- Total Biomass (AGB): {raster.get('biomass', {}).get('agb_total', 0)} tons
- Carbon Stock: {raster.get('biomass', {}).get('carbon_stock', 0)} tons

माग र आपूर्तिको तुलना गर्नुहोस्। जहाँ data छैन placeholder प्रयोग गर्नुहोस्।

Output length: 200-400 words"""


def build_section_5_prompt(metadata: Dict, data: Dict) -> str:
    """आर्थिक तथा सामाजिक अवस्था (Economic and Social Status)"""
    households = data.get("households", {})
    committees = data.get("committees", {})

    return f"""{SYSTEM_PROMPT}

तलको data प्रयोग गरेर "समूहको आर्थिक तथा सामाजिक अवस्था" section लेख्नुहोस्।

HOUSEHOLD DATA:
{json.dumps(households, indent=2, ensure_ascii=False) if households.get('available') else "Household data not available."}

COMMITTEE DATA:
- User Committee Members: {committees.get('user_committee', {}).get('total_members', 0)}
- Advisory Committee Members: {committees.get('advisory_committee', {}).get('total_members', 0)}
- Financial Committee Members: {committees.get('financial_committee', {}).get('total_members', 0)}

सामाजिक संरचना, आर्थिक अवस्था, र समूहको संगठनात्मक संरचना वर्णन गर्नुहोस्।

Output length: 200-350 words"""


def build_section_7_prompt(metadata: Dict, data: Dict, subsection: str) -> str:
    """वनस्रोत सर्वेक्षण subsections"""
    raster = data.get("raster_analysis", {})
    blocks = data.get("blocks", {})
    species = data.get("species", {})
    inventory = data.get("inventory", {})
    sampling = data.get("sampling", {})
    activities = data.get("activities", {})

    prompts = {
        "क": f"""{SYSTEM_PROMPT}

तलको data प्रयोग गरेर "भू-उपयोग" (Land Use) section लेख्नुहोस्।

LAND COVER:
- Dominant: {raster.get('landcover', {}).get('dominant', '')}
- Distribution: {json.dumps(raster.get('landcover', {}).get('percentages', {}), ensure_ascii=False)}

SLOPE:
- Dominant Class: {raster.get('slope', {}).get('dominant_class', '')}
- Distribution: {json.dumps(raster.get('slope', {}).get('percentages', {}), ensure_ascii=False)}

CANOPY:
- Dominant: {raster.get('canopy', {}).get('dominant_class', '')}
- Distribution: {json.dumps(raster.get('canopy', {}).get('percentages', {}), ensure_ascii=False)}

FOREST HEALTH:
- Dominant: {raster.get('forest_health', {}).get('dominant', '')}
- Distribution: {json.dumps(raster.get('forest_health', {}).get('percentages', {}), ensure_ascii=False)}

FOREST LOSS/GAIN:
- Loss: {raster.get('forest_loss_gain', {}).get('loss_hectares', 0)} hectares
- Gain: {raster.get('forest_loss_gain', {}).get('gain_hectares', 0)} hectares

HISTORICAL LANDCOVER:
- 1984: {raster.get('landcover_historical', {}).get('landcover_1984_dominant', '')}
- 2000: {raster.get('landcover_historical', {}).get('hansen2000_dominant', '')}

भू-उपयोगको विश्लेषण र वर्गीकरण table मा present गर्नुहोस्।

Output length: 250-400 words""",

        "ख": f"""{SYSTEM_PROMPT}

तलको data प्रयोग गरेर "ब्लक/कम्पार्टमेण्ट विभाजन" section लेख्नुहोस्।

BLOCK DATA:
- Total Blocks: {blocks.get('total_blocks', 0)}
- Total Sub-areas: {blocks.get('total_sub_areas', 0)}

BLOCKS:
{_format_data_for_prompt(blocks.get('blocks', []), 3000)}

SUB-AREA SUMMARY:
{json.dumps(blocks.get('sub_areas', {}), indent=2, ensure_ascii=False)}

प्रत्येक block को क्षेत्रफल, नाम, र मौज्दात उल्लेख गर्नुहोस्। Table format मा present गर्नुहोस्।

Output length: 200-350 words""",

        "ग": f"""{SYSTEM_PROMPT}

तलको data प्रयोग गरेर "वन संवर्द्धन प्रणाली छनोटको आधार" section लेख्नुहोस्।

SPECIES DATA:
- Total Species: {species.get('total_species', 0)}

RASTER ANALYSIS:
- Elevation: {raster.get('elevation', {}).get('min_m', 0)}m - {raster.get('elevation', {}).get('max_m', 0)}m
- Slope: {raster.get('slope', {}).get('dominant_class', '')}
- Canopy: {raster.get('canopy', {}).get('dominant_class', '')}
- Forest Type: {raster.get('forest_type', {}).get('dominant', '')}
- Biomass: {raster.get('biomass', {}).get('agb_mean', 0)} t/ha

वन संवर्द्धन प्रणाली छनोट गर्दा consideration दिइएका factors वर्णन गर्नुहोस्।

Output length: 200-300 words""",

        "घ": f"""{SYSTEM_PROMPT}

तलको data प्रयोग गरेर "वन संवर्द्धन प्रणाली तथा क्रियाकलाप" section लेख्नुहोस्।

SAMPLING DATA (Available: {sampling.get('available', False)}):
{json.dumps(sampling, indent=2, ensure_ascii=False) if sampling.get('available') else "Sampling data not available."}

PROPOSED ACTIVITIES (Available: {activities.get('available', False)}):
{json.dumps(activities, indent=2, ensure_ascii=False) if activities.get('available') else "Activities data not available."}

SPECIES DATA:
{_format_data_for_prompt(species.get('species_by_role', {}), 2000)}

कार्यान्वयन समय तालिका र वार्षिक स्वीकार्य कटान table मा present गर्नुहोस्।

Output length: 250-400 words""",

        "ङ": f"""{SYSTEM_PROMPT}

तलको data प्रयोग गरेर "वन पैदावार सङ्कलन चक्र तथा पुनरोत्पादन तरिका" section लेख्नुहोस्।

SPECIES DATA:
{species.get('total_species', 0)} species found
{_format_data_for_prompt(species.get('species_by_role', {}), 3000)}

INVENTORY DATA (Available: {inventory.get('available', False)}):
- Total Trees: {inventory.get('total_trees', 0)}
- Mother Trees: {inventory.get('mother_trees_count', 0)}
- Felling Trees: {inventory.get('felling_trees_count', 0)}
- Seedlings: {inventory.get('seedling_count', 0)}

सङ्कलन चक्र र पुनरोत्पादन तरिका वर्णन गर्नुहोस्।

Output length: 200-350 words""",
    }

    return prompts.get(subsection, "")


def build_section_8_prompt(metadata: Dict, data: Dict, subsection: str) -> str:
    """वन पैदावार उत्पादन subsections"""
    inventory = data.get("inventory", {})
    activities = data.get("activities", {})
    raster = data.get("raster_analysis", {})

    prompts = {
        "क": f"""{SYSTEM_PROMPT}

तलको data प्रयोग गरेर "वन पैदावार कटान, सङ्कलन तथा घाटगद्दी गर्ने समय तालिका" section लेख्नुहोस्।

INVENTORY DATA:
{json.dumps(inventory, indent=2, ensure_ascii=False) if inventory.get('available') else "Inventory data not available."}

BIOMASS DATA:
- Total AGB: {raster.get('biomass', {}).get('agb_total', 0)} tons
- Carbon Stock: {raster.get('biomass', {}).get('carbon_stock', 0)} tons

कटान, सङ्कलन र घाटगद्दी समय तालिका table मा present गर्नुहोस्।

Output length: 150-300 words""",

        "ख": f"""{SYSTEM_PROMPT}

तलको data प्रयोग गरेर "वन पैदावारको मूल्य निर्धारण" section लेख्नुहोस्।

INVENTORY DATA:
- Total Volume: {inventory.get('total_net_volume_cft', 0)} cft
- Total Firewood: {inventory.get('total_firewood_chatta', 0)} chatta

मूल्य निर्धारणको आधार र method वर्णन गर्नुहोस्। Placeholder प्रयोग गर्नुहोस् जहाँ actual pricing data छैन।

Output length: 150-250 words""",
    }

    return prompts.get(subsection, "")


def build_section_9_prompt(metadata: Dict, data: Dict, subsection: str) -> str:
    """संरक्षण व्यवस्थापन subsections"""
    raster = data.get("raster_analysis", {})
    biodiversity = data.get("biodiversity", {})
    activities = data.get("activities", {})
    sampling = data.get("sampling", {})

    prompts = {
        "क": f"""{SYSTEM_PROMPT}

तलको data प्रयोग गरेर "वन डढेलो तथा चरिचरन नियन्त्रण" section लेख्नुहोस्।

FOREST HEALTH DATA:
{json.dumps(raster.get('forest_health', {}), indent=2, ensure_ascii=False)}

SLOPE DATA:
{json.dumps(raster.get('slope', {}), indent=2, ensure_ascii=False)}

डढेलो र चरिचरन नियन्त्रणका उपायहरू वर्णन गर्नुहोस्।

Output length: 150-250 words""",

        "ख": f"""{SYSTEM_PROMPT}

तलको data प्रयोग गरेर "एकीकृत रोग किरा तथा मिचाहा प्रजाति नियन्त्रण" section लेख्नुहोस्।

BIODIVERSITY DATA (Available: {biodiversity.get('available', False)}):
{json.dumps(biodiversity, indent=2, ensure_ascii=False) if biodiversity.get('available') else "Biodiversity data not available."}

रोग, किरा र मिचाहा प्रजाति नियन्त्रणका उपाय वर्णन गर्नुहोस्।

Output length: 150-250 words""",

        "घ": f"""{SYSTEM_PROMPT}

तलको data प्रयोग गरेर "वन्यजन्तु तथा जैविक मार्ग संरक्षण" section लेख्नुहोस्।

BIODIVERSITY DATA:
{json.dumps(biodiversity, indent=2, ensure_ascii=False) if biodiversity.get('available') else "Biodiversity data not available."}

वन्यजन्तु संरक्षण र जैविक मार्गको व्यवस्था वर्णन गर्नुहोस्।

Output length: 150-250 words""",

        "ड": f"""{SYSTEM_PROMPT}

तलको data प्रयोग गरेर "वातावरणीय सेवा मूलप्रवाहीकरण" section लेख्नुहोस्।

BIOMASS/CARBON DATA:
- Total AGB: {raster.get('biomass', {}).get('agb_total', 0)} tons
- Carbon Stock: {raster.get('biomass', {}).get('carbon_stock', 0)} tons

वातावरणीय सेवा (carbon sequestration, water regulation, soil conservation) को महत्व वर्णन गर्नुहोस्।

Output length: 150-250 words""",

        "च": f"""{SYSTEM_PROMPT}

तलको data प्रयोग गरेर "पानीका मुहान, खोला किनार, सिमसार, जलाधार संरक्षण" section लेख्नुहोस्।

WATERSHED DATA:
- Watershed: {raster.get('watershed', '')}
- Precipitation: {raster.get('precipitation', {}).get('mean_mm', 0)} mm (range: {raster.get('precipitation', {}).get('min_mm', 0)}-{raster.get('precipitation', {}).get('max_mm', 0)} mm)
- Temperature: {raster.get('temperature', {}).get('mean_c', 0)}°C (range: {raster.get('temperature', {}).get('min_c', 0)}-{raster.get('temperature', {}).get('max_c', 0)}°C)

मुहान, खोला, सिमसार संरक्षणका उपाय वर्णन गर्नुहोस्।

Output length: 150-250 words""",

        "छ": f"""{SYSTEM_PROMPT}

तलको data प्रयोग गरेर "जलवायुजन्य जोखिम न्यूनीकरण तथा अनुकूलनका उपाय" section लेख्नुहोस्।

CLIMATE DATA:
- Temperature: {raster.get('temperature', {}).get('mean_c', 0)}°C
- Precipitation: {raster.get('precipitation', {}).get('mean_mm', 0)} mm
- Forest Loss: {raster.get('forest_loss_gain', {}).get('loss_hectares', 0)} hectares

जलवायु जोखिम र अनुकूलन उपायहरू वर्णन गर्नुहोस्।

Output length: 150-250 words""",

        "ज": f"""{SYSTEM_PROMPT}

तलको data प्रयोग गरेर "वन संवर्द्धनका क्रियाकलाप" section लेख्नुहोस्।

PROPOSED ACTIVITIES:
{json.dumps(activities, indent=2, ensure_ascii=False) if activities.get('available') else "Activities data not available."}

SAMPLING DESIGN:
{json.dumps(sampling, indent=2, ensure_ascii=False) if sampling.get('available') else "Sampling data not available."}

वन संवर्द्धनका क्रियाकलापहरू table मा present गर्नुहोस्।

Output length: 200-300 words""",
    }

    return prompts.get(subsection, "")


def build_section_11_prompt(metadata: Dict, data: Dict) -> str:
    """वार्षिक बजेट तथा कार्यक्रम"""
    activities = data.get("activities", {})
    return f"""{SYSTEM_PROMPT}

तलको data प्रयोग गरेर "वार्षिक बजेट तथा कार्यक्रम तर्जुमा" section लेख्नुहोस्।

ACTIVITIES DATA:
{json.dumps(activities, indent=2, ensure_ascii=False) if activities.get('available') else "Activities data not available."}

बजेट तर्जुमा, कार्यान्वयन, अनुगमन प्रक्रिया वर्णन गर्नुहोस्।

Output length: 200-300 words"""


def build_section_12_prompt(metadata: Dict, data: Dict) -> str:
    """वार्षिक क्रियाकलाप तथा बजेट"""
    activities = data.get("activities", {})
    basic = data.get("basic_info", {})
    return f"""{SYSTEM_PROMPT}

तलको data प्रयोग गरेर "व्यवस्थापन कार्ययोजना अवधिको लागि वार्षिक क्रियाकलाप तथा बजेट" section लेख्नुहोस्।

FOREST NAME: {basic.get('forest_name', '')}
PLAN PERIOD: {metadata.get('fy_start', '____')} to {metadata.get('fy_end', '____')}

ACTIVITIES AND BUDGET:
{json.dumps(activities, indent=2, ensure_ascii=False) if activities.get('available') else "Activities data not available."}

वार्षिक क्रियाकलाप र बजेट table मा present गर्नुहोस् (10-year plan)।

Output length: 200-400 words"""


def build_section_13_prompt(metadata: Dict, data: Dict) -> str:
    """छिमेकी समूहसँग सहकार्य"""
    user_group = data.get("user_group", {})
    return f"""{SYSTEM_PROMPT}

तलको data प्रयोग गरेर "छिमेकी समूहसँग सहकार्य तथा साझेदारीको व्यवस्था" section लेख्नुहोस्।

USER GROUP DATA:
{json.dumps(user_group, indent=2, ensure_ascii=False) if user_group.get('available') else "User group data not available."}

छिमेकी समूहसँग सहकार्यको व्यवस्था वर्णन गर्नुहोस्।

Output length: 150-250 words"""


def build_section_14_prompt(metadata: Dict, data: Dict) -> str:
    """वित्तीय विश्लेषण"""
    activities = data.get("activities", {})
    return f"""{SYSTEM_PROMPT}

तलको data प्रयोग गरेर "व्यवस्थापन कार्ययोजनाको वित्तीय विश्लेषण" section लेख्नुहोस्।

ACTIVITIES AND BUDGET DATA:
{json.dumps(activities, indent=2, ensure_ascii=False) if activities.get('available') else "Activities data not available."}

वित्तीय विश्लेषण (income, expenditure, NPV, B/C ratio) table मा present गर्नुहोस्।

Output length: 150-300 words"""


def build_generic_section_prompt(metadata: Dict, data: Dict, section_num: int, title: str) -> str:
    """Generic prompt for sections not specifically handled"""
    return f"""{SYSTEM_PROMPT}

तलको data प्रयोग गरेर "{title}" section लेख्नुहोस्।

SECTION NUMBER: {section_num}

FOREST DATA:
{_format_data_for_prompt(data, 4000)}

METADATA:
{json.dumps(metadata, indent=2, ensure_ascii=False)}

यस section को लागि उपयुक्त content लेख्नुहोस्। जहाँ data छैन placeholder "[_________]" प्रयोग गर्नुहोस्।

Output length: 150-300 words"""


BUILDERS = {
    1: build_section_1_prompt,
    2: build_section_2_prompt,
    3: build_section_3_prompt,
    4: build_section_4_prompt,
    5: build_section_5_prompt,
    11: build_section_11_prompt,
    12: build_section_12_prompt,
    13: build_section_13_prompt,
    14: build_section_14_prompt,
}

def build_prompt(section_num: int, subsection: Optional[str], metadata: Dict, data: Dict) -> str:
    """Build AI prompt for a given section"""
    if subsection:
        if section_num == 7:
            return build_section_7_prompt(metadata, data, subsection)
        elif section_num == 8:
            return build_section_8_prompt(metadata, data, subsection)
        elif section_num == 9:
            return build_section_9_prompt(metadata, data, subsection)

    builder = BUILDERS.get(section_num)
    if builder:
        return builder(metadata, data)

    from .section_templates import REPORT_SECTIONS
    section_info = REPORT_SECTIONS.get(section_num, {})
    title = section_info.get("title_ne", f"Section {section_num}")
    return build_generic_section_prompt(metadata, data, section_num, title)
