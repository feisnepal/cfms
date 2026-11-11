"""Raster analysis descriptions for management plan maps.

Generates plain-language descriptions (Nepali + English) of raster
analysis layers used in management plan maps: boundary overview, DEM
(elevation), slope, aspect, land cover, forest type, and canopy cover.
Each describe_*() function returns a dict with 'ne' and 'en' keys.

See also:
    .plan_narrative — broader chapter narratives
    .plan_map_service — embeds these descriptions alongside map images
"""

from typing import Dict, Optional


def describe_boundary(raster: Dict, basic_info: Dict, blocks_count: int) -> Dict[str, str]:
    """Generate Nepali/English description for the forest boundary map."""
    district = basic_info.get("district", "———")
    municipality = basic_info.get("municipality", "———")
    ward = basic_info.get("ward", "———")
    area = basic_info.get("total_area_hectares", 0)
    return {
        "ne": (
            f"यो नक्साले वनको सिमाना, ब्लकहरू र वरपरको भौगोलिक अवस्थिति देखाउँदछ। "
            f"वन {district} जिल्ला, {municipality}–{ward} मा अवस्थित छ। "
            f"जम्मा क्षेत्रफल {area:.2f} हेक्टर र {blocks_count} वटा ब्लकहरू रहेका छन्।"
        ),
        "en": (
            f"This map shows the forest boundary, blocks, and surrounding geography. "
            f"The forest is located in {district} district, {municipality}–{ward}. "
            f"Total area is {area:.2f} hectares with {blocks_count} blocks."
        ),
    }


def describe_dem(raster: Dict, forest_name: str = "") -> Dict[str, str]:
    """Generate Nepali/English description for the elevation (DEM) map."""
    elev = raster.get("elevation", {})
    min_e = elev.get("min_m", 0)
    max_e = elev.get("max_m", 0)
    mean_e = elev.get("mean_m", 0)
    return {
        "ne": (
            f"यो नक्साले {forest_name} वनको उचाइ वितरण देखाउँदछ। "
            f"न्यूनतम उचाइ {min_e:.0f} मिटर, अधिकतम {max_e:.0f} मिटर "
            f"र औसत उचाइ {mean_e:.0f} मिटर रहेको छ।"
        ),
        "en": (
            f"This map shows the elevation distribution of {forest_name}. "
            f"Minimum elevation is {min_e:.0f}m, maximum {max_e:.0f}m, "
            f"and mean elevation is {mean_e:.0f}m."
        ),
    }


def describe_slope(raster: Dict, forest_name: str = "") -> Dict[str, str]:
    """Generate Nepali/English description for the slope classification map."""
    sl = raster.get("slope", {})
    dominant = sl.get("dominant_class", "")
    pcts = sl.get("percentages", {})
    steep = pcts.get("Steep", 0) + pcts.get("Very Steep", 0)
    return {
        "ne": (
            f"यो नक्साले {forest_name} वनको भिरालो वर्गीकरण देखाउँदछ। "
            f"'{dominant}' भिरालो प्रमुख रहेको छ। "
            f"{steep:.1f}% भू-भाग भिरालो (३१° भन्दा बढी) रहेको छ, "
            f"जहाँ माटो क्षय र वन विनाशको जोखिम उच्च छ।"
        ),
        "en": (
            f"This map shows the slope classification of {forest_name}. "
            f"'{dominant}' slope is dominant. "
            f"{steep:.1f}% of the area has steep slopes (>31°), "
            f"where erosion and deforestation risk is high."
        ),
    }


def describe_aspect(raster: Dict, forest_name: str = "") -> Dict[str, str]:
    """Generate Nepali/English description for the aspect (slope direction) map."""
    asp = raster.get("aspect", {})
    dominant = asp.get("dominant", "")
    return {
        "ne": (
            f"यो नक्साले {forest_name} वनको भू-भाग दिशा (aspect) देखाउँदछ। "
            f"'{dominant}' मुख्य दिशा रहेको छ, जसले वनमा पुग्ने घामको मात्रा "
            f"र सुख्खापनलाई प्रभाव पार्दछ।"
        ),
        "en": (
            f"This map shows the aspect (slope direction) of {forest_name}. "
            f"'{dominant}' is the dominant aspect, influencing sunlight "
            f"exposure and moisture levels."
        ),
    }


def describe_soil(raster: Dict, forest_name: str = "") -> Dict[str, str]:
    """Generate Nepali/English description for the soil texture map."""
    soil = raster.get("soil", {})
    dominant = soil.get("dominant_type", "")
    return {
        "ne": (
            f"यो नक्साले {forest_name} वनको माटोको बनावट देखाउँदछ। "
            f"'{dominant}' माटो प्रमुख रहेको छ। माटोको गुणस्तरले वनको "
            f"वृद्धि र उत्पादकत्वमा प्रत्यक्ष प्रभाव पार्दछ।"
        ),
        "en": (
            f"This map shows the soil texture of {forest_name}. "
            f"'{dominant}' soil type is dominant. Soil quality directly "
            f"affects forest growth and productivity."
        ),
    }


def describe_forest_type(raster: Dict, forest_name: str = "") -> Dict[str, str]:
    """Generate Nepali/English description for the forest type map."""
    ft = raster.get("forest_type", {})
    dominant = ft.get("dominant", "")
    return {
        "ne": (
            f"यो नक्साले {forest_name} वनको वन प्रकार वितरण देखाउँदछ। "
            f"'{dominant}' प्रमुख वन प्रकार हो। वन प्रकार अनुसार "
            f"व्यवस्थापन गर्नु आवश्यक छ।"
        ),
        "en": (
            f"This map shows the forest type distribution of {forest_name}. "
            f"'{dominant}' is the dominant forest type. Management should "
            f"be tailored to the forest type."
        ),
    }


def describe_landcover(raster: Dict, forest_name: str = "") -> Dict[str, str]:
    """Generate Nepali/English description for the land cover map."""
    lc = raster.get("landcover", {})
    dominant = lc.get("dominant", "")
    return {
        "ne": (
            f"यो नक्साले {forest_name} वनको भू-आवरण वितरण देखाउँदछ। "
            f"'{dominant}' प्रमुख भू-आवरण हो। रुखको आवरणले वनको "
            f"स्वास्थ्य र जैविक विविधता संकेत गर्दछ।"
        ),
        "en": (
            f"This map shows the land cover distribution of {forest_name}. "
            f"'{dominant}' is the dominant land cover class. Tree cover "
            f"indicates forest health and biodiversity."
        ),
    }


def describe_forest_health(raster: Dict, forest_name: str = "") -> Dict[str, str]:
    """Generate Nepali/English description for the forest health map."""
    fh = raster.get("forest_health", {})
    dominant = fh.get("dominant", "")
    return {
        "ne": (
            f"यो नक्साले {forest_name} वनको स्वास्थ्य अवस्था देखाउँदछ। "
            f"'{dominant}' अवस्था प्रमुख रहेको छ। यसले वनमा आवश्यक "
            f"पर्ने संरक्षण र सुधारात्मक कार्यहरू निर्धारण गर्न मद्दत गर्दछ।"
        ),
        "en": (
            f"This map shows the forest health condition of {forest_name}. "
            f"'{dominant}' condition is dominant. This helps determine "
            f"required conservation and improvement activities."
        ),
    }


def describe_canopy(raster: Dict, forest_name: str = "") -> Dict[str, str]:
    """Generate Nepali/English description for the canopy cover map."""
    can = raster.get("canopy", {})
    dominant = can.get("dominant_class", "")
    mean_h = can.get("mean_m")
    if mean_h is None:
        mean_h = 0.0
    return {
        "ne": (
            f"यो नक्साले {forest_name} वनको वन छाना (canopy) वितरण देखाउँदछ। "
            f"'{dominant}' प्रमुख छ। औसत वन छाना उचाइ {mean_h:.1f} मिटर रहेको छ।"
        ),
        "en": (
            f"This map shows the canopy cover distribution of {forest_name}. "
            f"'{dominant}' class is dominant. Average canopy height is "
            f"{mean_h:.1f} meters."
        ),
    }


def describe_biomass(raster: Dict, forest_name: str = "") -> Dict[str, str]:
    """Generate Nepali/English description for the biomass map."""
    bio = raster.get("biomass", {})
    mean_b = bio.get("agb_mean", 0)
    total_b = bio.get("agb_total", 0)
    return {
        "ne": (
            f"यो नक्साले {forest_name} वनको माथिल्लो भू-भाग जैविक पदार्थ "
            f"(Above Ground Biomass) देखाउँदछ। औसत {mean_b:.1f} Mg/ha "
            f"र जम्मा {total_b:.1f} Mg रहेको छ।"
        ),
        "en": (
            f"This map shows the Above Ground Biomass of {forest_name}. "
            f"Mean AGB is {mean_b:.1f} Mg/ha with a total of {total_b:.1f} Mg."
        ),
    }


def describe_layer(layer_name: str, raster: Dict, basic_info: Dict = None,
                   forest_name: str = "", blocks_count: int = 0) -> Dict[str, str]:
    """Dispatch to the appropriate describe_* function by layer name."""
    if basic_info is None:
        basic_info = {}

    dispatcher = {
        "boundary":      lambda: describe_boundary(raster, basic_info, blocks_count),
        "dem":           lambda: describe_dem(raster, forest_name),
        "slope":         lambda: describe_slope(raster, forest_name),
        "aspect":        lambda: describe_aspect(raster, forest_name),
        "soil_texture":  lambda: describe_soil(raster, forest_name),
        "forest_type":   lambda: describe_forest_type(raster, forest_name),
        "landcover":     lambda: describe_landcover(raster, forest_name),
        "forest_health": lambda: describe_forest_health(raster, forest_name),
        "canopy":        lambda: describe_canopy(raster, forest_name),
        "biomass":       lambda: describe_biomass(raster, forest_name),
    }
    fn = dispatcher.get(layer_name)
    if fn:
        return fn()
    return {"ne": layer_name, "en": layer_name}
