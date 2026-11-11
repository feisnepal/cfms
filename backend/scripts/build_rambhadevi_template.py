#!/usr/bin/env python
"""Build the 'Rambhadevi SFM Renew' operational-plan template from the extracted 'Rambhadevi CF OP.docx'.

    venv/Scripts/python.exe -X utf8 backend/scripts/build_rambhadevi_template.py [--dry-run] [--report]

Reads  testData/SFM_data/rambhadevi_extract/body.json  (made by rambhadevi_extract.py) and writes the template into
``op_templates`` as a DRAFT of plan kind ``sustainable_fmp_revision`` (re-runnable: an existing template with the same
name is updated in place, with a version snapshot of what it held).

What is copied and what is not (owner decisions, RAMBHADEVI_SFM_RENEW_TEMPLATE_PLAN.md §6):
  * every generic sentence is copied word for word;
  * forest-specific values (names, address, area, dates, counts, species) become {{placeholders}};
  * numbering is corrected, not copied: headings carry no typed numbers (auto-numbering numbers them), captions and
    their cross-references are renumbered 1..N in document order, annex letters are made consecutive;
  * digits are written in Devanagari throughout.
"""
import argparse
import json
import re
import sys
import unicodedata
import uuid
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "backend"))

BODY = json.loads((REPO / "testData/SFM_data/rambhadevi_extract/body.json").read_text(encoding="utf-8"))
TEMPLATE_NAME = "Rambhadevi SFM Renew"
NS = uuid.UUID("5a6d8b1e-0d4f-4c1a-9a53-2f0c7a6b9e11")

DEV = str.maketrans("0123456789", "०१२३४५६७८९")
_TOKEN = re.compile(r"(\{\{[^}]+\}\})")


# ── text helpers ─────────────────────────────────────────────────────────────
def dev(n) -> str:
    return str(n).translate(DEV)


def digits(text: str) -> str:
    """ASCII digits -> Devanagari, except inside {{tokens}} and next to letters (C1S8, 5D, FY...)."""
    out = []
    for part in _TOKEN.split(text):
        if part.startswith("{{"):
            out.append(part)
        else:
            out.append(re.sub(r"(?<![A-Za-z0-9_])(\d+)(?![A-Za-z_])", lambda m: m.group(1).translate(DEV), part))
    return "".join(out)


# generic, forest-name/value substitutions applied to every paragraph (order matters)
SUBS = [
    (r"रम्भादेवी|रम्भादेवि|रम्िादेवी", "{{forest_name}}"),
    (r"देवदह-१०,\s*दलदले,\s*रूपन्देही", "{{forest_municipality}}-{{forest_ward}}, {{forest_district}}"),
    (r"तिलोत्तमा\s*सव\s*डिभिजन\s*वन\s*कार्यालय(?:,?\s*रूपन्देही)?", "{{sub_division}} सव डिभिजन वन कार्यालय"),
    (r"डिभिजन\s*वन\s*कार्यालय,?\s*रूपन्देही", "डिभिजन वन कार्यालय {{division}}"),
    (r"रूपन्देही\s*जिल्ला|रुपन्देही\s*जिल्ला", "{{forest_district}} जिल्ला"),
    (r"देवदह\s*(?:नगरपालिका|न\.पा\.)", "{{forest_municipality}} {{forest_municipality_type}}"),
    (r"वडा\s*(नं\.?|नम्बर)\s*(?:१०|10)\b", r"वडा \1 {{forest_ward}}"),
    (r"पुर्वः\s*आरे\s*खोला.*?त्रिशुली\s*सा\.वको\s*सिमाना\s*यति",
     "पुर्वः {{cf_boundary_east}}, पश्चिमः {{cf_boundary_west}}, उत्तरः {{cf_boundary_north}} र दक्षिणः {{cf_boundary_south}} यति"),
    (r"१०\s*\(दश\)\s*\(आ\.व\.\s*[^)]*\)\s*अवधिका",
     "{{plan_duration_years}} बर्ष (आ.व. {{op_start_fy}} देखि आ.व. {{op_end_fy}}) अवधिका"),
    (r"२६४\.५६", "{{total_area_hectares}}"),
    (r"पञ्चासे\s*बहुसेवा\s*प्रा\.ली,?\s*बर्दिया", "{{technical_assistance_org}}"),
    (r"रातमाटे\s*डाँडा\s*भन्ने\s*स्थानमा", "उपयुक्त स्थानमा"),
    (r"C1S8", "{{sfm_regeneration_felling_unit}}"),
    (r"C1S7", "{{sfm_preparatory_felling_unit}}"),
    (r"२०६९/१२/२९", "{{cf_handover_date}}"),
    (r"२०७८/०३/३०", "{{cf_first_renewal_date}}"),
]

# paragraph -> full replacement (block index in body.json). Tokens only where a value is forest-specific.
FULL = {
    # ── summary (कार्ययोजनाको साराशं) ──
    68: "सब-डिभिजन वन कार्यालयः {{sub_division}}",
    69: "समूहको नामः {{forest_name}} सामुदायिक वन उपभोक्ता समूह",
    70: "ठेगानाः {{forest_municipality}}-{{forest_ward}}, {{forest_district}}",
    71: "समूहको कोडः {{cf_code}}",
    72: "जम्मा घरधुरी संख्याः {{hh_total_households}}",
    73: "कार्ययोजना स्वीकृत भएको आ.ब.: {{op_start_fy}}",
    74: "जनसंख्याः {{hh_total_population}} (महिला - {{hh_total_female}}, पुरुष - {{hh_total_male}})",
    75: "समिति सदस्य संख्याः महिला {{uc_female_members}}, पुरुष {{uc_male_members}}, जम्मा {{uc_total_members}}",
    77: "सामुदायिक वनको नाम : {{forest_name}} सामुदायिक वन",
    78: "कार्ययोजना हस्तान्तरण मिति : {{cf_handover_date}}",
    79: "पहिलो पटक वन कार्ययोजना परिमार्जन : {{cf_first_renewal_date}}",
    80: "सा.वको कुल क्षेत्रफल : {{total_area_hectares}} हेक्टर",
    81: "संरक्षित क्षेत्रफल : {{ti_protection_working_circle_area_ha}} हेक्टर",
    82: "कम्पार्टमेन्ट र सव कम्पार्टमेन्टको क्षेत्रफल : {{ti_production_area_ha}} हेक्टर",
    83: "वनको किसिमः {{forest_type}}",
    84: "वनको औषत उमेर/अवस्थाः {{forest_avg_age}} बर्ष",
    85: "मुख्य प्रजातीः {{fi_main_species_names}}",
    86: "मुख्य गैह्रकाष्ठ वन पैदावारः {{main_non_timber_fp}}",
    87: "औषत छत्र घनत्वः {{avg_crown_density_pct}}%",
    88: "मोहडाः {{aspect_dominant_names}}",
    89: "भिरालोपनाः {{slope_range_deg}}",
    90: "माटोः {{soil_texture_names}}",
    91: "भू-क्षयको अवस्थाः {{erosion_status_word}}",
    93: "कम्पार्टमेन्ट संख्याः {{unit_parent_count}} वटा\tसब-कम्पार्टमेन्ट संख्याः {{unit_count}} वटा",
    94: "बाली चक्रः {{rotation_years}} बर्ष\tवन सम्वर्द्धन प्रणालीः {{silviculture_system}}",
    95: "पुनरुत्पादन अवाधिः {{regeneration_period_years}} बर्ष\tकार्य योजना अवधिः {{plan_duration_years}} बर्ष",
    96: "पुनरुत्पादन कटान गर्ने सब-कम्पार्टमेन्टः {{sfm_regeneration_felling_unit}}\tपुनरुत्पादन तयारी कटान: {{sfm_preparatory_felling_unit}}",
    97: "प्रत्येक बर्ष कटान गर्ने रुख संख्याः {{sm_felling_annual_trees}} गोटा\tमाउ रुख संख्याः {{sm_mother_trees_per_ha}} वटा प्रति हेक्टर",
    98: "उपलब्ध भएमा माउ रुखको औषत दुरीः {{mother_tree_spacing_m}} मिटर",
    99: "अनुमानित बार्षिक उत्पादन परिमाण (पुनरुत्पादन कटानबाट मात्र): {{sfm_annual_yield_timber_cft}} घन फिट काठ र {{sfm_annual_yield_firewood_chatta}} चट्टा दाउरा",
    # ── ch 2.1 historical background: generic wording + the local story (editable) + history from data ──
    297: ("यो वन सामुदायिक वनको रुपमा हस्तान्तरण हुनु अघि राष्ट्रिय वनको रुपमा रहेको थियो । बढ्दो जनसंख्या तथा वन पैदावारको मागसँगै वनमा मानिसको "
          "चाप बढ्दै जाँदा वनको अवस्थामा गिरावट आउन थालेपछि स्थानीय उपभोक्ताहरुको पहलमा संरक्षण समिति बनाई वनको संरक्षण गर्न थालियो ।\n"
          "{{cf_history_note}}"),
    298: ("वन उपभोक्ता समूह गठन भई वनको संरक्षणका लागि संगठित प्रयास भएसँगै स्थानीय उपभोक्ताहरुमा चेतनाको विकास भई सामुदायिक वन प्रति "
          "सकारात्मक सोच बसेको पाइन्छ । वन क्षेत्रको वैज्ञानिक र दिगो विकासका लागि वन व्यवस्थापनको कार्ययोजना र विधान तयार गरी "
          "{{cf_handover_date}} मा सामुदायिक वनको रुपमा हस्तान्तरण भएको हो ।"),
    299: ("सामुदायिक वनको रुपमा हस्तान्तरण भएपछि स्विकृत कार्ययोजना बमोजिम अतिक्रमण, चोरी निकासी, अबैध कटानी नियन्त्रण गर्दै वनको संरक्षण, "
          "वन्य जन्तु र चराचुरुङ्गीको वासस्थानको उचित संरक्षण गर्दै आएको छ । यस उपभोक्ता समूहलाई वन पैदावारको आवश्यकता पुरा गरि बाँकी रहेका "
          "काठ दाउरा बाहिर बिक्रि गरि आएको आम्दानीबाट वनको संरक्षण, संबर्धन गर्दै यसैको माध्यमबाट समूहमा रहेको न्यून आय आर्जन भएका "
          "व्यक्तिहरुको जीवनस्तर उकास्नुका साथै विभिन्न सामुदायिक विकास निर्माणका कार्यहरु समेत गर्दै आएको छ । साथै स्थानिय जनताको वन "
          "पैदावरको आवश्यकता परिपूर्ति गर्दै वन वातावरण तथा पारिस्तिथिकिय प्रणाली (Ecosystem) लाई सन्तुलन राख्न तथा सामुदायिक वनको "
          "व्यवस्थापन गर्न यस क्षेत्रका स्थानीय संगठित उपभोक्ताहरुको सहभागितामा बिगतका राम्रा सिकाइहरुलाई अनुसरण गरी उपभोक्ताहरुको चाहना "
          "अनुसार वन सम्वद्धर्न प्रणालीमा आधारित वन व्यवस्थापन लक्ष्य अनुरुप यो वन व्यवस्थापन कार्ययोजना {{op_preparation_year}} तयार पारिएको छ । "
          "वन सुधारको साथै वन पैदावारको पनि निरन्तर आपूर्ति हुने कुरोको चेतनाको विकास आम उपभोक्ताहरुमा भएकोले यस पद्धतिमा आधारीत वन "
          "व्यवस्थापनलाई सहयोग पुग्ने गरी कार्ययोजना तयार भएको छ । यो कार्ययोजना स्विकृत भएपछि यसै अनुसार सामुदायिक वनमा वन व्यवस्थापन "
          "कार्यक्रम गरिने छ । यस सामुदायिक वनको दीगो व्यवस्थापन गर्न वन सम्वद्धर्न प्रणालीमा आधारित वन व्यवस्थापन मापदण्ड २०७९ वमोजिम "
          "{{plan_duration_years}} वर्षे वन व्यवस्थापन कार्ययोजना {{op_preparation_year}} तयार गरी परिमार्जन गरीएको हो ।\n"
          "ऐतिहासिक भू-उपयोग तथा वन आवरणको परिवर्तन (तथ्याङ्कमा आधारित): सन् १९८४ को भू-उपयोग अनुसार यस क्षेत्रको प्रमुख भू-उपयोग "
          "{{landcover_1984_dominant}} रहेको थियो भने सन् २००० को वन आवरण (Hansen) अनुसार प्रमुख वर्ग {{hansen2000_dominant}} रहेको थियो । "
          "सन् २००१ देखि हालसम्म यस क्षेत्रमा {{forest_loss_hectares}} हेक्टर वन आवरण क्षति तथा {{forest_gain_hectares}} हेक्टर वन आवरण वृद्धि भएको "
          "तथ्याङ्कले देखाउँछ ।\n{{map:landcover_1984}}\n{{section:forest_loss:full}}"),
    # ── ch 2.4 / 2.7 ──
    310: ("यस सामुदायिक वनको जम्मा क्षेत्रफल {{total_area_hectares}} हेक्टर रहेको छ । ३० डिग्री भन्दा माथी भिरालो वन क्षेत्र, उपभोक्ता समुहको व्यवस्थापकिय क्षमता, "
          "वस्ती देखीको वन क्षेत्र लगायतका आधारमा यस सामुदायिक वनको आसपासको क्षेत्रलाई सघन वन व्यवस्थापनको Fringe Area मानी वन सम्वर्द्धन प्राणाली अन्तर्गत "
          "हुर्काउने कार्य यस योजना अवधिमा संचालन गर्ने र उक्त क्षेत्रबाट ढलपडा मात्र संकलन गर्ने गरी {{ti_protection_working_circle_area_ha}} हेक्टर क्षेत्रफललाई "
          "संरक्षित क्षेत्रको रुपमा छुट्याइएको छ । बाँकी {{ti_production_area_ha}} हेक्टर क्षेत्रफललाई सघन वन व्यवस्थापन गरी वन सम्बर्द्धनका पनुरुत्पादन कटान, "
          "पुनरुत्पादन तयारी कटान, थिनिङ्ग तथा सुधार कटान, पुनरुत्पादन अभिवृद्धि लगायतका कार्य संचालन गर्ने गरी {{unit_parent_count}} वटा कम्पार्टमेन्टका रुपमा "
          "विभाजन गरीएको छ।"),
    331: ("यस सामुदायिक वन {{watershed}} तथा {{major_river_basin}} अन्तर्गत पर्दछ । वनको भौगोलिक अवस्थिति {{physiography_zone}} क्षेत्रमा पर्दछ । "
          "{{drainage_summary}}\n{{thememap:forest__drainage_vectors}}\n{{section:land_cover:full}}"),
    333: "• हस्तान्तरण मिति : {{cf_handover_date}}",
    334: "• प्रथम नविरकण मिति : {{cf_first_renewal_date}}",
    335: "• आवद्ध घरधुरी संख्या : {{hh_total_households}}",
    336: "• लभाम्भित जनसंख्या : महिला {{hh_total_female}} पुरुष {{hh_total_male}} गरी जम्मा {{hh_total_population}}",
    337: "• कार्यसमिति : महिला {{uc_female_members}}, पुरुष {{uc_male_members}} गरी जम्मा {{uc_total_members}}",
    # ── ch 3 / 4 ──
    381: ("यस सामुदायिक वनका उपभोक्ताहरुको आवश्यकता पूर्ति गर्न बार्षिक करिव {{hh_timber_demand_cft}} क्युविक फिट काठ र {{hh_firewood_demand_bhari}} भारी दाउरा "
          "आवश्यक पर्ने देखिन्छ । वन पैदावार सम्वन्धी माग र आपूर्तिको अवस्थालाई तालिका ६ मा प्रस्तुत गरिएको छ ।\n{{section:demand_supply_narration:full}}"),
    395: ("यस सामुदायिक वनको औषत विरुवा, लाथ्रा, पोल र रुखको संख्या क्रमश {{fi_regeneration_per_ha}}, {{fi_sapling_per_ha}}, {{fi_pole_per_ha}} र "
          "{{fi_tree_per_ha}} रहेको छ । सामुदायिक वन स्रोत सर्वेक्षण मार्गदर्शन (परिमार्जित) २०६१ अनुसार समग्र वनको औषत मौज्दातको अवस्था "
          "{{fi_growing_stock_m3_per_ha}} घ.मी प्रति हेक्टर रहेको छ ।\n{{section:field_inventory_narration:full}}"),
    405: "{{section:ti_species_composition_narration:full}}",
    434: "{{section:ti_dbh_perha_narration:full}}",
    416: "{{section:ti_species_stock_narration:full}}",
    426: "{{section:ti_species_dbh_narration:full}}",
    427: ("नोट : वन स्रोत सर्वेक्षणबाट प्राप्त जानकारी विश्लेषणका आधारमा रुख नक्शाङ्कन गरिएको सब कम्पार्टमेन्ट {{sfm_regeneration_felling_unit}} मा "
          "{{fi_main_species_names}} प्रजातिको बाहुल्य रहेको तथा अन्य सब कम्पार्टमेन्टमा भन्दा बुढा रुखहरु रहेको देखिएकोले सवैभन्दा बुढा रुखहरुको "
          "बाहुल्य रहेको सब कम्पार्टमेन्ट {{sfm_regeneration_felling_unit}} वाट व्यवस्थापनको कार्य संचालन गर्नु उपयुक्त देखिन्छ ।"),
    436: ("यस योजना अवधिमा सब-कम्पार्टमेन्ट {{sfm_regeneration_felling_unit}} मा पुनरुत्वपादन कटान गरिने छ । यस सब-कम्पार्टमेन्टका सम्पूर्ण रुखहरुको मापन "
          "गरिनुका साथै जिपिएस लोकेशन समेत लिइएको छ । यी रुखहरु मध्ये कटान गरिने र माउ रुखको रुपमा राखिने रुखहरु समेत पहिचान गरिएको छ । यस "
          "सब-कम्पार्टमेन्टमा जम्मा {{sm_tree_total}} वटा रुखहरु छन् जस मध्ये {{sm_mother_tree_total}} वटा रुखहरुलाई माउ रुखको रुपमा पहिचान गरिएको छ भने, "
          "३० डिग्री भन्दा माथी भिरालोपन भएको क्षेत्र तथा खोलाको दुवै किनारा देखि ५-५ मिटर क्षेत्र भित्रका {{sm_protected_tree_total}} वटा रूखहरू संरक्षित "
          "रूखहरू छन् भने बाँकी {{sm_felling_tree_total}} वटा रुखहरु योजना अवधि ({{plan_duration_years}} बर्ष) मा कटान गरिनेछ । पुनरुत्पादन कटान गरिने "
          "सव कम्पार्टमेन्टको जम्मा रुख, माउ रुख र कटान गरीने रुखहरुको प्रतिहेक्टर मौज्दातको अवस्था तलको तालिकामा प्रस्तुत गरिएको छ ।"),
    # ── ch 7 / 8 / 10 / 13 ──
    614: ("यस सामुदायिक वनमा पाइने काठ बाहेकका अन्य वन पैदावारहरुलाई सामान्यतः गैह्र काष्ठ वन पैदावारको रुपमा परिभाषित गरिएको छ । यी वन पैदावारहरु "
          "पर्यावरणीय, आर्थिक, सामाजिक, भौगोलिक आदिको आधारमा उत्तिकै महत्वपूर्ण र आवश्यक भएकोले यस वन क्षेत्रमा पाईने र भौगोलिक हिसावले विकास गर्न "
          "सकिने गैह्र काष्ठ वन पैदावारको दिगो व्यवस्थापनमा समूहले जोड दिनेछ । यस सामुदायिक वनमा पाइने मुख्य गैह्रकाष्ठ वन पैदावार {{main_non_timber_fp}} "
          "रहेका छन् ।"),
    628: ("यस सामुदायिक वनको वन सम्वर्द्धन प्रणालिमा आधारित वन ब्यवस्थापन गर्न तयार गरिएको कार्ययोजनाको वित्तिय बिश्लेषण गर्दा {{cba_verdict}} । "
          "{{cba_discount_rate}} प्रतिशत दरमा खुद वर्तमान मूल्य (NPV) रु. {{cba_base_npv}} तथा लाभ-लागत अनुपात {{cba_base_bc_ratio}} छ । "
          "वित्तिय बिश्लेषणको संक्षेप तालिका २८ मा प्रस्तुत गरिएको छ भने बिस्तृत बिवरण अनुसूचि ५ मा प्रस्तुत गरिएको छ ।"),
    672: ("भौगोलिक हिसावले {{physiography_zone}} क्षेत्रमा पर्ने यस सामुदायिक वन जैविक विविधतायुक्त रहेको छ । यस वनमा पाइने मुख्य वनस्पति र तिनको "
          "वैज्ञानिक नाम तालिका २९ तथा वन्यजन्तु र तिनको वैज्ञानिक नाम तालिका ३० मा प्रस्तुत गरिएको छ ।"),
    777: ("क) कार्ययोजनाको अवधि : यस कार्ययोजनाको अवधी {{plan_duration_years}} बर्ष रहने छ । यो कार्ययोजना स्वीकृती भएको मितिदेखी लागु भई "
          "{{op_end_fy}} को आषाढ मसान्तसम्म लागु हुनेछ ।"),
}

# regex replacements inside a paragraph that is otherwise copied word for word: block -> [(pattern, replacement)]
REPL = {
    389: [
        (r"एक वटा कम्पार्टमेन्ट C1 मा विभाजन गरीएको छ ।\s*C1 कम्पार्टमेनटलाई ८ सब-कम्पार्टमेन्टमा बिभाजन ब्यवस्था राखीएको छ ।\s*"
         r"मुख्य प्रजाती सालको वनको रुपमा रहेको C1 वनको बाली चक्र ८० बर्ष तथा पुनरुत्पादन अवधि १० को कायम गरिएको छ ।",
         "कम्पार्टमेन्टमा विभाजन गरीएको छ । कम्पार्टमेन्टलाई {{unit_count}} सब-कम्पार्टमेन्टमा बिभाजन ब्यवस्था राखीएको छ । मुख्य प्रजाती "
         "{{fi_main_species_names}} को वनको रुपमा रहेको वनको बाली चक्र {{rotation_years}} बर्ष तथा पुनरुत्पादन अवधि {{regeneration_period_years}} बर्षको कायम गरिएको छ ।"),
        (r"जम्मा ४१ वटा स्याम्पल प्लट", "जम्मा {{fi_total_plots}} वटा स्याम्पल प्लट"),
    ],
    478: [
        (r"भावर क्षेत्रमा", "{{physiography_zone}} क्षेत्रमा"),
        (r"साल प्राजितको बाहुल्यता", "{{fi_main_species_names}} प्रजातिको बाहुल्यता"),
        (r"यस वनलाई साल प्रजातिको बाहुल्यता रहेको वन भएकोले", "यस वनलाई {{fi_main_species_names}} प्रजातिको बाहुल्यता रहेको वन भएकोले"),
        (r"चाहना गरिएका साल तथा अस्ना प्रजातिका", "चाहना गरिएका {{fi_main_species_names}} प्रजातिका"),
        (r"इरेगुलर छत्र प्रणाली \(Irregular Shelterwood System\)", "{{silviculture_system}}"),
    ],
    480: [
        (r"ह८० वर्ष समय", "{{rotation_years}} वर्ष समय"),
        (r"८० वर्ष समय", "{{rotation_years}} वर्ष समय"),
        (r"\(Rotation Period\) ८० वर्ष", "(Rotation Period) {{rotation_years}} वर्ष"),
        (r"\(Regeneration Period\) १० वर्ष", "(Regeneration Period) {{regeneration_period_years}} वर्ष"),
    ],
    482: [
        (r"इरेगुलर छत्र प्रणाली तथा वालीचक्र ८० बर्षको", "{{silviculture_system}} तथा वालीचक्र {{rotation_years}} बर्षको"),
        (r"१ कम्पार्टमेन्ट र बाँकी", "{{unit_parent_count}} कम्पार्टमेन्ट र बाँकी"),
        (r"कम्पार्टमेन्ट १ लाई वन सम्बर्द्धन प्रणालीमा आधारित वन व्यवस्थापन गर्न ८ वटा सव कम्पार्टमेन्टमा",
         "कम्पार्टमेन्टलाई वन सम्बर्द्धन प्रणालीमा आधारित वन व्यवस्थापन गर्न {{unit_count}} वटा सव कम्पार्टमेन्टमा"),
    ],
    520: [
        (r"जम्मा १ वटा कम्पार्टमेन्टका ६ वटा सब-कम्पार्टमेन्टमा", "जम्मा {{ya_thinning_unit_count}} वटा सब-कम्पार्टमेन्टमा"),
        (r"११०\.०४ हेक्टर", "{{ya_thinning_area_ha}} हेक्टर"),
        (r"अनुसूचि १ \(च\)", "अनुसूचि १ (ङ)"),   # source error: the activity map is annex 1(ङ), (च) is the stem map
    ],
    522: [
        (r"८० बर्ष बालीचक्र १० बर्ष पुनरुत्पादन अवधिको आधारमा हरेक कम्पार्टमेन्टमा आठ-आठ वटा",
         "{{rotation_years}} बर्ष बालीचक्र {{regeneration_period_years}} बर्ष पुनरुत्पादन अवधिको आधारमा हरेक कम्पार्टमेन्टमा {{unit_count}} वटा"),
    ],
    379: [(r"९ वटाका दरले ११७० वटा", "९ वटाका दरले {{demand_poles_count}} वटा")],
    490: [(r"अनुसुची १ \(ट\)", "अनुसुची १ (ठ)")],            # annex letters are made consecutive: the fire-line map is (ठ)
    623: [(r"अनुसूचि ६", "अनुसूचि ५")],                        # the financial analysis is annex 5 (the source says 6)
    440: [(r"१७ प्रजातिका", "{{sm_species_count}} प्रजातिका"), (r"साल मुख्य प्रजाति", "{{sm_top_species}} मुख्य प्रजाति")],
    444: [(r"साल मुख्य प्रजातिका", "{{sm_top_species}} मुख्य प्रजातिका")],
}

# figure / map placeholders at the picture paragraphs of the source (body.json block -> token lines)
IMG = {
    388: None,                                    # heading paragraph that carries the nested-plot picture (placed after 389)
    399: "{{chart:fi_unit_regen_per_ha_bar}}\n{{chart:fi_unit_sapling_per_ha_bar}}",
    412: "{{chart:fi_species_pole_count_bar}}",
    414: "{{chart:fi_species_pole_volume_bar}}",
    423: "{{chart:fi_species_tree_count_bar}}",
    425: "{{chart:fi_species_tree_volume_bar}}",
    430: "{{chart:dbh_class_count_bar}}",
    432: "{{chart:dbh_class_bar}}",
}
AFTER = {389: "{{asset:sample_plot_layout}}"}

# annex maps (annex heading block -> token); the (ट) fire-line page is empty in the source
ANNEX_MAP = {
    791: "{{map:boundary_satellite}}", 793: "{{map:boundary}}\n{{map:fieldbook}}\n{{thememap:forest__drainage_vectors}}\n{{opsmap:feature__fire_lines}}",
    795: "{{map:sub_compartment}}", 797: "{{map:sampling_plot}}", 799: "{{opsmap:unit__silviculture_year}}",
    801: "{{thememap:unit__stems_all}}", 803: "{{thememap:unit__stems_felling}}", 805: "{{thememap:unit__stems_mother}}",
    807: "{{map:aspect}}", 809: "{{map:dem}}", 811: "{{map:slope}}", 813: "{{opsmap:feature__fire_lines}}",
}
ANNEX_LETTERS = ["क", "ख", "ग", "घ", "ङ", "च", "छ", "ज", "झ", "ञ", "ट", "ठ"]

# tables: docx table index -> token lines (None -> a static table copied from the source)
TABLE_TOKENS = {
    1: "{{fi_unit_per_ha_summary_table}}", 2: "{{fi_forest_state_table}}", 3: "{{cba_cash_flow_table}}\n{{cba_summary_table}}",
    4: "{{uc_members}}", 6: "{{block_area_detail_merged}}", 7: "{{fi_forest_state_table}}", 8: "{{hh_caste_prosperity_table}}",
    10: "{{table:demand_supply}}", 11: "{{fi_unit_per_ha_summary_table}}",
    12: "{{fi_unit_species_regen_per_ha_table}}", 13: "{{fi_species_regen_per_ha_table}}",
    14: "{{fi_unit_species_pole_per_ha_table}}", 15: "{{fi_species_pole_per_ha_table}}",
    16: "{{fi_unit_species_tree_per_ha_table}}", 17: "{{fi_species_tree_per_ha_table}}",
    18: "{{sm_mother_felling_summary}}", 19: "{{sm_felling_tree_by_species}}", 20: "{{sm_mother_tree_by_species}}",
    21: "{{ya_felling_by_year_table}}", 23: "{{fire_line_plan_table}}", 26: "{{ya_silviculture_schedule_table}}",
    31: "{{ya_annual_budget_table}}", 32: "{{cba_cash_flow_table}}\n{{cba_summary_table}}",
    33: "{{table:vegetation_species}}", 34: "{{table:animal_species}}",
    37: "{{fieldbook_outer_table}}", 38: "{{fieldbook_internal_table}}", 39: "{{plot_utm_coordinate_table}}",
    40: "{{sm_felling_tree_list}}", 41: "{{sm_mother_tree_list}}", 42: "{{sm_protected_tree_list}}",
    43: "{{cba_benefit_breakdown}}\n{{cba_cost_breakdown}}\n{{cba_cash_flow_table}}",
}
# hand-authored static tables (docx index -> (columns, rows)) - the cells may hold {{tokens}}
STATIC_AUTHORED = {
    5: (["क्र.स.", "विवरण", ""], [
        ["१", "सा.व.को नाम", "{{forest_name}}"],
        ["२", "सा.व.को ठेगाना", "{{forest_municipality}}-{{forest_ward}}, {{forest_district}}"],
        ["३", "जम्मा क्षेत्रफल", "{{total_area_hectares}} हेक्टर"],
        ["४", "सघन वन व्यवस्थापन क्षेत्र", "{{ti_production_area_ha}} हेक्टर"],
        ["५", "सिमाना", "पुर्वः {{cf_boundary_east}}, पश्चिमः {{cf_boundary_west}}, उत्तरः {{cf_boundary_north}}, दक्षिणः {{cf_boundary_south}}"],
        ["६", "उचाई", "{{elevation_min_m}} देखि {{elevation_max_m}} मिटर"],
        ["७", "मोहडा", "{{aspect_dominant_names}}"],
        ["८", "माटो", "{{soil_texture_names}}"],
        ["९", "भिरालोपन", "{{slope_range_deg}}"],
        ["१०", "हावापानी", "औसत तापक्रम {{temperature_mean_c}} °से. र वार्षिक वर्षा {{precipitation_mean_mm}} मि.मि."],
        ["११", "वनको किसिम", "{{forest_type}}"],
        ["१२", "वनको प्रकार", "{{forest_type_dominant}}"],
        ["१३", "मुख्य प्रजाती", "{{fi_main_species_names}}"],
        ["१४", "औषत छत्र घनत्व", "{{avg_crown_density_pct}} प्रतिशत"],
        ["१५", "भु-क्षय", "{{erosion_status_word}}"],
        ["१६", "मुख्या गैह्रकाष्ठ वन पैदावार", "{{main_non_timber_fp}}"],
    ]),
    9: (["क्र.स", "मुख्य पेशा", "घरधुरी"], [["१", "कृषि", ""]]),
    22: (["मुख्य प्रजाति", "अन्य प्रजाति"], [["{{fi_main_species_names}}", "{{fi_other_species_names}}"]]),
}


# ── building blocks ──────────────────────────────────────────────────────────
_counter = [0]


def node(type_, title="", content="", children=None, **kw):
    from app.services.operational_plan.tree_models import TreeNode

    _counter[0] += 1
    d = TreeNode(id=str(uuid.uuid5(NS, f"rambhadevi-{_counter[0]}")), type=type_, title_ne=title, content=content,
                 children=children or [], **kw).model_dump()
    return d


def prose(i: int, text: str) -> str:
    """The paragraph text of block i, ready for the template: replacements, forest values to tokens, digits."""
    if i in FULL:
        return digits(unicodedata.normalize("NFC", FULL[i]))
    t = unicodedata.normalize("NFC", text).strip()
    t = t.replace("‍", "")
    t = re.sub(r"[  ]{2,}", " ", t)
    for pat, rep in REPL.get(i, []):
        t = re.sub(pat, rep, t)
    for pat, rep in SUBS:
        t = re.sub(pat, rep, t)
    return digits(t)


def clean_title(text: str) -> str:
    t = unicodedata.normalize("NFC", text).strip()
    t = re.sub(r"^परिच्छेद\s*[-–:]?\s*[0-9०-९]+\s*[:\-–]?\s*", "", t)
    t = re.sub(r"^[0-9०-९]+(?:\s*[.।]\s*[0-9०-९]+)*\s*[.:।]?\s*", "", t)
    return digits(re.sub(r"\s+", " ", t)).strip()


def crossrefs(text: str, seq: dict) -> str:
    """'तालिका 2२' / 'चित्र ६' / 'तालिका नं. १६' -> the same reference in Devanagari (captions are numbered 1..N in order)."""
    def sub(m):
        kind, num = m.group(1), int(m.group(3).translate(str.maketrans("०१२३४५६७८९", "0123456789")))
        return f"{kind} {m.group(2) or ''}{dev(num)}"

    return re.sub(r"(तालिका|चित्र)\s*(नं\.\s*)?([0-9०-९]+)", sub, text)


def static_table(n: int, lead_title: str = "") -> dict:
    """A static table copied from table n of the source (cells verbatim; ragged rows padded)."""
    if n in STATIC_AUTHORED:
        cols, rows = STATIC_AUTHORED[n]
        return {"caption": "", "columns": cols, "rows": rows, "merges": []}
    t = next(x for x in BODY if x["k"] == "t" and x["n"] == n)
    rows = [[digits(unicodedata.normalize("NFC", c).replace("\xa0", " ").strip()) for c in r] for r in t["rows"]]
    merges = []
    if n == 27:                                   # calendar: header row 1 = programme cols, row 2 = months
        cols = rows[0][:2] + rows[1][2:]
        body = rows[2:]
    elif n == 28:                                 # price list: quality grades A/B/C/D
        cols = rows[0][:3] + [f"गुणस्तर अनुसार प्रति इकाई मुल्य ({g})" for g in rows[1][3:7]] + [rows[0][4]]
        body = rows[2:]
    elif n == 35:                                 # penalties: 1st / 2nd / 3rd offence
        cols = rows[0][:2] + rows[1][2:5] + [rows[0][3]]
        body = rows[2:]
    elif len(rows) > 1 and rows[1] and rows[1][0] == "" and n in (6,):
        cols, body = rows[0], rows[2:]
    else:
        cols, body = rows[0], rows[1:]
    width = len(cols)
    out = []
    for ri, r in enumerate(body):
        r = list(r)
        if n == 35 and len(r) == width - 2:       # one cell spans the three penalty columns
            merges.append({"row": ri, "col": 2, "rowspan": 1, "colspan": 3})
            r = r[:2] + [r[2], "", ""] + r[3:]
        out.append((r + [""] * width)[:width])
    if n == 30 and len(cols) == 5:
        cols = cols + ["कैफियत"]
        out = [(r + [""] * 6)[:6] for r in out]
    return {"caption": "", "columns": cols, "rows": out, "merges": merges}


# ── the walk ─────────────────────────────────────────────────────────────────
def build_tree():
    from app.services.operational_plan.cover import ensure_cover_node  # noqa: F401  (imported to fail early if broken)

    blocks = BODY
    captions = {"तालिका": 0, "चित्र": 0}
    cap_lines: list = []            # for the list of tables / figures
    corrections: list = []
    tree: list = []

    # ---- cover (template-owned) ----
    cover_lines = [
        "{{asset:cf_logo}}",
        "क्रम संख्याः {{cf_code}}",
        "जिल्ला/सव-डिभिजन/ स्थानिय तह/संख्या",
        "",
        "श्री {{forest_name}} सामुदायिक वन उपभोक्ता समूह",
        "{{forest_municipality}}-{{forest_ward}}, {{forest_district}}",
        "वन संवर्धन प्रणालीमा आधारित वन व्यवस्थापन कार्ययोजना, {{op_preparation_year}}",
        "आ.व. {{op_start_fy}} देखि आ.व. {{op_end_fy}} सम्म",
        "",
        "COMMUNITY FORESTRY OPERATIONAL PLAN",
        "FY {{op_start_fy}} TO {{op_end_fy}}",
        "Serial Number: {{cf_code}}",
        "District//Sub-Division/Local Level/No",
    ]
    tree.append(node("preamble", "सामुदायिक वनको कार्ययोजना", "\n".join(cover_lines), is_cover=True, cover_meta={
        "border_style": "double", "align": "center", "front_page_format": "lowerRoman",
        "footer_text": "श्री {{forest_name}} सामुदायिक वनको वन व्यवस्थापन कार्ययोजना – {{op_preparation_year}}",
    }))
    tree.append(node("preamble", "", ("{{forest_name}} सामुदायिक वनको कार्ययोजना {{op_preparation_year}}\n\n" +
        "वन कार्ययोजना तयार गर्ने\nश्री {{forest_name}} सामुदायिक वन उपभोक्ता समूह\n{{forest_municipality}}-{{forest_ward}}, {{forest_district}}\n\n"
        "प्राविधिक सहयोग\nडिभिजन वन कार्यालय, {{division}},\n{{sub_division}} सव डिभिजन वन कार्यालय, {{division}},\n"
        "सेवा प्रदायक:- {{technical_assistance_org}}")))
    sign = {"caption": "", "columns": ["पेश गर्ने", "चेकजाँच गरी सिफारिस गर्ने"], "rows": [[
        "............................\n{{cf_chairperson}}\nअध्यक्ष\n{{forest_name}} सामुदायिक वन उपभोक्ता समूह\n{{forest_municipality}}-{{forest_ward}}, {{forest_district}}\nमिति: {{op_preparation_year}}/....../......",
        "............................\n{{sub_division_chief}}\nवन अधिकृत\n{{sub_division}} सव डिभिजन वन कार्यालय {{division}}\nमिति: {{op_preparation_year}}/....../......"],
        ["सिफारिस गर्ने\n............................\n{{forest_management_section_chief}}\nवन अधिकृत\nडिभिजन वन कार्यालय, {{division}}\nमिति: {{op_preparation_year}}/....../......",
         "स्वीकृत गर्ने\n............................\n{{division_forest_officer}}\nडिभिजनल वन अधिकृत\nडिभिजन वन कार्यालय, {{division}}\nमिति: {{op_preparation_year}}/....../......"]],
        "merges": []}
    approval = node("preamble", "वन कार्ययोजना स्वीकृति", prose(46, blocks[46]["text"]) + "\n{{inline_table:0}}",
                    inline_tables=[sign], page_format="upperRoman", restart_pages=True)
    tree.append(approval)

    # ---- summary ----
    lines = [prose(i, blocks[i]["text"]) for i in range(67, 102) if blocks[i]["k"] == "p" and blocks[i]["text"].strip()]
    lines += [prose(102, blocks[102]["text"]), prose(103, blocks[103]["text"]), "{{fi_unit_per_ha_summary_table}}",
              prose(106, blocks[106]["text"]), "{{fi_forest_state_table}}", prose(108, blocks[108]["text"]),
              "{{cba_cash_flow_table}}", "{{cba_summary_table}}"]
    tree.append(node("preamble", "कार्ययोजनाको साराशं", "\n".join(lines)))

    tree.append(node("preamble", "प्रस्तावना", prose(125, blocks[125]["text"])))

    # ---- kabuliyatnama ----
    kab = [prose(130, blocks[130]["text"]), prose(131, blocks[131]["text"])]
    kab += [prose(i, blocks[i]["text"]) for i in range(132, 153)]
    kab += [prose(153, blocks[153]["text"]), "{{uc_members}}"]
    tree.append(node("preamble", "कबुलियतनामा", "\n".join(kab)))
    tree.append(node("preamble", "संक्षिप्त शब्दहरूको सूचि",
                     "\n".join(prose(i, blocks[i]["text"]).replace("\t\t\t", "\t").replace("\t\t", "\t") for i in range(158, 188) if blocks[i]["text"].strip())))
    list_node = node("preamble", "तालिकाहरु", "")
    tree.append(list_node)

    # ---- chapters, sections and annexes ----
    ch = sub = sub3 = cur = None
    first_chapter = True
    annex_letter = 0

    def new_chapter(title, i):
        nonlocal ch, sub, sub3, cur, first_chapter
        kw = {}
        if first_chapter:
            kw = {"page_format": "decimal", "restart_pages": True}
            first_chapter = False
        ch = node("section", clean_title(title), number_prefix="परिच्छेद ", number_sep=" ", **kw)
        tree.append(ch)
        sub = sub3 = None
        cur = ch

    def new_sub(title, level3=False):
        nonlocal sub, sub3, cur
        n = node("subsection", clean_title(title), number_sep=" ")
        if level3 and sub is not None:
            sub["children"].append(n)
            sub3 = n
        else:
            ch["children"].append(n)
            sub, sub3 = n, None
        cur = n

    def add(text):
        if text is None or not str(text).strip():
            return
        cur["content"] = (cur["content"] + "\n" if cur["content"] else "") + str(text).strip()

    def cap_number(kind):
        captions[kind] += 1
        return captions[kind]

    appendix = None
    i = 233
    end = len(blocks)
    while i < end:
        x = blocks[i]
        if x["k"] == "t":
            n = x["n"]
            if n in TABLE_TOKENS:
                add(TABLE_TOKENS[n])
            else:
                tbl = static_table(n)
                idx = len(cur["inline_tables"] or [])
                cur["inline_tables"] = (cur["inline_tables"] or []) + [tbl]
                add("{{inline_table:%d}}" % idx)
            i += 1
            continue
        text = x["text"].strip()
        style = x["style"]
        is_h = style.startswith("Heading ")
        # chapter titles (some are Normal paragraphs in the source)
        if text.startswith("परिच्छेद") and len(text) < 120 and i < 790:
            if style != "Heading 1":
                corrections.append(f"block {i}: chapter title '{text[:40]}' is a plain paragraph in the source -> made a chapter")
            new_chapter(text, i)
            i += 1
            continue
        if text.startswith("अनुसूचीहरु") and style != "Heading 1":
            i += 1
            continue
        if style == "Heading 1" and text.startswith("अनुसुचि"):
            letter = None
            m = re.search(r"\(([क-ह]+)\)", text)
            title = re.sub(r"^अनुसुचि\s*[0-9०-९]+\s*", "", text)
            num = re.match(r"^अनुसुचि\s*([0-9०-९]+)", text).group(1)
            num = dev(int(num.translate(str.maketrans("०१२३४५६७८९", "0123456789"))))
            if m and num == "१":
                letter = ANNEX_LETTERS[annex_letter]
                if m.group(1) != letter:
                    corrections.append(f"block {i}: annex 1 letter ({m.group(1)}) -> ({letter})")
                annex_letter += 1
                title = re.sub(r"^\([क-ह]+\)\s*", "", title)
                full = f"अनुसुचि {num} ({letter}) {digits(title.strip())}"
            else:
                full = digits(text.replace("अनुसुचि", "अनुसुचि", 1))
            appendix = node("appendix", full)
            tree.append(appendix)
            ch = sub = sub3 = None
            cur = appendix
            if i in ANNEX_MAP:
                add(ANNEX_MAP[i])
            i += 1
            continue
        if style == "Normal" and text.startswith("अनुसुचि १ (") and 790 < i < 860:   # the aspect annex title is a plain paragraph
            m = re.search(r"\(([क-ह]+)\)\s*(.*)$", text)
            letter = ANNEX_LETTERS[annex_letter]
            annex_letter += 1
            corrections.append(f"block {i}: annex title is a plain paragraph -> made an annex heading; letter ({m.group(1)}) -> ({letter})")
            appendix = node("appendix", f"अनुसुचि १ ({letter}) {digits(m.group(2).strip())}")
            tree.append(appendix)
            ch = sub = sub3 = None
            cur = appendix
            if i + 1 in ANNEX_MAP or i in ANNEX_MAP:
                add(ANNEX_MAP.get(i) or ANNEX_MAP.get(i + 1))
            i += 1
            continue
        if appendix is not None and ch is None:
            # annex heading letters that follow in sequence: their map tokens
            if is_h and text.startswith("अनुसुचि"):
                pass
        if is_h and style == "Heading 2" and ch is not None:
            new_sub(text)
            i += 1
            continue
        if is_h and style == "Heading 3" and ch is not None:
            new_sub(text, level3=True)
            i += 1
            continue
        if ch is not None and style == "Normal" and re.match(r"^[0-9]\.[0-9]\.[0-9]\s", text) and len(text) < 100:
            corrections.append(f"block {i}: sub-section title '{text[:30]}' is a plain paragraph in the source -> made a sub-section")
            new_sub(text, level3=True)
            i += 1
            continue
        if style == "table of figures" or (not text and not x.get("img")):
            i += 1
            continue
        if cur is None:
            i += 1
            continue
        # captions
        m = re.match(r"^\s*(तालिका|चित्र)\s*([0-9०-९]+)\s*(.*)$", text)
        if m and (style == "Caption" or len(text) < 170) and style != "Heading 2":
            kind = m.group(1)
            no = cap_number(kind)
            line = f"{kind} {dev(no)} {digits(unicodedata.normalize('NFC', m.group(3)).strip())}"
            cap_lines.append((kind, line))
            if x.get("img") and i in IMG:
                add(IMG[i])
            add(line)
            i += 1
            continue
        if x.get("img"):
            if IMG.get(i):
                add(IMG[i])
            if not text:
                i += 1
                continue
        if i in IMG and IMG[i] is None:
            i += 1
            continue
        # prose
        t = prose(i, text)
        t = crossrefs(t, {})
        if style == "List Paragraph" and not t.startswith(("•", "-")):
            t = "• " + t
        add(t)
        if i in AFTER:
            add(AFTER[i])
        i += 1

    # list of tables and figures (captions are static text; page numbers cannot be, they change per forest)
    tl = [ln for k, ln in cap_lines if k == "तालिका"]
    fl = [ln for k, ln in cap_lines if k == "चित्र"]
    list_node["content"] = "\n".join(tl + ["", "चित्रहरु"] + fl)

    # wide tables are on landscape pages in the source: the per-unit stock table (4.2.1), the budget table (8.2)
    # and the stem-list / cost-benefit annexes 4 and 5
    def mark_landscape(nodes):
        for n in nodes:
            if n["title_ne"].startswith(("समग्र वनको मौज्दातको अवस्था", "कार्य योजना अवधिको लागि वार्षिक क्रियाकलाप",
                                         "अनुसुचि ४", "अनुसुचि ५")):
                n["landscape"] = True
            mark_landscape(n["children"])

    mark_landscape(tree)
    return tree, corrections


def description_text():
    return ("दिगो वन व्यवस्थापन (वन सम्वर्द्धन प्रणालीमा आधारित वन व्यवस्थापन कार्यविधि) अनुसार तयार हुने सामुदायिक वनको पुनरावलोकन (Renew) कार्ययोजना: "
            "आवरण, स्वीकृति, सारांश, कबुलियतनामा, १३ परिच्छेद र अनुसूचीहरु (नक्सा, कोअर्डिनेट, रुख नक्शाङ्कन सूची, लागत-लाभ विश्लेषण) सहित, रम्भादेवी सामुदायिक वन "
            "कार्ययोजनाको ढाँचामा। लुम्बिनी प्रदेश वन नियमावली अनुसार दश वर्षे कार्ययोजना नवीकरण गर्दै गरेका सामुदायिक वन उपभोक्ता समूहका लागि उपयुक्त; "
            "क्षेत्र सर्वेक्षण, रुख नक्शाङ्कन (stem mapping), रास्टर विश्लेषण, घरधुरी र वार्षिक योजनाका तथ्याङ्कले स्वतः भरिन्छ।")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="build and validate, do not write to the database")
    ap.add_argument("--report", action="store_true", help="print numbering corrections and leftover forest-specific text")
    args = ap.parse_args()

    tree, corrections = build_tree()
    # regulation-group species tables/charts/narration (fi_reg_*, fi_regc_*): right after the species-wise tree stock node
    from app.services.operational_plan.regulation_species_section import insert_into_tree
    insert_into_tree(tree, after_token="{{fi_species_tree_per_ha_table}}")
    from app.services.operational_plan.auto_numbering import recompute_numbers
    from app.services.operational_plan.tree_models import TreeNode

    nodes = [TreeNode.from_dict(json.loads(json.dumps(n))) for n in tree]
    recompute_numbers(nodes, "NP")
    tree = [n.model_dump() for n in nodes]

    def walk(ns):
        for n in ns:
            yield n
            yield from walk(n["children"])

    all_nodes = list(walk(tree))
    tokens = sorted({t for n in all_nodes for t in re.findall(r"\{\{([^}]+)\}\}", n["content"] or "")}
                    | {t for n in all_nodes for tb in (n["inline_tables"] or []) for r in tb["rows"] for c in r
                       for t in re.findall(r"\{\{([^}]+)\}\}", str(c))}
                    | {t for n in all_nodes for t in re.findall(r"\{\{([^}]+)\}\}", n["title_ne"] or "")}
                    | {t for n in all_nodes for t in re.findall(r"\{\{([^}]+)\}\}", json.dumps(n.get("cover_meta") or {}, ensure_ascii=False))})
    print(f"{len(all_nodes)} nodes, {len(tokens)} distinct placeholders")

    if args.report:
        marks = re.compile(r"रम्भादेव|देवदह|दलदले|रूपन्देही|रुपन्देही|तिलोत्तमा|पाल्पा|आरे खोला|चुली|तिरतिरे|त्रिशुली|२६४|११७|१४६|C1S[0-9]|साल\b|अस्ना")
        left = []
        for n in all_nodes:
            for ln in (n["content"] or "").split("\n"):
                if marks.search(ln):
                    left.append((n["title_ne"][:30], ln[:150]))
        print("\n-- paragraphs that still mention the source forest (review):", len(left))
        for t, ln in left:
            print(" ", t, "|", ln)
        print("\n-- numbering corrections:", len(corrections))
        for c in corrections:
            print(" ", c)

    from app.core.database import SessionLocal
    from app.services.operational_plan.template_validation import validate_template
    from app.services.operational_plan.variable_registry import VARIABLE_REGISTRY

    unknown = [t for t in tokens if t.removesuffix(":full") not in VARIABLE_REGISTRY and not t.startswith("inline_table:")]
    print("tokens not in the variable registry:", unknown or "none")

    db = SessionLocal()
    result = validate_template(db, tree, plan_kind="sustainable_fmp_revision", for_publish=False, description=description_text())
    print("validation:", "ok" if result["ok"] else "ERRORS", f"{len(result['errors'])} errors, {len(result['warnings'])} warnings")
    for e in result["errors"][:15]:
        print("  ERROR", e.get("code"), e.get("message"))
    for w in result["warnings"][:15]:
        print("  warn ", w.get("code"), w.get("message"))
    if args.dry_run or not result["ok"]:
        return 0 if result["ok"] else 1

    from app.models.op_template import OPTemplate, OPTemplateVersion
    from app.models.user import User
    from app.api.operational_plans import generate_template_summaries

    summaries = generate_template_summaries(tree)
    from app.models.user import UserRole

    # the template belongs to a super admin (the account that owns the other Sustainable-plan drafts), so it shows up
    # under Templates -> My templates and can be submitted/published from there
    owner = (db.query(User).filter(User.role == UserRole.SUPER_ADMIN).order_by(User.created_at).first()
             or db.query(User).filter(User.role == UserRole.TEMPLATE_DESIGNER).first())
    tmpl = db.query(OPTemplate).filter(OPTemplate.name == TEMPLATE_NAME).first()
    if tmpl is not None and owner is not None and tmpl.created_by != owner.id:
        tmpl.created_by = owner.id
    if tmpl is None:
        tmpl = OPTemplate(name=TEMPLATE_NAME, status="draft", created_by=owner.id if owner else None)
        db.add(tmpl)
    else:
        db.add(OPTemplateVersion(template_id=tmpl.id, version=tmpl.version, tree=tmpl.tree, name=tmpl.name,
                                 description=tmpl.description, changelog="before rebuild by build_rambhadevi_template.py"))
        tmpl.version = (tmpl.version or 1) + 1
    tmpl.description = description_text()
    tmpl.tree = tree
    tmpl.plan_kind, tmpl.plan_regime, tmpl.plan_stage = "sustainable_fmp_revision", "sustainable_fmp", "revision"
    tmpl.sections_summary = summaries["sections_summary"]
    tmpl.variables_summary = summaries["variables_summary"]
    tmpl.changelog = "Built from the Rambhadevi CF OP (docx) by build_rambhadevi_template.py"
    db.commit()
    print("template saved:", tmpl.id, "version", tmpl.version, "status", tmpl.status)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
