"""How to inventory a non-timber forest product: the method profile of each species (NTFP inventory, phase 1).

Source: गैरकाष्ठ वन पैदावारको स्रोत सर्वेक्षण मार्गदर्शन २०६९ (Department of Forests, Resource Survey Guideline for NTFPs), checked against the
PDF's text layer by ``tests/test_ntfp_methods.py``:

* Annex 1 -- the 30 NTFPs the Government of Nepal lists as priority species: scientific and Nepali name, altitude range, parts used, uses.
* Annex 2 -- the method card of each of 35 species (one card names five species): life form, part used, destructive or not, sample plot size, the sign that a plant is
  mature enough to harvest, how many individuals to lift and what fraction to take, the conversion factor (dry / fresh weight).
* Tables 3 and 4 -- plot size and sampling intensity by growth form and forest size (``GROWTH_FORMS``, ``intensity_pct``).

The profile is keyed like the regulation list (``ntfp_schedule7``): the normalised Latin name, genus only for a ``spp.`` entry, so a
species joins its Schedule-7 price lines with ``designated_entries``. The guideline gives no Latin name for three Annex-2
species. Two are named by Schedule-7 itself (ढटेलो = Prinsepia utilis, ङ 39; विषफेज = Polypodiodes amoena, क 66) and are filled in from it; माइकोपिला
is not found anywhere, and is keyed ``np:माइकोपिला`` until someone supplies the Latin name.

Not here yet: the harvest season of each species (Tables 5, 7, 9, 10, 11 of the guideline).

Seed only: ``alembic/versions/132_ntfp_method_profile.py`` loads these rows once; from then on the table ``ntfp_method_profile`` is the
source, as for ``ntfp_regulation``.
"""
from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from .ntfp_schedule7 import designated_entries
from .species_synonyms import canonical_key, canonical_name

SOURCE = "गैरकाष्ठ वन पैदावारको स्रोत सर्वेक्षण मार्गदर्शन २०६९"
SOURCE_EN = "NTFP Resource Survey Guideline 2069 (Department of Forests)"

# ── growth forms: Table 3 (plot size, m2) and Table 4 (sampling intensity, % of the forest area) ───────────────────────────────

TREE, SHRUB, CLIMBER, HERB, FUNGUS, LICHEN = "tree", "shrub", "climber", "herb", "fungus", "lichen"

#: growth class -> (Nepali, plot area min m2, plot area max m2). Table 3: trees DBH > 30 cm 100-500; shrubs, climbers and creepers (1-3 m
#: high) 25; herbs under 1 m 4-25. A growth class the guideline does not size (fungus, lichen) takes the herb range; a species card
#: overrides it.
GROWTH_FORMS: Dict[str, Tuple[str, float, float]] = {
    TREE: ("रूख", 100.0, 500.0),
    SHRUB: ("झाडी", 25.0, 25.0),
    CLIMBER: ("लहरा", 25.0, 25.0),
    HERB: ("झार", 4.0, 25.0),
    FUNGUS: ("च्याउ", 4.0, 25.0),
    LICHEN: ("भ्याउ", 4.0, 25.0),
}

#: Table 4: forest area band -> growth class (tree, shrub, herb) -> (min %, max %). Climbers follow the shrubs; fungus and lichen the herbs.
INTENSITY_PCT: Dict[str, Dict[str, Tuple[float, float]]] = {
    "lt100": {TREE: (1.0, 1.0), SHRUB: (0.5, 0.5), HERB: (0.05, 0.1)},
    "100_500": {TREE: (0.5, 0.5), SHRUB: (0.5, 0.5), HERB: (0.05, 0.05)},
    "gt500": {TREE: (0.1, 0.5), SHRUB: (0.1, 0.1), HERB: (0.01, 0.01)},
}
_INTENSITY_CLASS = {TREE: TREE, SHRUB: SHRUB, CLIMBER: SHRUB, HERB: HERB, FUNGUS: HERB, LICHEN: HERB}


def below_guideline(growth_class: str, forest_area_ha: float, pct: float) -> bool:
    """True when `pct` is under the lowest intensity Table 4 allows for this growth class and forest size (a plan that departs from the guideline says so)."""
    return pct < intensity_pct(growth_class, forest_area_ha)[0] - 1e-9


def area_band(forest_area_ha: float) -> str:
    """The Table-4 row for a forest: under 100 ha, 100 to 500 ha (inclusive), over 500 ha."""
    return "lt100" if forest_area_ha < 100 else ("100_500" if forest_area_ha <= 500 else "gt500")


def intensity_pct(growth_class: str, forest_area_ha: float) -> Tuple[float, float]:
    """The guideline's sampling intensity (min %, max %) for a growth class in a forest of this size."""
    return INTENSITY_PCT[area_band(forest_area_ha)][_INTENSITY_CLASS[growth_class]]


# ── the profile rows ───────────────────────────────────────────────────────────────────────────────────────────────────────────

D, SD, ND = "destructive", "semi_destructive", "non_destructive"

# Annex 1: (serial, scientific name as printed, Nepali name, altitude min m, max m, parts used, main uses)
ANNEX1: List[Tuple[int, str, str, int, int, str, str]] = [
    (1, "Aconitum heterophyllum", "अतिस", 2400, 4100, "जरा, गानो", "औषधी"),
    (2, "Aconitum spicatum", "विष", 3300, 4300, "जरा, फूल, पात", "औषधी"),
    (3, "Acorus calamus", "बोझो", 200, 2300, "जरा", "सुगन्धित तेल, औषधी"),
    (4, "Asparagus racemosus", "कुरिलो, सतावरी", 150, 2100, "जरा, टुसा", "खाना, औषधी"),
    (5, "Azadirachta indica", "नीम", 100, 900, "सम्पूर्ण भाग", "औषधी"),
    (6, "Bergenia ciliata", "पाखनवेद", 1600, 3600, "प्रकन्द", "औषधी"),
    (7, "Cinnamomum glaucescens", "सुगन्धकोकिला", 2000, 2500, "फल", "औषधी, सुगन्धित तेल"),
    (8, "Cinnamomum tamala", "तेजपात", 450, 2100, "बोक्रा", "औषधी, मसला"),
    (9, "Ophiocordyceps sinensis", "यार्सागुम्बा", 4200, 5000, "पूरै ढुसी र लार्भा", "औषधी, ताकत"),
    (10, "Dactylorhiza hatagirea", "पाँचऔंले", 2800, 4000, "गानो", "औषधी"),
    (11, "Dioscorea deltoidea", "भ्याकुर", 450, 3100, "जरा, फल", "खाना"),
    (12, "Gaultheria fragrantissima", "धसिंग्रे, पटपटे", 1200, 2700, "पात", "सुगन्धित तेल, औषधी"),
    (13, "Juglans regia", "ओखर", 1200, 3000, "फल, बोक्रा", "खाना, रङ, औषधी"),
    (14, "Morchella conica", "गुच्छी च्याउ", 2000, 3500, "पूरै बिरुवा", "खाना, टनिक"),
    (15, "Nardostachys grandiflora", "जटामसी", 3600, 5000, "प्रकन्द", "औषधी, सुगन्धित तेल"),
    (16, "Neopicrorhiza scrophulariiflora", "कुटकी", 3600, 4800, "जरा, प्रकन्द", "औषधी"),
    (17, "Lichens", "भ्याउ", 0, 0, "पूरै बिरुवा", "खाना, औषधी"),  # the guideline gives no altitude; 0/0 is stored as null
    (18, "Phyllanthus emblica", "अमला", 150, 1400, "फल", "औषधी, खान"),
    (19, "Piper longum", "पिप्ला", 200, 800, "फल, डाँठ", "औषधी, मसला"),
    (20, "Podophyllum hexandrum", "लघुपत्र", 2400, 4500, "जरा, प्रकन्द", "औषधी"),
    (21, "Rauvolfia serpentina", "सर्पगन्धा", 100, 1200, "जरा", "औषधी"),
    (22, "Rheum australe", "पदमचाल", 3000, 4200, "प्रकन्द, डाँठ", "खाना, औषधी"),
    (23, "Rubia manjith", "मजिठो", 1200, 2100, "डाँठ, जरा", "रङ, औषधी"),
    (24, "Sapindus mukorossi", "रिठ्ठा", 1000, 1400, "फल, बोक्रा, बीउ", "औषधी, डिटरजेन्ट"),
    (25, "Swertia chirayita", "चिराइतो, तिते", 1500, 3000, "पूरै बिरुवा", "औषधी"),
    (26, "Tagetes minuta", "जङ्गली सयपत्री", 1200, 2500, "पूरै बिरुवा", "औषधी, सुगन्धित तेल"),
    (27, "Taxus wallichiana", "लौठ सल्ला", 2400, 3400, "पात", "औषधी"),
    (28, "Tinospora sinensis", "गुर्जो", 300, 1500, "लहरा", "औषधी, जडीबुटी चिया"),
    (29, "Valeriana jatamansii", "सुगन्धवाल", 1500, 3600, "जरा, प्रकन्द", "औषधी, सुगन्धित तेल, धूप"),
    (30, "Zanthoxylum armatum", "टिमुर", 1100, 2500, "फल", "मसला, सुगन्धित तेल, औषधी"),
]

# Annex 2 method cards. ``parts`` are the Schedule-7 group codes (क root and tuber, ख bark, ग leaf and stem, घ flower, ङ fruit and seed, च whole
# plant) so a card ties to the regulation's price lines.
#   key fields: scientific name (None when the guideline gives only a Nepali name), Nepali name as printed, life form as printed,
#   growth class, part used as printed, parts, method, plot m2 min, max, maturity sign, individuals min, max, fraction taken %, CF, procedure
Card = Tuple[Optional[str], str, str, str, str, Tuple[str, ...], str, float, float, str, Optional[int], Optional[int], Optional[float], Optional[float], str]
CARDS: List[Card] = [
    ("Neopicrorhiza scrophulariiflora", "कुटकी", "भुइँझार", HERB, "प्रकन्द (जमीनमुनिको परिवर्तित काण्ड)", ("क",), D, 4, 4,
     "रूख, बुढी औंला आकारको प्रकन्द", None, None, None, 0.2891,
     "Count small and large plants in the plot; dig all rhizomes of 2-3 plots and weigh fresh and dry; scale by the plant count."),
    ("Aconitum spp.", "अतिस, विष, बिसमा", "झार", HERB, "प्रकन्द", ("क",), D, 4, 25,
     "फूल फुलेर फल र बीउ लागेपछि", None, None, None, None,
     "Count small and large plants; lift the rhizomes of mature plants from the management area; weigh fresh and dry."),
    ("Nardostachys grandiflora", "जटामसी", "भुइँझार", HERB, "जमीनमुनिको काण्ड", ("क",), D, 25, 25,
     "जमीनमुनिको काण्ड सुगन्धित भएको, जरा खैरो भएको", 9, 9, None, 0.2844,
     "Count small and large plants; lift the rhizomes of at least 9 mature plants; mean fresh and dry weight; yield per ha."),
    ("Acorus calamus", "बोझो", "झार", HERB, "जमीनमुनिको काण्ड वा प्रकन्द", ("क",), D, 4, 25,
     "फूल फुलेर फल र बीउ लागेपछि", 9, 9, None, None,
     "Count small and large plants; lift the rhizomes of at least 9 mature plants. Found in wet areas."),
    (None, "माइकोपिला", "झार", HERB, "बीउ", ("ङ",), ND, 4, 4,
     "फूल फुलेर पहिलो भएपछि", 9, 9, None, 0.35,
     "Count small and large plants; collect the seed of at least 9 mature plants; mean dry weight."),
    ("Ophiocordyceps sinensis", "यार्सागुम्बा", "च्याउ जाति", FUNGUS, "पूरै भाग", ("च",), D, 100, 100,
     "जेठमा कीराको लार्भा मरेर माथिको कालो टुसो देखिएपछि", 5, 7, None, None,
     "Count every specimen in the plot; mean fresh and dry weight of 5-7 specimens."),
    ("Paris polyphylla", "सतुवा", "झार", HERB, "जमीनमुनिको परिवर्तित काण्ड वा प्रकन्द", ("क",), D, 25, 25,
     "जमीनमुनिको काण्ड सुगन्धित भएको, जरा खैरो भएको", None, None, None, None,
     "Count small and large plants; in 3-5 plots lift 2-3 mature plants each; mean fresh and dry rhizome weight."),
    ("Valeriana jatamansii", "सुगन्धवाल", "झार", HERB, "प्रकन्द, जरा", ("क",), D, 4, 25,
     "पात पहेंलो भएपछि", 9, 9, None, None,
     "Count small and large plants; lift the rhizomes of at least 9 mature plants; mean fresh and dry weight."),
    ("Edgeworthia gardneri", "अर्गेली", "झाडी", SHRUB, "बोक्रा", ("ख",), D, 25, 25,
     "५ वर्ष पुरानो बिरुवा", 10, 10, None, 0.6473,
     "Count large, medium and small shrubs and the density; collect the bark of 10 mature shrubs; mean fresh and dry weight."),
    ("Girardinia diversifolia", "अल्लो", "झार", HERB, "बोक्रा", ("ख",), D, 25, 25,
     "फूल फुलेपछि", 15, 15, None, None,
     "Count large, medium and small plants; collect the bark of 15 mature plants; mean fresh and dry weight."),
    ("Daphne bholua", "लोक्ता", "झाडी", SHRUB, "बोक्रा", ("ख",), D, 25, 25,
     "७ वर्ष पुरानो बिरुवा", 10, 10, None, 0.6142,
     "Count large, medium and small shrubs and the density; collect the bark of 10 mature shrubs; mean fresh and dry weight."),
    ("Persea odoratissima", "काउलो", "रूख", TREE, "बोक्रा", ("ख",), SD, 100, 300,
     "१० वर्ष पुरानो रूख", 2, 3, 33.0, None,
     "Count all trees in the plot; take a third of the bark of 2-3 mature trees; mean fresh and dry weight."),
    ("Asparagus racemosus", "कुरिलो", "काँडादार झाडी", SHRUB, "जमीनमुनिको परिवर्तित जरा", ("क",), D, 25, 25,
     "जरा १० सेमी जत्रो भएमा", 3, 5, None, None,
     "Count small and large plants; lift all roots of 3-5 mature plants; mean fresh and dry weight per plant."),
    ("Rheum australe", "पदमचाल", "ठूलो एक वर्षीय झार", HERB, "जमीनमुनिको काण्ड", ("क",), D, 25, 25,
     "डाँठ रातो भएपछि र रातो फूल फुलेपछि", 3, 3, None, None,
     "Count small and large plants; lift the rhizomes of at least 3 mature plants; mean fresh weight."),
    ("Berberis spp.", "चुत्रो", "काँडादार झाडी", SHRUB, "बोक्रा", ("ख",), SD, 25, 25,
     "बोक्रा अलि खैरो भएको", 2, 3, 33.0, None,
     "Count small and large shrubs; take a third of the bark of 2-3 mature shrubs; mean fresh and dry weight."),
    ("Rubia manjith", "मजिठो", "लहरे झाडी", CLIMBER, "जरा, डाँठ", ("क", "ग"), D, 25, 25,
     "फूल फुलेर फल लागेपछि", 5, 5, None, None,
     "Count small and large plants; collect the stem and roots of 5 mature plants; mean fresh and dry weight."),
    ("Hippophae salicifolia", "डालेचुक", "सानो रूख", TREE, "फल", ("ङ",), ND, 100, 300,
     "फल पहेंलो भएपछि", 3, 3, 50.0, None,
     "Count the trees in the plot; take 50 % of the fruit of at least 3 trees; mean fresh weight of fruit per tree."),
    ("Hippophae tibetana", "भुईंचुक", "झाडी", SHRUB, "फल", ("ङ",), ND, 25, 25,
     "फल पहेंलो वा सुन्तला रंगको भएपछि", 5, 5, 75.0, None,
     "Count the shrubs in the plot; take 75 % of the fruit of at least 5 shrubs; mean fresh weight per shrub."),
    ("Prinsepia utilis", "ढटेलो", "झाडी", SHRUB, "बीउ", ("ङ",), ND, 25, 25,
     "फल लागेको झाडी", 3, 3, 90.0, None,
     "Count the shrubs in the plot; take 90 % of the fruit of at least 3 shrubs; mean fresh and dry weight."),
    ("Zanthoxylum armatum", "टिमुर", "झाडी", SHRUB, "फल", ("ङ",), ND, 25, 25,
     "फल पाकेर कालो भएपछि", 3, 3, 90.0, None,
     "Count the shrubs in the plot; take 90 % of the fruit of at least 3 shrubs; mean fresh weight per shrub."),
    ("Gaultheria fragrantissima", "धसिंग्रे", "झाडी", SHRUB, "पात", ("ग",), ND, 25, 25,
     "१ वा १.५ मीटर अग्लो झाडीबाट", 9, 9, 50.0, None,
     "Count the shrubs; count the tillers of large, medium and small shrubs; take 50 % of the leaves of 9 tillers; mean fresh weight."),
    ("Juniperus indica", "धूपी", "झाडी अथवा सानो रूख", SHRUB, "पात, फल", ("ग", "ङ"), ND, 25, 100,
     "ठूलो झाडी, फल गाढा निलो वा कालो भएपछि", None, None, 33.0, None,
     "Count the shrubs or trees; take 33 % of the leaves of a mature shrub; mean fresh and dry weight."),
    ("Rhododendron anthopogon", "सुनपाती", "झाडी", SHRUB, "पात", ("ग",), ND, 25, 25,
     "फूल फुलेर फल लागेपछि", None, None, 40.0, None,
     "Count the shrubs; take 40 % of the leaves of a mature shrub; mean fresh and dry weight."),
    ("Taxus wallichiana", "लौठ सल्ला", "रूख", TREE, "पात", ("ग",), ND, 100, 500,
     "२० वर्ष पुरानो रूख", 2, 2, 25.0, None,
     "Count the large and small trees; take 25 % of the leaves of two trees; mean fresh and dry weight."),
    ("Terminalia chebula", "हर्रो", "रूख", TREE, "फल", ("ङ",), ND, 100, 500,
     "फल फलेको रूख", 2, 2, 90.0, None,
     "Count the large and small trees; take 90 % of the fruit of two trees; mean fresh and dry weight."),
    ("Terminalia bellirica", "बर्रो", "रूख", TREE, "फल", ("ङ",), ND, 100, 500,
     "फल फलेको रूख", 2, 2, 90.0, None,
     "Count the large and small trees; take 90 % of the fruit of two trees; mean fresh and dry weight."),
    ("Phyllanthus emblica", "अमला", "रूख", TREE, "फल", ("ङ",), ND, 100, 500,
     "फल फलेको रूख", 2, 2, 90.0, None,
     "Count the large and small trees; take 90 % of the fruit of two trees; mean fresh and dry weight."),
    ("Sapindus mukorossi", "रिठ्ठा", "रूख", TREE, "फल", ("ङ",), ND, 100, 500,
     "फल फलेको रूख", 2, 2, 90.0, None,
     "Count the large and small trees; take 90 % of the fruit of two trees; mean fresh and dry weight."),
    ("Diploknema butyracea", "चिउरी", "रूख", TREE, "फल", ("ङ",), ND, 100, 500,
     "फल फलेको रूख", 2, 2, 90.0, None,
     "Count the large and small trees; take 90 % of the fruit of two trees; mean fresh and dry weight."),
    ("Cinnamomum tamala", "तेजपात", "रूख", TREE, "पात", ("ग",), ND, 100, 500,
     "पात सुक्न लागेपछि", 2, 2, 33.0, None,
     "Count the large and small trees; take 33 % of the leaves of two trees; mean fresh and dry weight."),
    ("Bombax ceiba", "सिमल", "रूख", TREE, "फूल", ("घ",), ND, 100, 500,
     "फूल फुलेको रूख", 2, 2, 50.0, None,
     "Count the large and small trees; take 50 % of the flowers of two trees (or 10-15 flowers and estimate the rest); mean fresh and dry weight."),
    ("Polypodiodes amoena", "बिषफेज", "पुरानो रूखमा उम्रने उन्यु", FUNGUS, "जरा र प्रकन्द", ("क",), SD, 100, 300,
     "उन्युको पात सुक्न लागेपछि", 2, 2, 50.0, None,
     "Count the trees carrying the fern; take 50 % of it from two trees; mean fresh and dry weight."),
    ("Fritillaria cirrhosa", "काकोली, वन लसुन", "झार", HERB, "जमीनमुनिको पोटी", ("क",), D, 25, 25,
     "फूल फुलेर फल र बीउ लागेपछि", 9, 9, None, None,
     "Count small and large plants; lift the bulbs of at least 9 mature plants; mean fresh and dry weight."),
    ("Morchella conica", "गुच्छी च्याउ", "च्याउ जाति", FUNGUS, "पूरै भाग", ("च",), D, 4, 25,
     "वर्षा शुरु हुनु भन्दा पहिले माथिको भाग खैरो भएपछि", 7, 9, None, None,
     "Count the mushrooms in the plot; mean fresh and dry weight of 7-9 ripe ones."),
    ("Swertia chirayita", "चिराइतो", "बिरुवा", HERB, "पूरै बिरुवा", ("च",), D, 4, 25,
     "बिरुवा खैरो भएपछि, पात सुक्न लागेपछि", 3, 3, None, 0.5764,
     "Count small and large plants; in 3-5 plots uproot 3 mature plants each; mean fresh and dry weight."),
]


def regulation_name(scientific: Optional[str]) -> Optional[str]:
    """The canonical Latin name to give ``designated_entries``, or None when Schedule-7 does not list the species (Edgeworthia gardneri,
    Daphne bholua, Girardinia diversifolia and Tagetes minuta carry no price rate; the lichen line is not matched by name)."""
    name = canonical_name(scientific or "")
    return name if name and designated_entries(name) else None


def species_key(scientific: Optional[str], nepali: str) -> str:
    """The profile's identity: the normalised CANONICAL Latin name (``core/species_synonyms``; genus only for a ``spp.`` entry), or
    ``np:<nepali>`` when the species has no Latin name."""
    key = canonical_key(scientific or "")
    return key if key else f"np:{nepali.split(',')[0].strip()}"


def _names(sci: Optional[str]) -> dict:
    """``scientific_name`` is the canonical name; the guideline's own spelling, when different, is kept as an alias."""
    if not sci:
        return {"scientific_name": None, "aliases": []}
    canon = canonical_name(sci)
    return {"scientific_name": canon, "aliases": [sci] if canon != sci else []}


def profiles() -> List[dict]:
    """The seed rows, one per species, from Annex 1 merged with the Annex 2 cards (a species on both has both)."""
    rows: Dict[str, dict] = {}
    for serial, sci, nepali, lo, hi, parts, uses in ANNEX1:
        key = species_key(sci, nepali)
        rows[key] = {
            "species_key": key, **_names(sci), "nepali_name": nepali, "priority_serial": serial,
            "altitude_min_m": lo or None, "altitude_max_m": hi or None, "parts_used_ne": parts, "uses_ne": uses,
            "has_method_card": False, "part_groups": [], "regulation_name": regulation_name(sci),
        }
    for sci, nepali, life_ne, growth, part_ne, groups, method, pmin, pmax, maturity, nmin, nmax, pct, cf, proc in CARDS:
        key = species_key(sci, nepali)
        row = rows.setdefault(key, {
            "species_key": key, **_names(sci), "nepali_name": nepali, "priority_serial": None,
            "altitude_min_m": None, "altitude_max_m": None, "parts_used_ne": None, "uses_ne": None,
            "regulation_name": regulation_name(sci),
        })
        row.update({
            "life_form_ne": life_ne, "growth_class": growth, "part_ne": part_ne, "part_groups": list(groups), "sampling_method": method,
            "plot_min_sqm": pmin, "plot_max_sqm": pmax, "maturity_ne": maturity, "n_individuals_min": nmin, "n_individuals_max": nmax,
            "harvest_fraction_pct": pct, "conversion_factor": cf, "procedure_en": proc, "has_method_card": True,
        })
    return list(rows.values())
