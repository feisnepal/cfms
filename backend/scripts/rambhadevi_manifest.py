"""Placeholder manifest for 'Rambhadevi CF OP.docx' + highlighted review copy.

Anchor: int = paragraph block index in body.json (from rambhadevi_extract.py), 'T<n>' = table n.
Class: A ready | E modify existing | C new, computed from existing data | D new, metadata/manual input.
(Fixed text is not listed - it needs no placeholder.)
Output (next to the source): manifest.tsv, manifest_summary.txt, 'Rambhadevi CF OP - placeholders.docx'.
Run from the repo root:  venv/Scripts/python.exe -X utf8 backend/scripts/rambhadevi_manifest.py [--check]
"""
import collections
import copy
import sys
from pathlib import Path

import docx
from docx.enum.text import WD_COLOR_INDEX
from docx.oxml.ns import qn
from docx.text.paragraph import Paragraph

BASE = Path("testData/SFM_data")
OUT = BASE / "rambhadevi_extract"
UG = "{{forest_ward}}, {{forest_municipality}}, {{forest_district}}"
S = []  # (anchor, class, token, note)


def a(anchor, cls, token, note=""):
    S.append((anchor, cls, token, note))


# --- cover / title page -------------------------------------------------------
for blk, tok, n in [
    (6, "{{cf_code}}", "serial number"), (9, "{{user_group_name}}", ""), (10, UG, "address"),
    (11, "{{op_preparation_year}}", "plan year in title"), (14, "{{op_start_fy}} - {{op_end_fy}}", ""),
    (17, "{{op_start_fy}} - {{op_end_fy}}", "English FY line"), (19, "{{cf_code}}", ""),
    (22, "{{forest_name}}", ""), (23, "{{op_preparation_year}}", ""),
    (36, "{{user_group_name}}", ""), (37, UG, ""), (42, "{{division}}", ""),
    (43, "{{sub_division}}", ""), (44, "{{technical_assistance_org}}", "service provider")]:
    a(blk, "A", tok, n)
# --- approval page ------------------------------------------------------------
for tok in ["{{user_group_name}}", UG, "{{division}}", "{{technical_assistance_org}}"]:
    a(46, "A", tok)
for k in ["east", "south", "west", "north"]:
    a(46, "A", "{{cf_boundary_%s}}" % k)
a(46, "A", "{{total_area_hectares}}"); a(46, "A", "{{op_start_fy}}"); a(46, "A", "{{op_end_fy}}")
# --- title-page signature text boxes (were missed in the first pass: they sit in text boxes) ---
a(47, "D", "{{cf_chairperson_name}}", "'पेश गर्ने' - chairperson name; add to the metadata form (committee table is only a fallback)")
a(47, "A", "{{user_group_name}}", "chairperson block: group"); a(47, "A", UG, "chairperson block: address")
a(47, "A", "{{sub_division_chief}}", "'चेकजाँच गरी सिफारिस गर्ने' - sub-division forest officer (field exists in the form)")
a(47, "A", "{{sub_division}}", "his/her office"); a(47, "A", "{{op_preparation_year}}", "signature date year")
a(59, "A", "{{division_forest_officer}}", "'स्वीकृत गर्ने' - division forest officer (field exists)")
a(59, "A", "{{division}}", "his/her office")
a(59, "A", "{{forest_management_section_chief}}", "'सिफारिस गर्ने' forest officer - CONFIRM this is the intended field")
a(59, "A", "{{op_preparation_year}}", "signature date year")
# --- preface (प्रस्तावना): the first pass missed the forest-specific values ---
for tok in ["{{forest_district}}", "{{forest_municipality}}", "{{forest_ward}}", "{{total_area_hectares}}", "{{user_group_name}}"]:
    a(125, "A", tok, "preface sentence")
# --- footer (every page) ---
a("FOOTER", "A", "{{user_group_name}}", "footer text: 'श्री <group> सामुदायिक वनको वन व्यवस्थापन कार्ययोजना – <year>'")
a("FOOTER", "A", "{{op_preparation_year}}", "footer text year")
a("FOOTER", "C", "{{page_number_format}}", "exporter: roman (front) -> arabic from chapter 1; needs exporter work, not a data token")
# --- summary ------------------------------------------------------------------
for blk, cls, tok, n in [
    (68, "A", "{{sub_division}}", ""), (69, "A", "{{user_group_name}}", ""), (70, "A", UG, ""),
    (71, "A", "{{cf_code}}", ""), (72, "A", "{{hh_total_households}}", ""), (73, "A", "{{op_start_fy}}", "approval FY"),
    (74, "A", "{{hh_total_population}}", ""), (74, "A", "{{hh_total_female}}", ""), (74, "A", "{{hh_total_male}}", ""),
    (75, "E", "{{uc_female_members}}", "new scalar; only dict uc_gender_distribution exists"),
    (75, "E", "{{uc_male_members}}", "new scalar"), (75, "A", "{{uc_total_members}}", ""),
    (77, "A", "{{forest_name}}", ""), (78, "A", "{{cf_handover_date}}", ""),
    (79, "D", "{{cf_first_renewal_date}}", "new metadata field"),
    (80, "A", "{{total_area_hectares}}", ""), (81, "A", "{{ti_protected_area_ha}}", ""),
    (82, "A", "{{ti_effective_area_ha}}", "area of compartments + sub-compartments"),
    (83, "A", "{{forest_type}}", ""), (84, "A", "{{forest_avg_age}}", ""), (85, "A", "{{fi_dominant_species}}", ""),
    (86, "A", "{{main_non_timber_fp}}", ""), (87, "A", "{{avg_crown_density_pct}}", ""),
    (88, "E", "{{aspect_dominant_names}}", "scalar from aspect raster section"),
    (89, "E", "{{slope_range_deg}}", "scalar min-max slope"),
    (90, "E", "{{soil_texture_names}}", "scalar from soil section"),
    (91, "E", "{{erosion_status_word}}", "word class from soil-loss analysis"),
    (93, "A", "{{blocks_count}}", "compartments"), (93, "A", "{{sub_areas_total}}", "sub-compartments"),
    (94, "D", "{{rotation_years}}", "new metadata field"), (94, "D", "{{silviculture_system}}", "new metadata field"),
    (95, "D", "{{regeneration_period_years}}", "new metadata field"), (95, "E", "{{plan_duration_years}}", "in the metadata schema but not registered as a variable"),
    (96, "C", "{{sfm_regeneration_felling_unit}}", "unit chosen for regeneration felling"),
    (96, "C", "{{sfm_preparatory_felling_unit}}", ""),
    (97, "C", "{{sm_felling_annual_trees}}", "from sm_felling_totals / AAH"),
    (97, "C", "{{sm_mother_trees_per_ha}}", ""), (98, "D", "{{mother_tree_spacing_m}}", "new metadata field"),
    (99, "C", "{{sfm_annual_yield_timber_cft}}", "regeneration-felling yield"),
    (99, "C", "{{sfm_annual_yield_firewood_chatta}}", ""),
    ("T1", "E", "{{fi_unit_summaries}} per-ha table", "area, regen/sapling/pole/tree per ha, basal area, stock"),
    ("T2", "E", "{{fi_forest_condition}} + stock table", "stock + condition words"),
    ("T3", "E", "{{cba_cash_flow_table}}", "year-wise income/expense/NPV + B/C, IRR")]:
    a(blk, cls, tok, n)
# --- kabuliyatnama ------------------------------------------------------------
for tok in ["{{district}}", "{{municipality}}", "{{ward}}", "{{user_group_name}}"]:
    a(130, "A", tok)
for k in ["east", "south", "west", "north"]:
    a(130, "A", "{{cf_boundary_%s}}" % k)
a(130, "A", "{{total_area_hectares}}"); a(153, "A", UG + ", {{user_group_name}}")
a(153, "A", "{{kabuliyatnama_date}}")
a("T4", "E", "{{uc_members}} rows (name, address)", "executants table - one row per committee member")
a("T4", "D", "{{kabuliyatnama_witnesses}}", "witnesses (साक्षी/रोहवर) - manual")
# --- chapter 1 ----------------------------------------------------------------
a(235, "A", "{{forest_name}}"); a(235, "A", "{{op_preparation_year}}")
a(236, "A", "{{division}}"); a(241, "A", "{{division}}")
# --- chapter 2 ----------------------------------------------------------------
a(297, "D", "{{cf_history_note}}", "short local story (editable free text) - generic wording by default; the Rambhadevi-specific story is NOT copied")
a(298, "A", "{{forest_municipality}}, {{forest_ward}}", "location sentence")
a(299, "A", "{{cf_handover_date}}", "registration year")
for tok in ["{{landcover_1984_dominant}}", "{{landcover_1984_percentages}}", "{{forest_loss_hectares}}", "{{forest_gain_hectares}}",
            "{{forest_loss_by_year}}", "{{section:forest_loss}}", "{{map:landcover_1984}}"]:
    a(299, "A", tok, "2.1 supplementary history from data: 1984 land use + Hansen forest loss/gain")
for tok in ["{{forest_name}}", UG, "{{total_area_hectares}}", "{{cf_registration_number}}", "{{cf_handover_date}}",
            "{{hh_total_households}}", "{{hh_total_population}}", "{{uc_total_members}}", "{{forest_type}}",
            "{{forest_avg_age}}", "{{cf_boundary_east}} .. {{cf_boundary_north}}"]:
    a("T5", "A", tok, "general-information table row")
a("T5", "D", "{{registration_office}}", "metadata (field exists in the metadata form schema)")
a("T5", "D", "{{cf_first_renewal_date}}", "")
a(310, "A", "{{total_area_hectares}}"); a(310, "E", "{{sfm_protection_area_ha}}", ">30 deg steep-area wording")
a("T6", "E", "{{block_area_detail_merged}} / {{compartment_summary}}", "add a 'location' column")
a("T7", "A", "{{fi_regeneration_per_ha}} {{fi_sapling_per_ha}} {{fi_pole_per_ha}} {{fi_tree_per_ha}}", "per-ha stock")
a(328, "A", "{{utm_zone}}", "UTM zone note")
a(331, "A", "{{section:land_cover}} {{ug_land_cover_classes}}", "land-use narration")
for tok in ["{{watershed}}", "{{major_river_basin}}", "{{physiography_zone}}", "{{thememap:forest__drainage_vectors}}"]:
    a(331, "A", tok, "replaces the Rambhadevi-only north/south description")
a(331, "E", "{{drainage_summary}}", "streams/rivers crossing the forest, from the drainage attribute table (new scalar)")
a(333, "A", "{{cf_handover_date}}"); a(334, "D", "{{cf_first_renewal_date}}")
a(335, "A", "{{hh_total_households}}"); a(336, "A", "{{hh_total_female}} {{hh_total_male}} {{hh_total_population}}")
a(337, "A", "{{uc_total_members}}")
a("T8", "C", "{{hh_caste_prosperity_table}}", "caste x prosperity cross-tab; rows already hold both fields")
a("T9", "D", "{{table:table_occupation}}", "manual table; schema has only forest_based / other flags")
a(345, "A", "{{section_6_previous_review}}", "strengths / weaknesses (free text, editable)")
# --- chapter 3 ----------------------------------------------------------------
a("T10", "A", "{{table:demand_supply}}"); a(381, "A", "{{section:demand_supply_narration}}")
# --- chapter 4 ----------------------------------------------------------------
for tok in ["{{sampling_total_points}}", "{{sampling_actual_intensity}}",
            "{{sampling_plot_shape}} {{sampling_plot_radius_m}}", "{{sampling_forest_area_ha}}"]:
    a(389, "A", tok, "survey method")
a(388, "E", "{{nested_plot_radii_m}}", "nested plot diagram (1.78/2.82/5.64/12.61 m) is a fixed picture; radii in its labels should follow the design")
for tok in ["{{fi_regeneration_per_ha}}", "{{fi_sapling_per_ha}}", "{{fi_pole_per_ha}}", "{{fi_tree_per_ha}}",
            "{{fi_dominant_species}}"]:
    a(395, "A", tok)
a("T11", "E", "{{fi_unit_tree_count_per_ha}}"); a("T12", "E", "{{fi_unit_regeneration_status}}", "regeneration by unit")
a("T13", "C", "{{fi_species_regen_per_ha_table}}", "species x stage per ha")
a(400, "C", "{{chart:fi_unit_regen_per_ha_bar}}", "Fig 1")
a(405, "A", "{{section:field_inventory_narration}}")
a("T14", "E", "{{fi_unit_pole_tree_volume}}", "pole by unit"); a("T15", "C", "{{fi_species_pole_per_ha_table}}")
a(413, "C", "{{chart:fi_species_pole_count_bar}}", "Fig 2"); a(415, "C", "{{chart:fi_species_pole_volume_bar}}", "Fig 3")
a(416, "A", "{{section:ti_species_stock_narration}}")
a("T16", "E", "{{fi_unit_pole_tree_volume}}", "tree by unit"); a("T17", "C", "{{fi_species_tree_per_ha_table}}")
a(424, "C", "{{chart:fi_species_tree_count_bar}}", "Fig 4"); a(425, "C", "{{chart:fi_species_tree_volume_bar}}", "Fig 5")
a(426, "A", "{{section:ti_species_dbh_narration}}"); a(427, "A", "{{fi_dominant_species}} note")
a(431, "A", "{{chart:dbh_class_count_bar}}", "Fig 6"); a(433, "A", "{{chart:dbh_class_bar}}", "Fig 7")
a(429, "A", "{{section:ti_dbh_perha_narration}}")
a(436, "C", "{{sfm_regeneration_felling_unit}}"); a("T18", "E", "{{sm_felling_totals}}", "trees, basal area, volume, firewood")
a(440, "C", "{{sm_species_count}}", "number of species in the felling unit")
a("T19", "E", "{{sm_felling_tree_by_species}}")
a(444, "E", "{{sm_mother_tree_coverage}}"); a("T20", "E", "{{sm_mother_tree_by_species}}")
a("T21", "C", "{{ya_felling_by_year_table}}", "activity x FY yield (RF/PF/thinning), from AAH + yearly plan")
a("T22", "E", "{{fi_dominant_species}} / {{fi_associated_species}}", "main vs other species")
# --- chapter 5 ----------------------------------------------------------------
a(478, "A", "{{physiography_zone}}", "replaces the typed 'भावर'"); a(478, "A", "{{fi_dominant_species}}", "replaces the typed 'साल'"); a(478, "D", "{{silviculture_system}}"); a(480, "D", "{{rotation_years}}"); a(480, "D", "{{regeneration_period_years}}")
a(482, "A", "{{blocks_count}}"); a(482, "A", "{{sub_areas_total}}")
a("T23", "C", "{{fire_line_plan_table}}", "from fire_line features + yearly plan")
a(508, "C", "{{sm_felling_annual_trees}}"); a(508, "C", "{{sm_mother_trees_per_ha}}")
a(518, "C", "{{sfm_regeneration_felling_unit}}"); a(518, "C", "{{sfm_preparatory_felling_unit}}")
a(520, "C", "{{sfm_regeneration_felling_unit}}"); a(520, "C", "{{sfm_preparatory_felling_unit}}")
a(522, "D", "{{rotation_years}}"); a(522, "D", "{{regeneration_period_years}}")
a("T26", "C", "{{ya_felling_by_year_table}}", "silviculture schedule by FY")
# --- chapters 6-8 -------------------------------------------------------------
a("T28", "D", "{{table:table_17}}", "distribution rates - manual")
a("T29", "D", "{{table:table_timber_per_household}}", "manual")
a("T30", "D", "{{table:table_contingency}}", "manual")
a(614, "A", "{{main_non_timber_fp}}")
a("T31", "E", "{{ya_activity_plan_detail}} / {{ya_plan_matrix}}", "reformat to PDF columns (147 rows)")
a(623, "A", "{{ya_total_ten_year_budget}}"); a("T32", "E", "{{cba_cash_flow_table}}")
for tok in ["{{cba_base_bc_ratio}}", "{{cba_base_npv}}", "{{cba_base_irr}}"]:
    a(628, "A", tok)
# --- chapters 10, 13 ----------------------------------------------------------
a(672, "A", "{{bio_total_species}}"); a("T33", "E", "{{table:vegetation_species}}")
a("T34", "E", "{{table:animal_species}}")
a(777, "A", "{{plan_years_range}}", "plan period (13 a)")
# --- annexes ------------------------------------------------------------------
for blk, cls, tok, n in [
    (792, "E", "{{map:boundary}} with satellite basemap", "1(क) boundary over Google/Esri imagery: map:boundary + imagery basemap override"),
    (794, "E", "{{map:boundary}} + {{map:fieldbook}} + {{thememap:forest__drainage_vectors}} + {{opsmap:feature__fire_lines}}", "1(ख) feature map: boundary, survey points, streams, roads, fire line, sub-compartment lines - composite of existing layers"),
    (796, "A", "{{map:sub_compartment}}", "1(ग) sub-compartments with name and area labels"),
    (798, "A", "{{map:sampling_plot}}", "1(घ) numbered sample plots"),
    (800, "A", "{{opsmap:unit__silviculture_year}}", "1(ङ) management activities by sub-compartment (regeneration / preparatory / thinning)"),
    (802, "C", "{{opsmap:unit__stems_all}}", "1(च) all stems in the regeneration-felling unit - new stem-point map from tree inventory"),
    (804, "C", "{{opsmap:unit__stems_felling}}", "1(छ) felling trees - new stem-point map"),
    (806, "C", "{{opsmap:unit__stems_mother}}", "1(ज) mother trees - new stem-point map"),
    (808, "A", "{{map:aspect}}", "1(झ) aspect"), (810, "A", "{{map:dem}}", "1(झ) elevation"),
    (812, "A", "{{map:slope}}", "1(ञ) slope"),
    (813, "A", "{{opsmap:feature__fire_lines}}", "1(ट) fire lines - the source page is EMPTY (no map); the system map fills it")]:
    a(blk, cls, tok, n)
a("T37", "E", "{{fieldbook_points}}", "SN, X, Y (outer ring)")
a("T38", "E", "{{fieldbook_points}} internal", "+ sub-compartment column")
a("T39", "E", "{{sampling_point_locations}}", "SP_Num, X, Y")
a("T40", "C", "{{sm_felling_tree_list}}", "stem list 4(a), 1,200 rows")
a("T41", "C", "{{sm_felling_tree_list}}", "4(b)"); a("T42", "C", "{{sm_felling_tree_list}}", "4(c)")
a("T43", "E", "{{cba_*}}", "annex 5 cost-benefit")


def main():
    import json
    cnt = collections.Counter(c for _, c, _, _ in S)
    toks = {c: len({t for _, cc, t, _ in S if cc == c}) for c in "AECD"}
    body = json.load(open(OUT / "body.json", encoding="utf-8"))
    if "--check" in sys.argv:
        for anchor in sorted({x for x, *_ in S if isinstance(x, int)}):
            b = body[anchor]
            print(anchor, b.get("style", ""), (b.get("text", "") or ("[IMG]" if b.get("img") else ""))[:60].replace("\n", " "))
        return
    with open(OUT / "manifest.tsv", "w", encoding="utf-8") as f:
        f.write("anchor\tclass\ttoken\tnote\n")
        for r in S:
            f.write("\t".join(str(x) for x in r) + "\n")
    summary = (f"insertion points: {len(S)}  A={cnt['A']} E={cnt['E']} C={cnt['C']} D={cnt['D']}\n"
               f"distinct tokens: {len({t for _, _, t, _ in S})}  " + " ".join(f"{c}={toks[c]}" for c in "AECD"))
    (OUT / "manifest_summary.txt").write_text(summary, encoding="utf-8")
    print(summary)

    col = {"A": WD_COLOR_INDEX.BRIGHT_GREEN, "E": WD_COLOR_INDEX.YELLOW,
           "C": WD_COLOR_INDEX.TURQUOISE, "D": WD_COLOR_INDEX.PINK}
    d = docx.Document(str(BASE / "Rambhadevi CF OP.docx"))
    els = list(d.element.body.iterchildren())
    # body.json indexes only <w:p>/<w:tbl>; bookmarkEnd / sdt / sectPr children must not be counted
    elmap, tbl, i = {}, 0, 0
    for el in els:
        if el.tag not in (qn("w:p"), qn("w:tbl")):
            continue
        if el.tag == qn("w:tbl"):
            tbl += 1
            elmap["T%d" % tbl] = el
        elmap[i] = el
        i += 1
    elmap["FOOTER"] = elmap[3]
    by = collections.defaultdict(list)
    for anchor, cls, tok, note in S:
        by[anchor].append((cls, tok))

    def make_par(items):
        newp = copy.deepcopy(next(e for e in els if e.tag == qn("w:p")))
        for ch in list(newp):
            newp.remove(ch)
        par = Paragraph(newp, d.element.body)
        for cls, tok in items:
            r = par.add_run(f" [{cls}] {tok} ")
            r.font.highlight_color = col[cls]
            r.font.size = docx.shared.Pt(9)
        return newp

    for anchor, items in by.items():
        el = elmap.get(anchor)
        if el is None:
            print("missing anchor", anchor)
            continue
        newp = make_par(items)
        (el.addprevious if el.tag == qn("w:tbl") else el.addnext)(newp)
    els[0].addprevious(make_par([("A", "READY - token exists"), ("E", "MODIFY existing token"),
                                 ("C", "NEW computed"), ("D", "NEW metadata / manual")]))
    d.save(str(BASE / "Rambhadevi CF OP - placeholders.docx"))
    print("review copy written")


if __name__ == "__main__":
    main()
