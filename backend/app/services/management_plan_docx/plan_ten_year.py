"""10-year activity plan builder for management plans.

Defines activity templates for each forest condition class (Good,
Moderate, Poor, Regeneration) and builds the 10-year activity schedule
with per-block recommendations for harvesting, thinning, planting, and
conservation activities.

Key function:
    build_ten_year_plan() — generates the 10-year activity matrix.

See also:
    .plan_docx_builder — calls this builder during DOCX assembly
"""

from typing import Dict, List, Optional, Any


ACTIVITY_TEMPLATES = {
    "Good": {
        "activity": "Commercial timber harvesting (व्यावसायिक काठ कटान)",
        "rationale": (
            "यस ब्लकको अवस्था राम्रो छ, उच्च growing stock रहेकोले "
            "व्यावसायिक काठ कटान उपयुक्त हुन्छ। नियमित अन्तरालमा "
            "कटान गर्दा वनको स्वास्थ्य कायम रहन्छ।"
        ),
        "rationale_en": (
            "This block is in Good condition with high growing stock, "
            "making it suitable for commercial timber harvesting. "
            "Regular harvesting maintains forest health."
        ),
    },
    "Moderate": {
        "activity": "Improvement felling + thinning (सुधारात्मक कटान + पातलो गर्ने)",
        "rationale": (
            "यस ब्लकको अवस्था मध्यम छ। सुधारात्मक कटान र पातलो गर्ने "
            "कार्यले ब्लकको स्वास्थ्य सुधार गर्न मद्दत गर्दछ। कमजोर "
            "र रोगी रुखहरू हटाउनुपर्दछ।"
        ),
        "rationale_en": (
            "This block is in Moderate condition. Improvement felling "
            "and thinning will improve block health. Weak and diseased "
            "trees should be removed."
        ),
    },
    "Weak": {
        "activity": "Protection + enrichment planting (संरक्षण + वृद्धि रोपण)",
        "rationale": (
            "यस ब्लकको अवस्था कमजोर छ। यसलाई पुनरुत्थानको लागि समय "
            "चाहिन्छ। केवल हल्का कटान, मृत रुख हटाउने, र वृद्धि रोपण "
            "गर्नुपर्दछ।"
        ),
        "rationale_en": (
            "This block is in Weak condition and needs time for "
            "recovery. Only light harvesting, dead wood removal, "
            "and enrichment planting should be done."
        ),
    },
}

CONDITION_PRIORITY = {
    "Moderate": 0,  # First — needs improvement earliest
    "Good": 1,      # Next — commercial harvest mid-plan
    "Weak": 2,      # Last — rest and recovery
}


def _compute_rotation(condition: str, area_ha: float) -> int:
    base = {"Good": 5, "Moderate": 7, "Weak": 10}
    r = base.get(condition, 7)
    min_coupe = max(2.0, area_ha * 0.15)
    rotation_by_area = max(1, int(area_ha / min_coupe))
    return max(r, rotation_by_area)


def build_ten_year_plan(mgmt_data: Dict, activities_data: Optional[Dict] = None) -> Dict:
    """
    Build a 10-year block-wise management plan.

    Algorithm:
    1. Sort blocks by condition priority: Moderate first, then Good, then Weak
    2. Assign harvest years based on rotation
    3. Overlay existing Yearly Activities if available
    4. Generate rationale per block

    Args:
        mgmt_data: Output from get_management_plan_data()
        activities_data: Output from data_collector.get_activities_data()

    Returns:
        Dict with years[], block_schedule{}, summary{}
    """
    ranked = mgmt_data.get("block_comparison", {}).get("ranked", [])
    harvest_blocks = mgmt_data.get("annual_harvest_plan", {}).get("blocks", [])

    if not ranked:
        return {
            "years": {y: [] for y in range(1, 11)},
            "block_schedule": {},
            "summary": {
                "total_harvest_m3_10yr": 0,
                "total_budget_10yr": 0,
                "average_yearly_harvest_m3": 0,
            },
        }

    # Merge ranked with harvest data
    harvest_by_name = {}
    for hb in harvest_blocks:
        name = hb.get("name", "")
        harvest_by_name[name] = hb

    enrich_ranked = []
    for blk in ranked:
        name = blk.get("name", "")
        hb = harvest_by_name.get(name, {})
        enrich_ranked.append({
            "name": name,
            "condition": blk.get("condition", "Moderate"),
            "area_ha": blk.get("area_ha", 0),
            "growing_stock_m3ha": blk.get("growing_stock_m3ha", 0),
            "aah_timber_m3yr": hb.get("aah_timber_m3yr", blk.get("aah_timber_m3yr", 0)),
            "aah_fuelwood_m3yr": hb.get("aah_fuelwood_m3yr", blk.get("aah_fuelwood_m3yr", 0)),
            "coupe_area_ha": hb.get("coupe_area_ha", blk.get("area_ha", 0) / 5),
            "rotation_yrs": hb.get("rotation_yrs", 0),
        })

    # Sort by condition priority
    sorted_blocks = sorted(
        enrich_ranked,
        key=lambda b: (CONDITION_PRIORITY.get(b["condition"], 9), b["name"])
    )

    block_schedule = {}
    years_data = {y: [] for y in range(1, 11)}
    current_year = 1

    for blk in sorted_blocks:
        name = blk["name"]
        condition = blk["condition"]
        area = blk["area_ha"]
        aah_timber = blk["aah_timber_m3yr"]
        aah_fuel = blk["aah_fuelwood_m3yr"]
        rotation = int(blk["rotation_yrs"]) if blk["rotation_yrs"] and blk["rotation_yrs"] > 0 else int(_compute_rotation(condition, area))
        if rotation < 1:
            rotation = 10
        template = ACTIVITY_TEMPLATES.get(condition, ACTIVITY_TEMPLATES["Moderate"])

        # Distribute harvest years across 10 years based on rotation
        harvest_years = []
        for y in range(current_year, 11, rotation):
            if y <= 10:
                harvest_years.append(y)

        if not harvest_years:
            harvest_years = [10]  # At minimum, schedule in final year

        # Reset pointer if we've exhausted
        current_year += 1
        if current_year > 10:
            current_year = 1

        yearly_activities = []
        for hy in harvest_years:
            yearly_activities.append({
                "year": hy,
                "activity": template["activity"],
                "activity_en": template["activity"].split("(")[1].rstrip(")") if "(" in template["activity"] else template["activity"],
                "area_ha": round(area / len(harvest_years), 2),
                "harvest_timber_m3": round(aah_timber / len(harvest_years), 2) if hy == harvest_years[0] else 0,
                "harvest_fuelwood_m3": round(aah_fuel / len(harvest_years), 2) if hy == harvest_years[0] else 0,
                "budget": round(aah_timber * 500 / len(harvest_years), 2),
            })
            years_data[hy].append({
                "block": name,
                "condition": condition,
                "activity": template["activity"],
                "activity_en": template["activity"].split("(")[1].rstrip(")") if "(" in template["activity"] else template["activity"],
                "area_ha": round(area / len(harvest_years), 2),
                "harvest_timber_m3": round(aah_timber / len(harvest_years), 2) if hy == harvest_years[0] else 0,
                "harvest_fuelwood_m3": round(aah_fuel / len(harvest_years), 2) if hy == harvest_years[0] else 0,
                "budget": round(aah_timber * 500 / len(harvest_years), 2),
            })

        block_schedule[name] = {
            "condition": condition,
            "area_ha": area,
            "growing_stock_m3ha": blk["growing_stock_m3ha"],
            "aah_timber_m3yr": aah_timber,
            "aah_fuelwood_m3yr": aah_fuel,
            "rotation_yrs": rotation,
            "harvest_years": harvest_years,
            "activities": yearly_activities,
            "rationale": template["rationale"],
            "rationale_en": template["rationale_en"],
        }

    # Merge with existing Yearly Activities if available
    if activities_data and activities_data.get("available"):
        existing_acts = activities_data.get("activities", [])
        # Note: We log existing activities for reference but the detailed
        # merge requires activity_id mapping which is a future enhancement.
        # For now, the default schedule is generated above.

    # Compute summary
    total_harvest = sum(
        sum(a.get("harvest_timber_m3", 0) for a in acts)
        for acts in years_data.values()
    )
    total_budget = sum(
        sum(a.get("budget", 0) for a in acts)
        for acts in years_data.values()
    )

    summary = {
        "total_harvest_m3_10yr": round(total_harvest, 2),
        "total_budget_10yr": round(total_budget, 2),
        "average_yearly_harvest_m3": round(total_harvest / 10, 2),
        "average_yearly_budget": round(total_budget / 10, 2),
        "total_blocks": len(sorted_blocks),
    }

    return {
        "years": years_data,
        "block_schedule": block_schedule,
        "summary": summary,
    }
