"""DRAFT harvest seasons of NTFP species, from the guideline's season tables (NOT SEEDED, NOT USED: awaiting the owner's review).

Source: गैरकाष्ठ वन पैदावारको स्रोत सर्वेक्षण मार्गदर्शन २०६९: Table 5 (roots, tubers and rhizomes, printed pages 19-20), Table 7 (leaf, p. 24),
Table 10 (bark, p. 28) and Table 13 (fruit, flower, seed and fluff, pp. 31-32). 47 rows (the two Hippophae species share a row of the printed table).

What is machine-checked (``tests/test_ntfp_seasons.py``): every altitude range against the PDF's text layer, every Latin name against its text, and
that every season string parses to months. What is NOT: the season words themselves. They are Nepali month names read from the page images (the
text layer is Preeti-encoded and its month words cannot be decoded reliably), so every row carries ``reviewed = False`` until a person confirms it.

Months are Bikram Sambat numbers, 1 = बैशाख ... 12 = चैत. A range that runs past चैत wraps (``माघ-वैशाख`` is 10 to 1).
"""
from __future__ import annotations

import re
from typing import Dict, List, Tuple

REVIEWED = False  # flips to True only when the owner returns the review sheet; the import step must refuse while it is False

MONTHS_NE = ["बैशाख", "जेठ", "असार", "साउन", "भदौ", "असोज", "कार्तिक", "मंसिर", "पौष", "माघ", "फागुन", "चैत"]
MONTHS_EN = ["Baishakh", "Jestha", "Asar", "Shrawan", "Bhadra", "Ashwin", "Kartik", "Mangsir", "Poush", "Magh", "Falgun", "Chaitra"]
#: every spelling the guideline uses -> month number
_MONTH = {
    "बैशाख": 1, "वैशाख": 1, "जेठ": 2, "जेष्ठ": 2, "असार": 3, "साउन": 4, "श्रावण": 4, "भदौ": 5, "भाद्र": 5,
    "असोज": 6, "आसोज": 6, "आश्विन": 6, "कार्तिक": 7, "मंसिर": 8, "पौष": 9, "पुस": 9, "पुष": 9, "माघ": 10, "फागुन": 11, "चैत": 12, "चैत्र": 12,
}


def parse_season(text: str) -> List[Tuple[int, int]]:
    """``"भदौ - असोज"`` -> ``[(5, 6)]``; ``"चैत-जेठ, भदौ-कार्तिक"`` -> ``[(12, 2), (5, 7)]``; a single month ``"भदौ"`` -> ``[(5, 5)]``.
    Raises ValueError on a word that is not a month, so a misread cannot slip through as a wrong number."""
    ranges: List[Tuple[int, int]] = []
    for part in re.split(r"[,;]", text):
        words = [w for w in re.split(r"[\s–—\-]+", part.strip()) if w]
        if not words:
            continue
        try:
            nums = [_MONTH[w] for w in words]
        except KeyError as exc:
            raise ValueError(f"not a month name: {exc.args[0]!r} in {text!r}") from None
        if len(words) == 1 and re.search(r"[–—\-]", part):
            raise ValueError(f"a range with one end: {text!r}")
        if len(nums) > 2:
            raise ValueError(f"a range has two ends: {text!r}")
        ranges.append((nums[0], nums[-1]))
    if not ranges:
        raise ValueError(f"no season in {text!r}")
    return ranges


def months_covered(ranges: List[Tuple[int, int]]) -> List[int]:
    """Every month number a season touches, in calendar order, wrapping past चैत."""
    out: List[int] = []
    for a, b in ranges:
        m = a
        while True:
            if m not in out:
                out.append(m)
            if m == b:
                break
            m = m % 12 + 1
    return sorted(out)


# (table, printed page, serial in the table, Nepali name, scientific name as printed, altitude min m, max m, life form as printed,
#  Schedule-7 group of the part, part as printed, season as printed)
Row = Tuple[str, int, int, str, str, int, int, str, str, str, str]
ROWS: List[Row] = [
    # Table 5: roots, tubers, rhizomes (क)
    ("T5", 19, 1, "जटामसी, भुल्ले", "Nardostachys grandiflora", 3600, 4500, "बहुवर्षीय झार", "क", "जरा, गानो, प्रकन्द", "भदौ - असोज"),
    ("T5", 19, 2, "कुटकी", "Neopicrorhiza scrophulariiflora", 3600, 4800, "बहुवर्षीय झार", "क", "जरा, गानो, प्रकन्द", "भदौ – कार्तिक"),
    ("T5", 19, 3, "कुरिलो", "Asparagus racemosus", 150, 2100, "झाडी", "क", "जरा, गानो, प्रकन्द", "पुस – फागुन"),
    ("T5", 19, 4, "सुगन्धवाल, समायो", "Valeriana jatamansii", 1500, 3600, "बहुवर्षीय झार", "क", "जरा, गानो, प्रकन्द", "भदौ – कार्तिक"),
    ("T5", 19, 5, "पदमचाल", "Rheum australe", 3000, 4200, "बहुवर्षीय झार", "क", "जरा, गानो, प्रकन्द", "भदौ - असोज"),
    ("T5", 19, 6, "निरमसी", "Delphinium denudatum", 1500, 2700, "बहुवर्षीय झार", "क", "जरा, गानो, प्रकन्द", "असोज –कार्तिक"),
    ("T5", 20, 7, "जिम्बु", "Allium wallichii", 2400, 4700, "एकवर्षीय झार", "क", "जरा, गानो, प्रकन्द", "असोज –कार्तिक"),
    ("T5", 20, 8, "सतुवा", "Paris polyphylla", 1800, 3500, "एकवर्षीय झार", "क", "जरा, गानो, प्रकन्द", "भदौ - असोज"),
    ("T5", 20, 9, "पाखनबेद", "Bergenia ciliata", 1600, 3600, "बहुवर्षीय झार", "क", "जरा, गानो, प्रकन्द", "भदौ – कार्तिक"),
    ("T5", 20, 10, "भुतकेस", "Selinum wallichianum", 2700, 4800, "झार", "क", "जरा, गानो, प्रकन्द", "असोज – कार्तिक"),
    ("T5", 20, 11, "बोझो", "Acorus calamus", 200, 2300, "झार", "क", "जरा, गानो, प्रकन्द", "कार्तिक – मंसिर"),
    ("T5", 20, 12, "बिख", "Aconitum spicatum", 3300, 4300, "झार", "क", "जरा, गानो, प्रकन्द", "असोज –कार्तिक"),
    ("T5", 20, 13, "अतिस", "Delphinium heterophyllum", 3000, 4500, "झार", "क", "जरा, गानो, प्रकन्द", "असोज –कार्तिक"),
    ("T5", 20, 14, "काकोली", "Fritillaria cirrhosa", 3000, 4600, "झार", "क", "जरा, गानो, प्रकन्द", "साउन –भदौ"),
    ("T5", 20, 15, "गुजरगानो", "Stephania sp", 1800, 3000, "लहरा", "क", "जरा, गानो, प्रकन्द", "असोज –कार्तिक"),
    ("T5", 20, 16, "गुर्जो", "Tinospora sinensis", 300, 1500, "लहरा", "क", "जरा, गानो, प्रकन्द", "भदौ – कार्तिक"),
    ("T5", 20, 17, "चुत्रो", "Berberis spp", 1800, 3500, "झाडी", "क", "जरा, गानो, प्रकन्द", "असोज – कार्तिक"),
    ("T5", 20, 18, "टुकीफूल", "Taraxacum officinale", 1500, 3500, "झार", "क", "जरा, गानो, प्रकन्द", "असोज – कार्तिक"),
    ("T5", 20, 19, "लघुपत्र", "Podophyllum hexandrum", 2400, 4500, "झार", "क", "जरा, गानो, प्रकन्द", "भदौ - असोज"),
    ("T5", 20, 20, "सर्पगन्धा", "Rauvolfia serpentina", 100, 800, "झार", "क", "जरा, गानो, प्रकन्द", "भदौ – कार्तिक"),
    # Table 7: leaf (ग)
    ("T7", 24, 1, "धसिङ्ग्रे", "Gaultheria fragrantissima", 1200, 2700, "झाडी", "ग", "पात", "चैत-जेठ, भदौ-कार्तिक"),
    ("T7", 24, 2, "लौठसल्ला", "Taxus wallichiana", 2400, 3400, "रूख", "ग", "पात", "आश्विन – कार्तिक"),
    ("T7", 24, 3, "तेजपात", "Cinnamomum tamala", 450, 2100, "रूख", "ग", "पात", "आश्विन – फागुन"),
    ("T7", 24, 4, "सुनपाती", "Rhododendron anthopogon", 3300, 5100, "झाडी", "ग", "पात", "आश्विन – कार्तिक"),
    ("T7", 24, 5, "धूपी", "Juniperus indica", 3000, 4600, "रूख, झाडी", "ग", "पात", "आश्विन – कार्तिक"),
    ("T7", 24, 6, "तितेपाती", "Artemisia sp", 300, 2400, "बहुवर्षीय झार", "ग", "पात", "भदौ"),
    ("T7", 24, 7, "सिस्नु", "Urtica dioica", 1000, 3600, "झाडी", "ग", "पात", "साउन- भदौ"),
    # Table 10: bark (ख)
    ("T10", 28, 1, "लोक्ता", "Daphne bholua", 1500, 3500, "झाडी", "ख", "बोक्रा", "भदौ – जेठ"),
    ("T10", 28, 2, "अर्गेली", "Edgeworthia gardneri", 1500, 3000, "झाडी", "ख", "बोक्रा", "कार्तिक – फागुन"),
    ("T10", 28, 3, "अल्लो", "Girardinia diversifolia", 1700, 3000, "झार", "ख", "बोक्रा", "भदौ – असोज"),
    ("T10", 28, 4, "भोजपत्र", "Betula utilis", 3000, 4300, "रूख", "ख", "बोक्रा", "असोज– कार्तिक"),
    ("T10", 28, 5, "काउलो", "Persea odoratissima", 1500, 2100, "रूख", "ख", "बोक्रा", "भदौ–कार्तिक"),
    ("T10", 28, 6, "दालचिनी", "Cinnamomum tamala", 450, 2100, "रूख", "ख", "बोक्रा", "माघ–चैत"),
    ("T10", 28, 7, "बर्रो", "Terminalia bellirica", 300, 1100, "रूख", "ख", "बोक्रा", "माघ–चैत"),
    ("T10", 28, 8, "हर्रो", "Terminalia chebula", 150, 1100, "रूख", "ख", "बोक्रा", "माघ–वैशाख"),
    ("T10", 28, 9, "चुत्रो", "Berberis spp", 1800, 3500, "झाडी", "ख", "बोक्रा", "भदौ–कार्तिक"),
    # Table 13: fruit, flower, seed, fluff (ङ; घ for the fluff)
    ("T13", 31, 1, "टिमुर", "Zanthoxylum armatum", 1200, 2500, "झाडी", "ङ", "फल", "आसोज – मंसिर"),
    ("T13", 31, 2, "अमला", "Phyllanthus emblica", 150, 1400, "रूख", "ङ", "फल", "आश्विन – पौष"),
    ("T13", 32, 3, "पिप्ला", "Piper longum", 200, 1400, "झार", "ङ", "फल", "पौष – फागुन"),
    ("T13", 32, 4, "डालेचुक", "Hippophae salicifolia", 2000, 3700, "रूख", "ङ", "फल", "भदौ– कार्तिक"),
    ("T13", 32, 4, "भुईंचुक", "Hippophae tibetana", 3300, 4500, "झाडी", "ङ", "फल", "भदौ– कार्तिक"),
    ("T13", 32, 5, "चिउरी", "Diploknema butyracea", 400, 1400, "रूख", "ङ", "बीउ", "जेष्ठ–असार"),
    ("T13", 32, 6, "ओखर", "Juglans regia", 1200, 3000, "रूख", "ङ", "फल", "भाद्र – आश्विन"),
    ("T13", 32, 7, "रिठ्ठा", "Sapindus mukorossi", 800, 1400, "रूख", "ङ", "बीउ", "आश्विन – पौष"),
    ("T13", 32, 8, "बेल", "Aegle marmelos", 100, 1100, "रूख", "ङ", "फल", "श्रावण – भाद्र"),
    ("T13", 32, 9, "सिमल", "Bombax ceiba", 100, 1400, "रूख", "घ", "भुवा", "फागुन- चैत"),
    ("T13", 32, 10, "सिकाकाई", "Acacia rugata", 400, 800, "झाडी", "ङ", "कोसा", "फागुन- वैशाख"),
]


def species_key_of(scientific: str) -> str:
    """The profile key (``core.ntfp_methods.species_key``) of a printed name: ``Stephania sp`` and ``Berberis spp`` are genus entries."""
    from .species_synonyms import canonical_key

    return canonical_key(re.sub(r"\s+sp\.?$", " spp.", scientific.strip()))


def seasons() -> List[Dict[str, object]]:
    """The rows as dicts with the parsed months, for the review sheet and, once reviewed, the import."""
    out = []
    for table, page, serial, ne, sci, lo, hi, life, group, part, season in ROWS:
        rng = parse_season(season)
        out.append({
            "table": table, "page": page, "serial": serial, "nepali_name": ne, "scientific_name": sci, "species_key": species_key_of(sci),
            "altitude_min_m": lo, "altitude_max_m": hi, "life_form_ne": life, "part_group": group, "part_ne": part, "season_ne": season,
            "ranges": rng, "months": months_covered(rng), "reviewed": REVIEWED,
        })
    return out
