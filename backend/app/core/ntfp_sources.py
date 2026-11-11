"""Where every NTFP method-card value comes from: the sources, and the sourced values (owner requirement 2026-10-22: "the source of a method card
should be specified").

A value is one fact about one species (or one growth form, or one part): the plot size, the maturity sign, the annual allowable harvest, the
season, ... with the document it comes from, the table or page, and a status:

  documented        stated by the source for that species (or part);
  derived           worked out by a stated rule from documented facts (growth-form defaults, part-based method);
  provisional       a best guess, or read from a page image and not yet reviewed: shown as such, needs a person;
  expert_confirmed  a named reviewer has checked it (set by the review import, never by this module).

Several sources may give a different value for the same field (the shrub plot is 25 m2 in the Nepal guideline, 100 m2 in ANSAB, 9 m2 in India's
national inventory): all are kept, and exactly one is ``chosen``. The order of preference is the government guideline of the jurisdiction (Nepal), then
government manuals of other countries, then manuals of recognised bodies (ANSAB, FAO), then rule-derived defaults.

Only what was READ is a value. Documents found but not opened are sources with ``read_status = "lead"`` and give no values.

Seed only: ``alembic/versions/138_ntfp_method_sources.py`` loads these once; from then on the tables ``ntfp_source`` and ``ntfp_method_value`` are the source.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

STATUSES = ("documented", "derived", "provisional", "expert_confirmed")
FIELDS = (
    "growth_class", "part_groups", "sampling_method", "plot_area_sqm", "maturity", "n_individuals", "sample_fraction_pct", "conversion_factor",
    "aah_pct", "rotation_years", "season", "altitude_m", "procedure", "ivi_components",
)

# key -> source. ``tier`` orders preference when sources disagree (lower is preferred).
SOURCES: Dict[str, Dict[str, Any]] = {
    "DOF2069": dict(
        title="गैरकाष्ठ वन पैदावारको स्रोत सर्वेक्षण मार्गदर्शन २०६९ (NTFP Resource Survey Guideline 2069)", publisher="Department of Forests, Government of Nepal",
        year="2069 BS (2012/13)", url=None, tier=1, read_status="read", licence="Government publication",
        note="The guideline the page follows. Annex 1 (30 priority species), Annex 2 (method cards), Tables 3-5, 7, 10, 13."),
    "S7-2079": dict(
        title="वन नियमावली, २०७९ अनुसूची-७ (Forest Regulations 2079, Schedule-7)", publisher="Government of Nepal", year="2079 BS (2022)", url=None, tier=1,
        read_status="read", licence="Government publication", note="The designated NTFP list and the royalty rates; the part (group) each species is harvested for."),
    "ANSAB2010": dict(
        title="Toolkit 2: Participatory Inventory of Non-Timber Forest Products", publisher="ANSAB (Asia Network for Sustainable Agriculture and Bioresources), Nepal",
        year="2010", url="https://ansab.org.np/wp-content/uploads/2024/02/toolkit-2-participatory-inventory-of-ntfps.pdf", tier=3, read_status="read",
        licence="Non-commercial reproduction with acknowledgement",
        note="Table 7 plot sizes, Table 18 annual allowable harvest for 16 species, worked examples (wintergreen, chiraito, ...)."),
    "ANSAB2022": dict(
        title="Toolkit on Sustainable Harvesting of Non-Timber Forest Products (NTFPs)", publisher="ANSAB, Nepal", year="2022",
        url="https://ansab.org.np/wp-content/uploads/2023/08/Toolkit-on-Sustainable-Harvesting-of-NTFPs_eng-ver_final.pdf", tier=3, read_status="read",
        licence="Non-commercial reproduction with acknowledgement; commercial use needs ANSAB's written permission",
        note="Annex 3: harvest-season table (~28 species) and annual allowable harvest table (~17 species); Annexes 4-8: harvesting rules (cites DPR 2020, ANSAB 2010b)."),
    "NWPC2014": dict(
        title="National Working Plan Code 2014", publisher="Ministry of Environment, Forest and Climate Change and Forest Research Institute, India", year="2014",
        url="https://mpforest.gov.in/img/files/National_WP_Code_2014.pdf", tier=2, read_status="read", licence="Government publication",
        note="Paras 70-72 (assessment of NTFPs: sample counts for yield, importance value), para 87 (NTFP working circle: closed area, closed season, harvesting limits)."),
    "FSI-NFI": dict(
        title="National Forest Inventory in India (presentation)", publisher="Forest Survey of India", year="c. 2012",
        url="https://un-redd.org/sites/default/files/2021-10/02_NFI_04_India.pdf", tier=2, read_status="read", licence="Public presentation",
        note="Herb 1 m x 1 m and shrub 3 m x 3 m subplots, 0.1 ha tree plot. A forest inventory, not an NTFP inventory: sizes for orientation."),
    "FAO-GACP2010": dict(
        title="GACP for Medicinal Plants: Illustrated Booklet for Farmers and Collectors (based on the NMPB-WHO Good Field Collection Practices 2009)",
        publisher="FAO with DMAPR (ICAR), India", year="2010",
        url="https://coin.fao.org/coin-static/cms/media/8/13069087097420/trainers_manual_on_gacp_for_medicinal_plants1_latest.pdf", tier=3, read_status="read",
        licence="FAO publication", note="Principles only, no numeric rates: flowers, fruits and leaves regenerate more easily than roots and barks; collect only mature plants, after seed ripening."),
    "RULE": dict(
        title="Default rules of this system (growth form and part harvested)", publisher="NTFP inventory module", year="2026", url=None, tier=9, read_status="read",
        licence="-", note="Values derived from documented facts by a stated rule; always flagged derived or provisional."),
    "MASTER": dict(
        title="Species master (biodiversity_species)", publisher="This system", year="2026", url=None, tier=8, read_status="read", licence="-",
        note="Growth form taken from the species master's sub-category where it has one."),
    # leads: found, not read; they give no values yet
    "HFRI-2009": dict(
        title="Assessment of optimum harvest limits of Picrorhiza kurroa and Valeriana jatamansi in Himachal Pradesh (2009-2014)", publisher="ICFRE - Himalayan Forest Research Institute",
        year="2014", url="https://hfri.icfre.gov.in/UserFiles/File/projects/completed28.html", tier=2, read_status="lead", licence="-",
        note="The project page does not give the limits; the report is needed."),
    "ICFRE-2020": dict(
        title="An Operational Manual: Sustainable Harvesting of Non Timber Forest Produce (NTFPs)", publisher="ICFRE, Dehradun", year="2020",
        url="https://english.icfre.gov.in/books-file/book9.pdf", tier=4, read_status="read", licence="-",
        note="Indian conditions (tropical species); read from the web-archive copy. Ranked below the Nepal sources, which win where both give a figure."),
    "MP-ESIP-2022": dict(
        title="Sustainable Harvesting Protocols for NTFPs (25 species)", publisher="Madhya Pradesh Forest Department (ESIP)", year="2022",
        url="https://www.mpforest.gov.in/img/files/ESIP_Sustainable_Harvesting_Protocols_for_NTFPs_English_2022.pdf", tier=4, read_status="read", licence="-",
        note="Madhya Pradesh (India), 25 species; the English PDF names its date as 20.09.2021. Ranked below the Nepal sources."),
    "NMPB-GFCP-2009": dict(
        title="Good Field Collection Practices (GFCP) standard", publisher="National Medicinal Plants Board (with WHO India)", year="2009", url=None, tier=2,
        read_status="lead", licence="-", note="Known only through the FAO booklet; the standard text was not obtained."),
    "FAIRWILD": dict(
        title="FairWild Standard", publisher="FairWild Foundation", year="2010 (v2), 2023 (v3)", url="https://www.traffic.org/site/assets/files/8523/fairwild-standard-v2.pdf",
        tier=3, read_status="lead", licence="-", note="Resource assessment and harvest management plans; the PDF was only partly readable."),
    "CITES-NDF": dict(
        title="CITES Non-Detriment Findings guidance for perennial plants (modules 11 and 13)", publisher="CITES / BfN", year="2014, 2025", url="https://cites.org/sites/default/files/eng/prog/ndf/ndf_guidance/module_11.pdf",
        tier=3, read_status="lead", licence="-", note="Scoring templates, no harvest rates."),
    "WHO-GACP-2003": dict(
        title="WHO guidelines on good agricultural and collection practices (GACP) for medicinal plants", publisher="World Health Organization", year="2003",
        url="https://apps.who.int/medicinedocs/pdf/s4928e/s4928e.pdf", tier=3, read_status="lead", licence="-", note="Not readable here."),
    "PETERS-1994": dict(
        title="Sustainable harvest of non-timber plant resources in tropical moist forest: an ecological primer", publisher="Biodiversity Support Program", year="1994",
        url=None, tier=3, read_status="lead", licence="-", note="General method for harvest levels; not read."),
    "TICKTIN-2004": dict(
        title="The ecological implications of harvesting non-timber forest products", publisher="Journal of Applied Ecology 41:11-21", year="2004", url=None, tier=3,
        read_status="lead", licence="-", note="Review of 70 studies: the effect depends on the part harvested. Abstract only."),
}

# the part groups of Schedule-7 (क root and tuber, ख bark, ग leaf and stem, घ flower, ङ fruit and seed, च whole plant, छ gum and resin)
PART_METHOD: Dict[str, Tuple[str, str]] = {
    "क": ("destructive", "the plant is lifted to take the root or rhizome"),
    "ख": ("semi_destructive", "bark is taken from a living plant"),
    "ग": ("non_destructive", "leaves regrow"),
    "घ": ("non_destructive", "flowers regrow"),
    "ङ": ("non_destructive", "fruit and seed regrow"),
    "च": ("destructive", "the whole plant is taken"),
    "छ": ("semi_destructive", "gum or resin is tapped from a living plant"),
}

# growth form -> (plot min m2, plot max m2): the Nepal guideline's Table 3; the other sources are kept beside it
GROWTH_PLOT: Dict[str, Tuple[float, float]] = {"tree": (100, 500), "shrub": (25, 25), "climber": (25, 25), "herb": (4, 25), "fungus": (4, 25), "lichen": (4, 25)}
# growth form -> (min individuals to weigh, max): India's Working Plan Code para 71 (tree: at least 3 trees of different diameter classes; shrub: at
# least 5 plants; herb: 10 to 20). A climber is treated as a shrub, a fungus or lichen as a herb: not stated by the source.
GROWTH_SAMPLES: Dict[str, Tuple[int, Optional[int]]] = {"tree": (3, None), "shrub": (5, None), "climber": (5, None), "herb": (10, 20), "fungus": (10, 20), "lichen": (10, 20)}


def _v(species_key, field, source, locator, status, *, part=None, num=None, num2=None, text=None, unit=None, calendar=None, chosen=True, note=None) -> Dict[str, Any]:
    assert field in FIELDS and status in STATUSES and source in SOURCES, (species_key, field, source, status)
    return {"species_key": species_key, "field": field, "part_group": part, "value_num": num, "value_num2": num2, "value_text": text, "unit": unit, "calendar": calendar,
            "source_key": source, "locator": locator, "status": status, "chosen": chosen, "note": note}


# ── Annex 1 and 2 of the Nepal guideline: one value per card field ───────────────────────────────────────────────────────────────

def guideline_values(profiles: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """The values of the 35 Annex-2 cards (and the Annex-1 altitudes), from ``core.ntfp_methods.profiles()``. All documented, all chosen."""
    out: List[Dict[str, Any]] = []
    for p in profiles:
        k = p["species_key"]
        if p.get("altitude_min_m"):
            out.append(_v(k, "altitude_m", "DOF2069", "Annex 1", "documented", num=p["altitude_min_m"], num2=p.get("altitude_max_m"), unit="m"))
        if not p.get("has_method_card"):
            continue
        loc = "Annex 2"
        out.append(_v(k, "growth_class", "DOF2069", loc, "documented", text=p["growth_class"], note=f"life form as printed: {p.get('life_form_ne')}"))
        out.append(_v(k, "part_groups", "DOF2069", loc, "documented", text=",".join(p["part_groups"]), note=f"part as printed: {p.get('part_ne')}"))
        out.append(_v(k, "sampling_method", "DOF2069", loc, "documented", text=p["sampling_method"]))
        out.append(_v(k, "plot_area_sqm", "DOF2069", loc, "documented", num=p["plot_min_sqm"], num2=p["plot_max_sqm"], unit="m2"))
        if p.get("maturity_ne"):
            out.append(_v(k, "maturity", "DOF2069", loc, "documented", text=p["maturity_ne"]))
        if p.get("n_individuals_min"):
            out.append(_v(k, "n_individuals", "DOF2069", loc, "documented", num=p["n_individuals_min"], num2=p.get("n_individuals_max")))
        if p.get("harvest_fraction_pct"):
            out.append(_v(k, "sample_fraction_pct", "DOF2069", loc, "documented", num=p["harvest_fraction_pct"], unit="%",
                          note="the share of the part taken from a sampled plant to weigh (measurement), not a harvest limit"))
        if p.get("conversion_factor"):
            out.append(_v(k, "conversion_factor", "DOF2069", loc, "documented", num=p["conversion_factor"], note="dry weight / fresh weight"))
        if p.get("procedure_en"):
            out.append(_v(k, "procedure", "DOF2069", loc, "documented", text=p["procedure_en"], note="a summary of the card's procedure in English"))
    return out


def season_values() -> List[Dict[str, Any]]:
    """The 47 season rows of the Nepal guideline's Tables 5, 7, 10 and 13 and their altitudes (``core.ntfp_seasons``). The altitudes are checked against the
    PDF's text layer (documented); the season words were read from page images and are not reviewed (provisional)."""
    from . import ntfp_seasons as ns

    out: List[Dict[str, Any]] = []
    for r in ns.seasons():
        k = r["species_key"]
        a, b = r["ranges"][0]
        more = f"; second season {r['ranges'][1][0]}-{r['ranges'][1][1]}" if len(r["ranges"]) > 1 else ""
        out.append(_v(k, "season", "DOF2069", f"Table {r['table'][1:]} (printed p. {r['page']})", "provisional", part=r["part_group"], num=a, num2=b, text=r["season_ne"],
                      calendar="BS", note="read from the page image, awaiting the owner's review; months are Bikram Sambat numbers" + more))
        out.append(_v(k, "altitude_m", "DOF2069", f"Table {r['table'][1:]} (printed p. {r['page']})", "documented", num=r["altitude_min_m"], num2=r["altitude_max_m"], unit="m",
                      chosen=False, note="checked against the PDF text layer"))
    return out


# ── ANSAB: annual allowable harvest, seasons, rotation (read in full) ───────────────────────────────────────────────────────────

# (species_key, part group, min %, max %, source, locator, note)
_AAH: List[Tuple[str, str, float, Optional[float], str, str, Optional[str]]] = [
    # ANSAB 2010, Table 18
    ("aconitum heterophyllum", "क", 80, None, "ANSAB2010", "Table 18", "ANSAB writes Delphinium himalayai (atis); the part is not stated and is taken to be the root"),
    ("ophiocordyceps sinensis", "च", 90, None, "ANSAB2010", "Table 18", "ANSAB writes Cordyceps sinensis"),
    ("delphinium denudatum", "क", 75, None, "ANSAB2010", "Table 18", "the part is not stated and is taken to be the root"),
    ("neopicrorhiza scrophulariiflora", "क", 80, None, "ANSAB2010", "Table 18", "ANSAB writes Picrorhiza scrophulariflora (kutki)"),
    ("allium wallichii", "क", 75, None, "ANSAB2010", "Table 18", "ban lasun; the part is not stated"),
    ("nardostachys jatamansi", "क", 80, None, "ANSAB2010", "Table 18", "ANSAB writes Nardostachys grandiflora"),
    ("daphne bholua", "ख", 70, 80, "ANSAB2010", "Table 18", "lokta (spelt Danphe in the table); the bark is the part used"),
    ("girardinia diversifolia", "ख", 90, None, "ANSAB2010", "Table 18", "allo (spelt Girardiana in the table); the bark is the part used"),
    ("persea odoratissima", "ख", 50, None, "ANSAB2010", "Table 18", "kaulo, printed Persea sps.; taken as the species the guideline and Schedule-7 name"),
    ("cinnamomum tamala", "ग", 70, None, "ANSAB2010", "Table 18", "tejpat; the part is not stated and is taken to be the leaf (the 2022 toolkit gives the leaf 70 %, the bark 20 %)"),
    ("rhododendron anthopogon", "ग", 70, None, "ANSAB2010", "Table 18", "sunpati; the leaf is the part used"),
    ("taxus wallichiana", "ग", 50, 60, "ANSAB2010", "Table 18", "loth salla, printed Taxus baccata (the Himalayan yew); the leaf is the part used"),
    ("hippophae tibetana", "ङ", 75, 80, "ANSAB2010", "Table 18", "dalechuk; the fruit is the part used"),
    ("zanthoxylum armatum", "ङ", 80, None, "ANSAB2010", "Table 18", "timur; the fruit is the part used"),
    ("swertia chirayita", "च", 75, 80, "ANSAB2010", "Table 18", "chiraito"),
    ("piper longum", "ङ", 90, None, "ANSAB2010", "Table 18", "pipla; the fruit is the part used"),
    # ANSAB 2022, Annex 3 (AAH table, pp. 23-24); same species may repeat the 2010 value
    ("phyllanthus emblica", "ङ", 90, None, "ANSAB2022", "Annex 3, AAH table", "amala"),
    ("aconitum heterophyllum", "क", 80, None, "ANSAB2022", "Annex 3, AAH table", "ANSAB writes Delphinium himalayai (atis)"),
    ("terminalia bellirica", "ङ", 70, None, "ANSAB2022", "Annex 3, AAH table; Annex 5", "barro: harvest only 70 % of the fruit of a tree, leaving about 30 % to regenerate"),
    ("swertia chirayita", "च", 75, 80, "ANSAB2022", "Annex 3, AAH table", "chiraito"),
    ("diploknema butyracea", "ङ", 90, None, "ANSAB2022", "Annex 3, AAH table", "chiuri; ANSAB writes Bassia butyracea"),
    ("morchella conica", "च", 80, None, "ANSAB2022", "Annex 3, AAH table", "gucchi chyau"),
    ("tinospora sinensis", "ग", 90, None, "ANSAB2022", "Annex 3, AAH table", "guduchi (gurjo); ANSAB writes Tinospora cordifolia, the guideline and Schedule-7 write T. sinensis: identity to be confirmed"),
    ("terminalia chebula", "ङ", 70, None, "ANSAB2022", "Annex 3, AAH table; Annex 6", "harro"),
    ("nardostachys jatamansi", "क", 80, None, "ANSAB2022", "Annex 3, AAH table", "jatamansi"),
    ("asparagus racemosus", "क", 80, None, "ANSAB2022", "Annex 3, AAH table", "kurilo"),
    ("neopicrorhiza scrophulariiflora", "क", 80, None, "ANSAB2022", "Annex 3, AAH table", "kutki"),
    ("sapindus mukorossi", "ङ", 80, None, "ANSAB2022", "Annex 3, AAH table", "rittha"),
    ("paris polyphylla", "क", 75, None, "ANSAB2022", "Annex 3, AAH table", "satuwa"),
    ("valeriana jatamansi", "क", 80, None, "ANSAB2022", "Annex 3, AAH table", "sugandhawal"),
    ("cinnamomum tamala", "ख", 20, None, "ANSAB2022", "Annex 3, AAH table; Annex 4", "tejpat bark: 20 % of the bark of a tree every 3 years"),
    ("cinnamomum tamala", "ग", 70, None, "ANSAB2022", "Annex 3, AAH table", "tejpat leaf"),
    ("zanthoxylum armatum", "ङ", 80, None, "ANSAB2022", "Annex 3, AAH table", "timur"),
    # ANSAB 2010, worked example (Table 22 and 23)
    ("gaultheria fragrantissima", "ग", 75, None, "ANSAB2010", "Table 22 (wintergreen, Dolakha)", "wintergreen leaves; 25 % of the leaves are left undisturbed (Table 23)"),
]
AAH = _AAH

# harvest season (ANSAB 2022, Annex 3 table, pp. 20-21): (species_key, part group, month from, month to, text as printed). Gregorian months.
_SEASONS: List[Tuple[str, str, int, int, str, Optional[str]]] = [
    ("amomum subulatum", "ङ", 8, 11, "Mid August-November", "alainchi"), ("phyllanthus emblica", "ङ", 9, 11, "September-November", "amala"),
    ("aconitum heterophyllum", "क", 9, 11, "September-November", "atis, ANSAB writes Delphinium himalayai"), ("terminalia bellirica", "ङ", 11, 3, "November-March", "barro"),
    ("aegle marmelos", "ङ", 3, 6, "March-June", "bel"), ("ziziphus buddhensis", "ङ", 8, 8, "August", "bodhichitta"), ("acorus calamus", "क", 9, 2, "September-February", "bojho"),
    ("swertia chirayita", "च", 11, 12, "November-December", "chiraito"), ("diploknema butyracea", "ङ", 6, 8, "June-August", "chiuri, fruit or nut"),
    ("morchella conica", "च", 4, 7, "April-July", "gucchi chyau"), ("tinospora sinensis", "ग", 2, 4, "February-April", "guduchi, stem; identity to be confirmed (ANSAB: T. cordifolia)"),
    ("terminalia chebula", "ङ", 12, 3, "December-March", "harro"), ("nardostachys jatamansi", "क", 9, 12, "September-December", "jatamansi"),
    ("persea odoratissima", "ख", 1, 2, "January-February", "kaulo, bark"), ("asparagus racemosus", "क", 9, 11, "September-November", "kurilo"),
    ("neopicrorhiza scrophulariiflora", "क", 9, 12, "September-December", "kutki"), ("choerospondias axillaris", "ङ", 9, 1, "September-January", "lapsi"),
    ("rheum australe", "क", 11, 5, "November-May", "padamchal: rhizome, petiole and leaf"), ("bergenia ciliata", "क", 10, 11, "October-November", "pasanbed, underground stem"),
    ("sapindus mukorossi", "ङ", 10, 12, "October-December", "rittha, fruit or nut"), ("elaeocarpus sphaericus", "ङ", 12, 2, "December-February", "rudraksha, fruit or seed"),
    ("paris polyphylla", "क", 9, 11, "September-November", "satuwa"), ("rauvolfia serpentina", "क", 11, 3, "November-March", "serpagandha, root"),
    ("polygonatum cirrhifolium", "क", 10, 12, "October-December", "setakchini (khiraula); ANSAB prints Polygonatum chhirifolium"),
    ("lindera neesiana", "ङ", 7, 9, "July-September", "siltimur"), ("valeriana jatamansi", "क", 9, 11, "September-November", "sugandhawal"),
    ("cinnamomum tamala", "ख", 10, 5, "October-May", "tejpat bark"), ("cinnamomum tamala", "ग", 9, 5, "September-May", "tejpat leaf"),
    ("zanthoxylum armatum", "ङ", 9, 12, "September-December", "timur"),
    ("gaultheria fragrantissima", "ग", 1, 12, "Whole year", "wintergreen leaves (ANSAB 2010, Table 23)"),
]


def ansab_values() -> List[Dict[str, Any]]:
    """Annual allowable harvest, rotation and harvest seasons from the two ANSAB toolkits. Documented, but not ``chosen`` over the Nepal guideline where both exist."""
    out: List[Dict[str, Any]] = []
    for key, part, lo, hi, src, loc, note in _AAH:
        status = "provisional" if key == "tinospora sinensis" else "documented"
        out.append(_v(key, "aah_pct", src, loc, status, part=part, num=lo, num2=hi, unit="%", note=note, chosen=(src == "ANSAB2022" or key in _ONLY_2010)))
    out.append(_v("cinnamomum tamala", "rotation_years", "ANSAB2022", "Annex 3; Annex 4", "documented", part="ख", num=3, unit="years",
                  note="tejpat bark regenerates in about 3 years, so the rotation without destroying the tree is 3 years; harvest only 20 % of the bark of a tree in that interval"))
    out.append(_v("gaultheria fragrantissima", "rotation_years", "ANSAB2010", "Table 23 (wintergreen)", "documented", part="ग", num=0.5, num2=1, unit="years",
                  note="optimal rotational interval 6 months to 1 year; leaves of twigs of 5-6 year old plants"))
    for key, part, a, b, text, note in _SEASONS:
        status = "provisional" if key == "tinospora sinensis" else "documented"
        out.append(_v(key, "season", "ANSAB2022", "Annex 3, season table (pp. 20-21)", status, part=part, num=a, num2=b, text=text, calendar="AD", note=note, chosen=False))
    return out


# species whose only AAH source is ANSAB 2010: that value is the chosen one
_ONLY_2010 = {k for k, *_ in _AAH if k not in {x[0] for x in _AAH if x[4] == "ANSAB2022"}}


# ── growth-form defaults and part-based method: the rules the provisional cards use ───────────────────────────────────────────

def form_values() -> List[Dict[str, Any]]:
    """Plot size and sample counts by growth form (pseudo-species ``form:<class>``), IVI components, and the method by part (``part:<group>``)."""
    out: List[Dict[str, Any]] = []
    for g, (lo, hi) in GROWTH_PLOT.items():
        out.append(_v(f"form:{g}", "plot_area_sqm", "DOF2069", "Table 3", "documented" if g in ("tree", "shrub", "climber", "herb") else "derived",
                      num=lo, num2=hi if hi != lo else None, unit="m2", note=None if g != "fungus" and g != "lichen" else "not sized by the guideline: the herb range is used"))
    out += [
        _v("form:herb", "plot_area_sqm", "ANSAB2010", "Table 7", "documented", num=4, num2=25, unit="m2", chosen=False, note="4 m2; 25 m2 if the herbs are highly scattered"),
        _v("form:shrub", "plot_area_sqm", "ANSAB2010", "Table 7", "documented", num=100, unit="m2", chosen=False, note="10 m x 10 m (the Nepal guideline gives 25 m2)"),
        _v("form:tree", "plot_area_sqm", "ANSAB2010", "Table 7", "documented", num=4, num2=500, unit="m2", chosen=False, note="500 m2 for dbh > 30 cm, 100 m2 for 10-30 cm, 4 m2 for < 10 cm"),
        _v("form:herb", "plot_area_sqm", "FSI-NFI", "Form No. 8", "documented", num=1, unit="m2", chosen=False, note="1 m x 1 m herb subplot of the national forest inventory"),
        _v("form:shrub", "plot_area_sqm", "FSI-NFI", "Form No. 8", "documented", num=9, unit="m2", chosen=False, note="3 m x 3 m shrub and regeneration subplot of the national forest inventory"),
        _v("form:tree", "plot_area_sqm", "FSI-NFI", "Sample point layout", "documented", num=1000, unit="m2", chosen=False, note="0.1 ha square tree plot of the national forest inventory"),
    ]
    for g, (lo, hi) in GROWTH_SAMPLES.items():
        out.append(_v(f"form:{g}", "n_individuals", "NWPC2014", "Para 71", "documented" if g in ("tree", "shrub", "herb") else "derived", num=lo, num2=hi,
                      note={"tree": "at least three trees of different diameter classes, two consecutive seasons; fresh and dry weight of each",
                            "shrub": "the useful part of at least five plants; fresh and dry weight", "herb": "at least 10 to 20 individuals; fresh and dry biomass of the useful part"}.get(g, "treated like the nearest growth form")))
    out += [
        _v("form:tree", "ivi_components", "NWPC2014", "Para 72", "documented", num=3, note="relative dominance (basal area) + relative density + relative frequency; maximum 300"),
        _v("form:shrub", "ivi_components", "NWPC2014", "Para 72", "documented", num=2, note="for shrubs, herbs, saplings and regeneration the IVI is relative frequency + relative density; maximum 200"),
        _v("form:herb", "ivi_components", "NWPC2014", "Para 72", "documented", num=2, note="relative frequency + relative density; maximum 200"),
    ]
    for g, (method, why) in PART_METHOD.items():
        out.append(_v(f"part:{g}", "sampling_method", "RULE", "part-based default", "derived", text=method,
                      note=f"{why}; consistent with the Annex-2 cards (DoF 2069) and the principle that flowers, fruits and leaves regenerate more easily than roots and bark (FAO-GACP 2010, section 4)"))
    return out

# ── choosing one value per fact ──────────────────────────────────────────────────────────────────────────────────────────────────

_YEAR_AD = {"DOF2069": 2012, "S7-2079": 2022, "ANSAB2010": 2010, "ANSAB2022": 2022, "NWPC2014": 2014, "FSI-NFI": 2012, "FAO-GACP2010": 2010, "ICFRE-2020": 2020, "MP-ESIP-2022": 2021, "RULE": 2026, "MASTER": 2026}
_STATUS_RANK = {"expert_confirmed": 0, "documented": 1, "derived": 2, "provisional": 3}


# Indian harvest rules for species that also grow in Nepal: (species, field, source, locator, part, num, num2, unit, quote). The quote is a sentence of the source
# (whitespace-normalised) that tests look up in the PDF text. ``aah_pct`` is the share of the crop that may be taken, i.e. 100 minus the share the source leaves.
_INDIA: List[Tuple[str, str, str, str, Optional[str], float, Optional[float], str, str]] = [
    ("phyllanthus emblica", "aah_pct", "ICFRE-2020", "Aonla, Sustainable harvesting", "ङ", 80, None, "%", "20% fruits are left for regeneration"),
    ("terminalia bellirica", "aah_pct", "ICFRE-2020", "Baheda, Sustainable harvesting", "ङ", 80, 95, "%", "5-10% fruits should be left for regeneration"),
    ("terminalia bellirica", "aah_pct", "MP-ESIP-2022", "4.1.5 Terminalia bellerica, extent of harvesting", "ङ", 60, 75, "%", "Only 60 – 75% of the fruits should be harvested"),
    ("terminalia chebula", "aah_pct", "MP-ESIP-2022", "4.1.6 Terminalia chebula, extent of harvesting", "ङ", 60, 75, "%", "Only 60–75% of the fruits should be harvested"),
    ("aegle marmelos", "aah_pct", "MP-ESIP-2022", "4.1.1 Aegle marmelos, extent of harvesting", "ङ", 60, 75, "%", "Only 60–75% of the fruits should be harvested"),
    ("asparagus racemosus", "aah_pct", "MP-ESIP-2022", "4.3.1 Asparagus racemosus, extent of harvesting", "क", 80, None, "%", "Harvesting of tubers should be limited for 80% of the total number of tubers"),
    ("woodfordia fruticosa", "aah_pct", "ICFRE-2020", "Dhawai, Do's and Don'ts", "घ", 80, None, "%", "About 20% flowers should be left intact"),
    ("oroxylum indicum", "rotation_years", "ICFRE-2020", "Sheonak, Sustainable harvesting practices", "ख", 1.5, None, "years", "Sustainable bark harvesting can be done after every 18 months"),
    ("bauhinia variegata", "rotation_years", "ICFRE-2020", "Kachnar, Sustainable harvesting practices", "ख", 1.5, None, "years", "Sustainable bark harvesting can be done after every 18 months"),
    ("symplocos racemosa", "rotation_years", "ICFRE-2020", "Lodh, Sustainable harvesting practices", "ख", 2, None, "years", "Sustainable bark harvesting can be done after every 24 months"),
    ("aegle marmelos", "rotation_years", "MP-ESIP-2022", "4.1.1 Aegle marmelos, extent of harvesting (bark)", "ख", 2, 3, "years", "The tree should be given rest for a period of 2-3 years"),
]


def india_cited() -> List[Tuple[str, str, str, str, Optional[str], float, Optional[float], str, str]]:
    return list(_INDIA)


def india_values() -> List[Dict[str, Any]]:
    return [_v(k, f, src, loc, "documented", part=part, num=a, num2=b, unit=u, note="Indian practice, not Nepali: " + quote)
            for k, f, src, loc, part, a, b, u, quote in _INDIA]


def finalize_chosen(values: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Mark exactly one value ``chosen`` for every (species, field, part). The order: a better status first (expert-confirmed, documented, derived,
    provisional), then the more authoritative source tier, then the newer source. The other values stay as the conflicting evidence."""
    groups: Dict[Tuple[str, str, Optional[str]], List[Dict[str, Any]]] = {}
    for v in values:
        groups.setdefault((v["species_key"], v["field"], v["part_group"]), []).append(v)
    for rows in groups.values():
        best = min(rows, key=lambda v: (_STATUS_RANK[v["status"]], SOURCES[v["source_key"]]["tier"], -_YEAR_AD.get(v["source_key"], 0)))
        for v in rows:
            v["chosen"] = v is best
    return values


def all_documented_values(profiles: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return finalize_chosen(guideline_values(profiles) + season_values() + ansab_values() + form_values() + india_values())
