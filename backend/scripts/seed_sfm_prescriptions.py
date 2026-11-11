"""Seed / re-seed ``sfm_forest_type_prescriptions`` — the 14 rows of
दिगो वन व्यवस्थापन कार्यविधि, २०७९ अनुसूची-१.

Called from migration 082 and re-runnable standalone (P7 "reset to guideline"):

    cd backend && python -m scripts.seed_sfm_prescriptions

Idempotent — an upsert keyed on ``type_no``. Editing a row here and re-running
overwrites any hand-tuning done via ``PUT /admin/sfm-prescriptions/{type_no}``,
so P7's admin UI is the day-to-day path; this is the canonical baseline.

The numbers are transcribed from
``testData/दिगो वन व्यवस्थापन कार्यविधि/अनुसूची-१.md``. Ranges and per-species
rotations that the yield maths do not consume are carried in the note text; only
``felling_cycle_years`` / ``regeneration_period_years`` feed a formula.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

# Silvicultural-system method keys (must match yield_regulation in P3).
SELECTION = "selection_felling_cycle"
SHELTERWOOD = "shelterwood_periodic_block"
STEM_COUNT = "stem_count"
AREA_COUPE = "area_coupe"


def _steps(
    *triples: tuple[Optional[float], Optional[float], float]
) -> list[dict[str, Any]]:
    """(gs_per_ha_min, gs_per_ha_max, pct) → step dicts. A step matches when
    ``(min is None or gs >= min) and (max is None or gs < max)``."""
    return [
        {"gs_per_ha_min": mn, "gs_per_ha_max": mx, "pct": pct}
        for mn, mx, pct in triples
    ]


def _branch(
    *,
    method: str,
    system_ne: str,
    system_en: str,
    yield_basis: str,
    felling_cycle_years: Optional[int] = None,
    regeneration_period_years: Optional[int] = None,
    rotation_years: Optional[int] = None,
    regen_method_ne: str = "प्राकृतिक",
    regen_method_en: str = "Natural",
    mother_trees_per_ha: Optional[list[int]] = None,
    steps: Optional[list[dict[str, Any]]] = None,
    target_stems_per_ha: Optional[list[int]] = None,
    yield_note_ne: str = "",
    yield_note_en: str = "",
    note_ne: str = "",
    note_en: str = "",
) -> dict[str, Any]:
    return {
        "method": method,
        "system_ne": system_ne,
        "system_en": system_en,
        "felling_cycle_years": felling_cycle_years,
        "regeneration_period_years": regeneration_period_years,
        "rotation_years": rotation_years,
        "regen_method_ne": regen_method_ne,
        "regen_method_en": regen_method_en,
        "mother_trees_per_ha": mother_trees_per_ha,
        "yield_rules": {
            "basis": yield_basis,
            "steps": steps,
            "target_stems_per_ha": target_stems_per_ha,
            "note_ne": yield_note_ne,
            "note_en": yield_note_en,
        },
        "note_ne": note_ne,
        "note_en": note_en,
    }


# ─────────────────────────────────────────────────────────────────────────────
# The 14 rows
# ─────────────────────────────────────────────────────────────────────────────
PRESCRIPTION_ROWS: list[dict[str, Any]] = [
    dict(
        type_no=1,
        name_ne="१९ डिग्रीभन्दा कम भिरालो तराई र शिवालिक साल वन",
        name_en="Terai & Siwalik Sal forest, slope < 19°",
        species_groups=["SAL"],
        zone_triggers=["LOWLAND_SAL"],
        slope_band=1,
        origin=None,
        orientation="Production",
        sort_order=10,
        notes_ne="सम्भाव्य भू-क्षयलाई न्यूनीकरण गरी उत्पादनमुखी वन व्यवस्थापन।",
        notes_en="Production-oriented management, minimising potential soil loss.",
        branches={
            "adequate": _branch(
                method=SELECTION,
                system_ne="कटान चक्र सहितको छनौट प्रणाली",
                system_en="Selection system with felling cycle",
                felling_cycle_years=10,
                yield_basis="growing_stock_pct_ge40",
                steps=_steps((200, None, 2.0), (150, 200, 1.0), (None, 150, 0.5)),
                yield_note_ne="जम्मा मौज्दात (छाती व्यास ≥ ४० से.मि.) को प्रतिशतका आधारमा।",
                yield_note_en="Percentage of total growing stock (DBH >= 40 cm).",
                note_ne="विरुवा ५००० र लाथ्रा २००० प्रति हे. भन्दा बढी।",
                note_en="Seedlings > 5000/ha and saplings > 2000/ha.",
            ),
            "inadequate": _branch(
                method=SHELTERWOOD,
                system_ne="इन्डियन इरेगुलर सेल्टरवुड प्रणाली",
                system_en="Indian irregular shelterwood system",
                rotation_years=80,
                regeneration_period_years=10,
                mother_trees_per_ha=[15, 25],
                yield_basis="area_volume",
                yield_note_ne="क्षेत्रफल, आयतन र रुख संख्याको आधारमा।",
                yield_note_en="By area, volume and stem count.",
                note_ne="विरुवा ५००० र लाथ्रा २००० प्रति हे. भन्दा थोरै। माउ रुख १५–२५ प्रति हे. राख्ने।",
                note_en="Below the regeneration thresholds. Retain 15-25 mother trees/ha.",
            ),
        },
    ),
    dict(
        type_no=2,
        name_ne="शिवालिक साल वन: १९ देखि ३१ डिग्री भिरालो",
        name_en="Siwalik Sal forest, slope 19°-31°",
        species_groups=["SAL"],
        zone_triggers=["LOWLAND_SAL"],
        slope_band=2,
        origin=None,
        orientation="Conservation",
        sort_order=20,
        notes_ne="भू-क्षयका दृष्टिकोणले संवेदनशील; संरक्षणलाई प्राथमिकता दिई संरक्षणमुखी व्यवस्थापन।",
        notes_en="Erosion-sensitive; conservation-oriented management.",
        branches={
            "adequate": _branch(
                method=SELECTION,
                system_ne="कटान चक्रसहितको एकल रुख छनौट प्रणाली",
                system_en="Single-tree selection with felling cycle",
                felling_cycle_years=10,
                yield_basis="growing_stock_pct_ge40",
                steps=_steps((200, None, 1.0), (None, 200, 0.5)),
                yield_note_ne="क्षेत्रफल र आयतनको आधारमा।",
                yield_note_en="By area and volume.",
            ),
            "inadequate": _branch(
                method=SELECTION,
                system_ne="समूह छनौट प्रणाली",
                system_en="Group selection system",
                felling_cycle_years=10,
                regeneration_period_years=10,
                rotation_years=100,
                yield_basis="growing_stock_pct_ge40",
                steps=_steps((200, None, 1.0), (None, 200, 0.5)),
                yield_note_ne="क्षेत्रफल, रुख संख्या र आयतनको आधारमा।",
                yield_note_en="By area, stem count and volume.",
            ),
        },
    ),
    dict(
        type_no=3,
        name_ne="शिवालिक साल वन: ३१ डिग्रीभन्दा बढी भिरालो",
        name_en="Siwalik Sal forest, slope > 31°",
        species_groups=["SAL"],
        zone_triggers=["LOWLAND_SAL"],
        slope_band=3,
        origin=None,
        orientation="Protection",
        sort_order=30,
        notes_ne="संरक्षण (Protection)। भू-क्षयका दृष्टिकोणले संवेदनशील।",
        notes_en="Protection. Erosion-sensitive terrain.",
        branches={
            "default": _branch(
                method=AREA_COUPE,
                system_ne="संरक्षणमुखी व्यवस्थापन",
                system_en="Protection management",
                yield_basis="none",
                yield_note_ne="कुनै नियमित कटान होइन।",
                yield_note_en="No regular harvest.",
                note_ne="सम्भव भएसम्म ढलेका र सुकेका (सुखड खडा) रुख मात्र हटाउन सकिने।",
                note_en="Where possible, remove only fallen and dead-standing trees.",
            )
        },
    ),
    dict(
        type_no=4,
        name_ne="सिसौ / खयर वृक्षारोपण वन",
        name_en="Sissoo / Khair plantation forest",
        species_groups=["SISSOO_KHAIR"],
        zone_triggers=["LOWLAND_SAL"],
        slope_band=None,
        origin="plantation",
        orientation="Production",
        sort_order=40,
        notes_ne="काठ दाउरा उत्पादन।",
        notes_en="Timber and fuelwood production.",
        branches={
            "default": _branch(
                method=STEM_COUNT,
                system_ne="पुनरोत्पादनको लागि माउ रुख राखी गरिने प्रणाली (Seed tree method)",
                system_en="Seed tree method",
                rotation_years=35,
                regen_method_ne="प्राकृतिक वा कृत्रिम (वृक्षारोपण / बीउ छर्ने)",
                regen_method_en="Natural or artificial (planting / direct seeding)",
                yield_basis="stem_count",
                target_stems_per_ha=[100, 150],
                yield_note_ne="क्षेत्रफल र रुख संख्याको आधारमा। बाली चक्र ३०–४० वर्ष।",
                yield_note_en="By area and stem count. Rotation 30-40 years.",
                note_ne=(
                    "प्रति हे. २०० भन्दा कम रुख भए सिधै Seed Tree Method; "
                    "२०० भन्दा बढी भए एक चोटी थिनिङ्ग गरी १००–१५० कायम गरी दोस्रो कटानमा माउ रुख प्रणालीमा।"
                ),
                note_en=(
                    "< 200 stems/ha -> straight to seed-tree; > 200 -> thin once to 100-150/ha, "
                    "seed-tree at the second felling."
                ),
            )
        },
    ),
    dict(
        type_no=5,
        name_ne="नदी तटीय वन",
        name_en="Riverine forest",
        species_groups=["SISSOO_KHAIR", "RIVERINE_ASSOC"],
        zone_triggers=["LOWLAND_SAL"],
        slope_band=None,
        origin=None,
        orientation="Production",
        sort_order=50,
        notes_ne="काठ दाउरा उत्पादन र नदी तटीय क्षेत्रको संरक्षण।",
        notes_en="Timber/fuelwood production and riverbank protection.",
        branches={
            "default": _branch(
                method=AREA_COUPE,
                system_ne="सुधार कटान प्रणाली (Improvement felling)",
                system_en="Improvement felling",
                felling_cycle_years=10,
                regen_method_ne="प्राकृतिक साथै Assisted regeneration (वृक्षरोपण / बीउ छर्ने)",
                regen_method_en="Natural plus assisted regeneration",
                yield_basis="area_volume",
                yield_note_ne="क्षेत्रफल र आयतन (रुख संख्या) को आधारमा। कटान चक्र ५–१० वर्ष।",
                yield_note_en="By area and volume (stem count). Felling cycle 5-10 years.",
                note_ne="भू-क्षयको दृष्टिकोणले जोखिम बढाउने बूढा रुखहरु हटाउन सकिने।",
                note_en="Erosion-risk over-mature trees may be removed.",
            )
        },
    ),
    dict(
        type_no=6,
        name_ne="तराई तथा भित्री मधेशको हैसियत बिग्रेको वन",
        name_en="Degraded Terai / Inner-Madhesh forest",
        species_groups=["SAL"],
        zone_triggers=["LOWLAND_SAL"],
        slope_band=None,
        origin=None,
        orientation="Restoration",
        sort_order=60,
        notes_ne=(
            "झाडी / बुट्यान / मिचाहा प्रजातिले मुख्य प्रजातिको छत्र घनत्व २० प्रतिशत भन्दा कम भएको वन। "
            "वन पुनःस्थापना गरी उत्पादकत्व अभिवृद्धि गर्ने।"
        ),
        notes_en=(
            "Crown density of the main species below 20% due to shrub / invasive cover. "
            "Restore the forest and raise productivity."
        ),
        branches={
            "default": _branch(
                method=AREA_COUPE,
                system_ne="सुधार कटान (Improvement felling)",
                system_en="Improvement felling",
                regen_method_ne="प्राकृतिक साथै Assisted regeneration; झाडी सफाई र पत्लाउने",
                regen_method_en="Natural plus assisted regeneration; shrub clearing and thinning",
                yield_basis="none",
                yield_note_ne="अवस्थामा सुधार नआएसम्म कुनै आयतन कटान नगर्ने।",
                yield_note_en="No volume harvest until the condition recovers.",
                note_ne=(
                    "वन डढेलो लाग्न नदिने; आवश्यकता अनुसार घेरावारा; ढलापडा र सुखड खडा हटाउने। "
                    "अवस्थामा सुधार आएपछि उपयुक्त वन सम्वर्द्धन प्रणाली अपनाई पुनः वर्गीकरण।"
                ),
                note_en=(
                    "Fire protection; fencing as needed; remove fallen and dead-standing trees. "
                    "Re-classify to a suitable silvicultural type once the condition improves."
                ),
            )
        },
    ),
    dict(
        type_no=7,
        name_ne="पहाडी साल वन (Hill Sal Forest)",
        name_en="Hill Sal forest",
        species_groups=["SAL"],
        zone_triggers=["HILL"],
        slope_band=None,
        origin=None,
        orientation="Conservation",
        sort_order=70,
        notes_ne="भू-क्षयका दृष्टिकोणले संवेदनशील; संरक्षणमुखी व्यवस्थापन।",
        notes_en="Erosion-sensitive; conservation-oriented management.",
        branches={
            "adequate": _branch(
                method=SELECTION,
                system_ne="छनौट प्रणाली — Felling area based on felling cycle र समूह छनौट प्रणाली",
                system_en="Selection (felling-area-based + group selection)",
                felling_cycle_years=10,
                regen_method_ne="प्राकृतिक (बीउ वा मुना)",
                regen_method_en="Natural (seed or coppice)",
                yield_basis="growing_stock_pct_ge40",
                steps=_steps((200, None, 1.0), (150, 200, 0.5), (None, 150, 0.25)),
                yield_note_ne="क्षेत्रफल र आयतन अथवा रुख संख्याको आधारमा।",
                yield_note_en="By area and volume or stem count.",
            ),
            "inadequate": _branch(
                method=AREA_COUPE,
                system_ne="Coppice with standard वा irregular shelterwood system",
                system_en="Coppice-with-standard or irregular shelterwood system",
                regeneration_period_years=10,
                rotation_years=100,
                regen_method_ne="प्राकृतिक (बीउ वा मुना)",
                regen_method_en="Natural (seed or coppice)",
                yield_basis="area_volume",
                yield_note_ne="क्षेत्रफल, रुख संख्या र आयतनको आधारमा। बाली चक्र: CWS ४० वर्ष, ISW १०० वर्ष।",
                yield_note_en="By area, stem count and volume. Rotation: CWS 40 yr, ISW 100 yr.",
            ),
        },
    ),
    dict(
        type_no=8,
        name_ne="प्राकृतिक सल्ला वन",
        name_en="Natural pine forest",
        species_groups=["PINE_ROX", "PINE_WALL", "PINE_PATULA"],
        zone_triggers=[],
        slope_band=None,
        origin="natural",
        orientation="Production",
        sort_order=80,
        notes_ne="सम्भाव्य भू-क्षयलाई न्यूनीकरण गरी उत्पादनमुखी व्यवस्थापन। ४५ डिग्रीभन्दा बढी भिरालोमा संरक्षणमुखी।",
        notes_en="Production-oriented, minimising soil loss. Slope > 45° -> protection.",
        branches={
            "adequate": _branch(
                method=SELECTION,
                system_ne="कटान चक्र सहितको समूह छनौट प्रणाली",
                system_en="Group selection with felling cycle",
                felling_cycle_years=10,
                regen_method_ne="प्राकृतिक; असन्तोषजनक भए Enrichment plantation",
                regen_method_en="Natural; enrichment planting where regeneration is poor",
                yield_basis="growing_stock_pct_ge40",
                steps=_steps((200, None, 2.0), (150, 200, 1.0), (None, 150, 0.5)),
                yield_note_ne="क्षेत्रफल र आयतन अथवा रुख संख्याको आधारमा।",
                yield_note_en="By area and volume or stem count.",
            ),
            "inadequate": _branch(
                method=SHELTERWOOD,
                system_ne="Irregular shelterwood system",
                system_en="Irregular shelterwood system",
                regeneration_period_years=10,
                rotation_years=60,
                yield_basis="area_volume",
                yield_note_ne="क्षेत्रफल र रुख संख्याको आधारमा।",
                yield_note_en="By area and stem count.",
                note_ne="बाली चक्र: खोटे सल्ला ६० वर्ष, गोब्रे सल्लाको प्राकृतिक वन १०० वर्ष, पाटे सल्ला ३०–३५ वर्ष।",
                note_en="Rotation: khote pine 60 yr, natural gobre pine 100 yr, pate pine 30-35 yr.",
            ),
        },
    ),
    dict(
        type_no=9,
        name_ne="वृक्षारोपण सल्ला वन",
        name_en="Pine plantation forest",
        species_groups=["PINE_ROX", "PINE_WALL", "PINE_PATULA"],
        zone_triggers=[],
        slope_band=None,
        origin="plantation",
        orientation="Production",
        sort_order=90,
        notes_ne="सम्भाव्य भू-क्षयलाई न्यूनीकरण गरी उत्पादनमुखी व्यवस्थापन। ४५ डिग्रीभन्दा बढी भिरालोमा संरक्षणमुखी।",
        notes_en="Production-oriented, minimising soil loss. Slope > 45° -> protection.",
        branches={
            "default": _branch(
                method=STEM_COUNT,
                system_ne="कटान चक्र सहितको समूह छनौट वा Irregular shelterwood; तल्लोबाट पत्लाउने (Low thinning)",
                system_en="Group selection with cycle or ISW; low thinning",
                felling_cycle_years=5,
                regen_method_ne="प्राकृतिक; असन्तोषजनक भए वृक्षारोपण",
                regen_method_en="Natural; planting where regeneration is poor",
                yield_basis="stem_count",
                target_stems_per_ha=[150, 200],
                yield_note_ne=(
                    "खोटे सल्ला: ४५ वर्षको उमेरसम्म १५०–२०० रुख कायम; पाटे सल्ला: २५ वर्षसम्म। "
                    "खोटे तथा पाटे सल्ला पत्लाउने दिग्दर्शन, २०६४ अनुसार।"
                ),
                yield_note_en=(
                    "Khote pine: retain 150-200 stems/ha to age 45; pate pine to age 25. "
                    "Per the 2064 pine-thinning directive."
                ),
            )
        },
    ),
    dict(
        type_no=10,
        name_ne="सल्ला र चौडापातेको मिश्रित वन",
        name_en="Pine - broadleaf mixed forest",
        species_groups=["PINE_ROX", "PINE_WALL", "PINE_PATULA"],
        zone_triggers=[],
        slope_band=None,
        origin=None,
        orientation="Production",
        sort_order=100,
        notes_ne="भविष्यमा चाहिने वनको किसिम अनुसार वार्षिक वृद्धि दर कायम गर्ने। ४५ डिग्रीभन्दा बढी भिरालोमा संरक्षणमुखी।",
        notes_en="Maintain the increment rate toward the target forest type. Slope > 45° -> protection.",
        branches={
            "default": _branch(
                method=SELECTION,
                system_ne="Irregular shelterwood system / selection system with felling cycles",
                system_en="Irregular shelterwood / selection with felling cycles",
                felling_cycle_years=10,
                regeneration_period_years=10,
                rotation_years=60,
                yield_basis="area_volume",
                yield_note_ne="क्षेत्रफल र रुख संख्याको आधारमा।",
                yield_note_en="By area and stem count.",
                note_ne="बाली चक्र: खोटे सल्ला वृक्षारोपण ६० वर्ष, पाटे र अन्य सल्ला ३०–३५ वर्ष।",
                note_en="Rotation: khote pine plantation 60 yr, pate and other pine 30-35 yr.",
            )
        },
    ),
    dict(
        type_no=11,
        name_ne="पहाडी चौडापाते मिश्रित वन",
        name_en="Hill broadleaf mixed forest",
        species_groups=["HILL_BROADLEAF"],
        zone_triggers=["HILL"],
        slope_band=None,
        origin=None,
        orientation="Conservation",
        sort_order=110,
        notes_ne="भू-क्षयका दृष्टिकोणले संवेदनशील; संरक्षणमुखी व्यवस्थापन।",
        notes_en="Erosion-sensitive; conservation-oriented management.",
        branches={
            "default": _branch(
                method=AREA_COUPE,
                system_ne="रुख सहितको मुना प्रणाली (Coppice with standard System)",
                system_en="Coppice-with-standard system",
                felling_cycle_years=30,
                regeneration_period_years=10,
                regen_method_ne="प्राकृतिक (मुना र बीउ)",
                regen_method_en="Natural (coppice and seed)",
                yield_basis="area_volume",
                yield_note_ne="क्षेत्रफल र आयतनको आधारमा (रुख संख्या)। मुनाको बाली चक्र १०–३० वर्ष।",
                yield_note_en="By area and volume (stem count). Coppice rotation 10-30 years.",
                note_ne=(
                    "उप-प्रकार पहाडी चौडापाते झाडीदार (गुराँस प्रधान): "
                    "Coppice selection / reserve, कटान चक्र १० वर्ष।"
                ),
                note_en=(
                    "Sub-type hill broadleaf shrubland (rhododendron-dominant): "
                    "coppice selection / reserve, felling cycle 10 years."
                ),
            )
        },
    ),
    dict(
        type_no=12,
        name_ne="शितोष्ण चौडापाते मिश्रित वन",
        name_en="Temperate broadleaf mixed forest",
        species_groups=["TEMPERATE_BROADLEAF"],
        zone_triggers=["TEMPERATE"],
        slope_band=None,
        origin=None,
        orientation="Production",
        sort_order=120,
        notes_ne=(
            "अनुसूची-१ को मूल स्क्यानमा 'संरक्षणलाई प्राथमिकता' लेखिएको तर '(Production Oriented)' पनि "
            "उल्लेख भएकोले पहिले अस्पष्ट देखिएको थियो। समाधान भयो (योजना D7, 2026-09-15): मालिकले सम्बन्धित "
            "अधिकारीसँग सिधै सोधपुछ गर्दा यो प्रकार Production Oriented नै हो भनी पुष्टि भयो — यसको आफ्नै "
            "उत्पादन नियमन तालिका (मौज्दात >२०० घन.मी./हे. भए १%, <२०० भए ०.५%) र कोष्ठकको ट्यागसँग मिल्छ। "
            "अब अस्पष्ट होइन; भिरालोमा आधारित कुनै विशेष अपवाद छैन (band ४ को सामान्य नीति बाहेक, जुन सबै "
            "प्रकारमा लागू हुन्छ)।"
        ),
        notes_en=(
            "The source scan initially looked contradictory ('conservation priority' text next to a "
            "'(Production Oriented)' tag). Resolved (plan D7, 2026-09-15): the owner consulted the "
            "responsible official directly, who confirmed this type is Production Oriented -- matching "
            "its own yield table (>200 m3/ha growing stock -> 1%, <200 -> 0.5%) and the parenthetical tag. "
            "No longer ambiguous; carries no slope-band-3 exception (only the general band-4 policy, which "
            "applies to every type, still affects it) -- see AMBIGUOUS_ORIENTATION_TYPES in "
            "forest_type_classifier.py (now empty)."
        ),
        branches={
            "adequate": _branch(
                method=SELECTION,
                system_ne="Selection system — Felling area based on felling cycle र Group selection",
                system_en="Selection (felling-area-based + group selection)",
                felling_cycle_years=10,
                regen_method_ne="प्राकृतिक (बीउ)",
                regen_method_en="Natural (seed)",
                yield_basis="growing_stock_pct_ge40",
                steps=_steps((200, None, 1.0), (None, 200, 0.5)),
                yield_note_ne="क्षेत्रफल र आयतनको आधारमा (रुख संख्या)।",
                yield_note_en="By area and volume (stem count).",
            ),
            "inadequate": _branch(
                method=AREA_COUPE,
                system_ne="Coppice with standard system",
                system_en="Coppice-with-standard system",
                felling_cycle_years=10,
                regen_method_ne="प्राकृतिक (बीउ र मुना)",
                regen_method_en="Natural (seed and coppice)",
                yield_basis="area_volume",
                yield_note_ne="झाडीदार भाग: क्षेत्रफलको आधारमा बायोमास। कटान चक्र ५–१० वर्ष।",
                yield_note_en="Shrubland part: biomass by area. Felling cycle 5-10 years.",
            ),
        },
    ),
    dict(
        type_no=13,
        name_ne="शितोष्ण कोणधारी वन (Temperate Conifer Forest)",
        name_en="Temperate conifer forest",
        species_groups=["TEMPERATE_CONIFER"],
        zone_triggers=["HIGH_MOUNTAIN"],
        slope_band=None,
        origin=None,
        orientation="Production",
        sort_order=130,
        notes_ne="भू-क्षयलाई न्यूनीकरण गरी काठ उत्पादन। ४५ डिग्रीभन्दा माथिको भिरालोमा संरक्षणमुखी।",
        notes_en="Timber production, minimising soil loss. Slope > 45° -> protection.",
        branches={
            "default": _branch(
                method=SHELTERWOOD,
                system_ne="Uniform shelterwood system / selection system (Felling area based on felling cycle वा group selection)",
                system_en="Uniform shelterwood / selection (felling-area-based or group selection)",
                regeneration_period_years=20,
                rotation_years=150,
                regen_method_ne="प्राकृतिक (बीउ)",
                regen_method_en="Natural (seed)",
                yield_basis="growing_stock_pct_ge40",
                steps=_steps((200, None, 2.0), (150, 200, 1.0), (None, 150, 0.5)),
                yield_note_ne="क्षेत्रफल र आयतनको आधारमा रुख संख्या निर्धारण। बाली चक्र १२०–१५० वर्ष; पुनरोत्पादन अवधि १५–२० वर्ष।",
                yield_note_en="Stem count set by area and volume. Rotation 120-150 yr; regeneration period 15-20 yr.",
            )
        },
    ),
    dict(
        type_no=14,
        name_ne="सल्ला वृक्षारोपण वनलाई चौडापाते वनमा रूपान्तरित वन",
        name_en="Pine plantation converted to broadleaf forest",
        species_groups=["PINE_ROX", "PINE_WALL", "PINE_PATULA"],
        zone_triggers=[],
        slope_band=None,
        origin="plantation",
        orientation="Multi-use",
        sort_order=140,
        notes_ne="बहुउपयोगी वन व्यवस्थापन। कोणधारी घटाउँदै चौडापाते बढाउने। केवल रूपान्तरणका लागि छानिएको वनमा लागू।",
        notes_en="Multi-use management: reduce conifer, increase broadleaf. Only for a forest flagged for conversion.",
        branches={
            "default": _branch(
                method=STEM_COUNT,
                system_ne="प्रतिस्थापन — चौडापाते प्रजाति स्थापना",
                system_en="Replacement - establish broadleaf species",
                regeneration_period_years=10,
                regen_method_ne="प्राकृतिक (मुना र बीउ) र कृत्रिम दुबै",
                regen_method_en="Both natural (coppice and seed) and artificial",
                yield_basis="stem_count",
                target_stems_per_ha=[150, 200],
                yield_note_ne=(
                    "न्यूनतम ७५% चौडापाते र २५% सल्लाको मिश्रित वन कायम गर्ने। "
                    "सल्ला प्रति हे. २०० भन्दा बढी भए ५–१० वर्षमा १५०–२०० मा, त्यसपछि ५–१० वर्षमा प्रति हे. ५० मा झार्ने।"
                ),
                yield_note_en=(
                    "Maintain at least 75% broadleaf / 25% pine. If pine > 200/ha, "
                    "reduce to 150-200/ha over 5-10 yr, then to 50/ha over the next 5-10 yr."
                ),
            )
        },
    ),
]


def seed(session: Session) -> int:
    """Upsert the 14 rows (keyed on ``type_no``). Returns the row count.
    ``flush`` only — the caller (migration or a script) owns the commit."""
    from app.models.sfm_prescription import SfmForestTypePrescription

    for row in PRESCRIPTION_ROWS:
        session.merge(SfmForestTypePrescription(**row))
    session.flush()
    logger.info("seeded %d sfm_forest_type_prescriptions rows", len(PRESCRIPTION_ROWS))
    return len(PRESCRIPTION_ROWS)


if __name__ == "__main__":  # pragma: no cover - manual entrypoint
    logging.basicConfig(level=logging.INFO)
    from app.core.database import SessionLocal

    s = SessionLocal()
    try:
        n = seed(s)
        s.commit()
        print(f"seeded {n} rows")
    finally:
        s.close()
