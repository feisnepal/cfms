"""One place that knows the other names of a column (UPLOAD_EXPERIENCE_PLAN.md, column-name work).

Hand-typed CSV / Excel files rarely use the template's header. ``Lon``, ``Pole Dia (cm)``, ``पोल व्यास``, ``घर नम्बर`` all name a column we know.
This module resolves such a header to the canonical column of a purpose, and reads the unit written in it. It is pure: no database, no I/O.

Design:
  * names are *built* from small word sets (stand x measure) instead of listing every spelling, so a new word covers every combination;
  * headers are folded before comparing: case, punctuation, spaces and the common Nepali spelling variants (ू/ु, ब/व, श/ष/स, म्/ं ...);
  * a unit in the header is parsed and handed on (``DBH (mm)`` is millimetres), it never changes the column it names;
  * names that are too ambiguous to guess (bare ``sp``, ``name``, ``unit``) are NOT accepted - the user chooses. ``x`` / ``y`` / ``easting`` / ``northing``
    are accepted as coordinate columns (UTM files are headed that way);
  * ``girth`` / ``circumference`` are NOT diameters; they are a different quantity, not a spelling of one.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from itertools import product
from typing import Dict, Iterable, List, Optional, Tuple

# ── folding ────────────────────────────────────────────────────────────────
# Nepali spellings that mean the same word in a column header. Applied to both sides of every comparison.
_NEPALI_FOLD = (
    ("‌", ""), ("‍", ""),  # zero-width joiners
    ("ू", "ु"), ("ी", "ि"), ("ऊ", "उ"), ("ई", "इ"),  # long -> short vowel
    ("ँ", "ं"), ("म्", "ं"),  # chandrabindu / anusvara / half-ma: नंवर = नंबर = नम्बर
    ("ब", "व"), ("श", "स"), ("ष", "स"), ("ण", "न"),
)


def fold(text: object) -> str:
    """Comparable form: lower case, Nepali spelling variants merged, every run of non-letters a single ``_``."""
    s = unicodedata.normalize("NFC", str(text)).strip().lower()
    for a, b in _NEPALI_FOLD:
        s = s.replace(a, b)
    out: List[str] = []
    for ch in s:
        out.append(ch if unicodedata.category(ch)[0] in ("L", "M", "N") else "_")
    return re.sub(r"_+", "_", "".join(out)).strip("_")


def _key(text: object) -> str:
    """Lookup key: folded with the separators removed, so ``Pole DBH`` = ``pole_dbh`` = ``poledbh``."""
    return fold(text).replace("_", "")


# ── units written in a header ──────────────────────────────────────────────
_UNIT_WORDS = {
    "cm": "cm", "centimeter": "cm", "centimetre": "cm", "centimeters": "cm", "सेमी": "cm", "से_मी": "cm", "सेन्टिमिटर": "cm",
    "mm": "mm", "millimeter": "mm", "millimetre": "mm", "मिमी": "mm", "मि_मि": "mm",
    "m": "m", "meter": "m", "metre": "m", "meters": "m", "metres": "m", "मिटर": "m", "मि": "m", "मीटर": "m",
    "ft": "ft", "feet": "ft", "foot": "ft", "फिट": "ft",
    "in": "in", "inch": "in", "inches": "in", "इन्च": "in", "इञ्च": "in",
    # land area (household template: "जमिन (ropani)") and the money scale of a rate column ("दर (हजारमा)" = thousands)
    "ropani": "ropani", "रोपनी": "ropani", "kattha": "kattha", "kaththa": "kattha", "katha": "kattha", "कठ्ठा": "kattha", "बिघा": "bigha", "bigha": "bigha",
    "ha": "ha", "hectare": "ha", "hectares": "ha", "हेक्टर": "ha",
    "हजार": "thousand", "हजारमा": "thousand", "thousand": "thousand", "thousands": "thousand", "in thousands": "thousand", "000": "thousand",
}
_UNIT_FOLDED = {fold(k): v for k, v in _UNIT_WORDS.items()}
_BRACKETED = re.compile(r"[\(\[\{]([^\)\]\}]*)[\)\]\}]\s*$")


def split_unit(header: object) -> Tuple[str, Optional[str]]:
    """``('pole dia', 'cm')`` for ``Pole Dia (cm)``; the unit is None when the header names none (the convention applies)."""
    text = str(header).strip()
    m = _BRACKETED.search(text)
    if m:
        unit = _UNIT_FOLDED.get(fold(m.group(1)))
        if unit:
            return text[: m.start()].strip(), unit
    parts = fold(text).split("_")
    if len(parts) > 1 and parts[-1] in _UNIT_FOLDED:
        return " ".join(parts[:-1]), _UNIT_FOLDED[parts[-1]]
    return text, None


# ── word sets ──────────────────────────────────────────────────────────────
_STANDS: Dict[str, Tuple[str, ...]] = {
    "regen": ("regen", "regeneration", "regenerations", "seedling", "seedlings", "विरुवा", "बिरुवा", "पुनरुत्पादन", "पुनरोत्पादन"),
    "sapling": ("sapling", "saplings", "लाथ्रा"),
    "pole": ("pole", "poles", "पोल"),
    "tree": ("tree", "trees", "रुख", "रूख"),
}
_MEASURES: Dict[str, Tuple[str, ...]] = {
    "dbh": ("dbh", "dia", "diameter", "व्यास", "छातीको उचाइको व्यास", "छातिको उचाइको व्यास", "डीबीएच"),
    "height": ("height", "ht", "उचाइ", "उचाई"),
    "count": ("count", "number", "num", "nos", "संख्या", "गोटा"),
    "species": ("species", "species name", "sp name", "scientific name", "scientific", "species scientific", "प्रजाति", "वैज्ञानिक नाम"),
    "class": ("class", "वर्ग"),
}
_PLOT = ("plot", "plot no", "plot number", "plot id", "plot num", "sample plot", "sample plot no", "sample plot number", "sp no",
         "नमुना प्लट", "नमुना प्लट नं", "प्लट", "प्लट नं", "प्लट नम्बर")
_BLOCK = ("block", "block name", "block no", "block id", "compartment", "compartment name", "compartment no", "compartment id",
          "ब्लक", "कम्पार्टमेन्ट")
_LON_CORE = ("lon", "long", "lng", "longitude", "longitude dd", "x longitude", "देशान्तर", "देशान्तर रेखांश")
_LAT_CORE = ("lat", "latitude", "latitude dd", "y latitude", "अक्षांश", "अक्षाँस")
# UTM files are headed Easting / Northing or X / Y. In a table that has coordinates those ARE the coordinate columns (the size of the numbers, not the
# header, then says whether they are degrees or metres, and which is which), so the field-inventory, tree and sample-plot tables accept them.
_LON = _LON_CORE + ("x", "easting", "east", "x coord", "x coordinate", "utm x", "utm easting", "पूर्वी निर्देशाङ्क")
_LAT = _LAT_CORE + ("y", "northing", "north", "y coord", "y coordinate", "utm y", "utm northing", "उत्तरी निर्देशाङ्क")
_TREE_NO = ("tree no", "tree number", "tree id", "sn", "s n", "रूख नं", "रुख नं", "क्र सं")


def _build(table: Dict[str, Iterable[str]]) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for canonical, names in table.items():
        for n in names:
            out.setdefault(_key(n), canonical)
    return out


def _stand_measure(stands: Iterable[str], measures: Iterable[str], name) -> Dict[str, Iterable[str]]:
    """``{canonical: [every 'stand measure' and 'measure stand' spelling]}`` for the given stands and measures."""
    table: Dict[str, List[str]] = {}
    for s, m in product(stands, measures):
        names = [f"{a} {b}" for a, b in product(_STANDS[s], _MEASURES[m])] + [f"{b} {a}" for a, b in product(_STANDS[s], _MEASURES[m])]
        table.setdefault(name(s, m), []).extend(names)
    return table


# ── field inventory ────────────────────────────────────────────────────────
_FIELD_INVENTORY: Dict[str, Iterable[str]] = {
    "block_name": _BLOCK,
    "sample_plot_number": _PLOT,
    "longitude": _LON,
    "latitude": _LAT,
}
_FIELD_INVENTORY.update(_stand_measure(
    ("regen", "sapling", "pole", "tree"), ("species",),
    lambda s, m: f"{s}_species_scientific",
))
_FIELD_INVENTORY.update(_stand_measure(("regen", "sapling", "pole", "tree"), ("dbh",), lambda s, m: f"{s}_dbh"))
_FIELD_INVENTORY.update(_stand_measure(("pole", "tree"), ("height",), lambda s, m: f"{s}_height"))
_FIELD_INVENTORY.update(_stand_measure(("regen", "sapling"), ("count",), lambda s, m: f"{s}_count"))
_FIELD_INVENTORY.update(_stand_measure(("pole", "tree"), ("class",), lambda s, m: f"{s}_class"))

# ── a loose list of trees ──────────────────────────────────────────────────
_TREES: Dict[str, Iterable[str]] = {
    "species": _MEASURES["species"] + ("tree species", "रूख प्रजाति", "रुख प्रजाति"),
    "dbh_cm": _MEASURES["dbh"] + ("tree dbh", "tree diameter"),
    "height_m": _MEASURES["height"] + ("tree height",),
    "longitude": _LON,
    "latitude": _LAT,
    "plot": _PLOT,
    "tree_no": _TREE_NO,
    "class": ("class", "stand type", "size class", "वर्ग"),
}

# ── households: the template's own Nepali headers + English names ─────────
# canonical (as in household_table.HOUSEHOLD_HEADER_MAP values) -> extra names; the template's Nepali headers are added from that map.
_HOUSEHOLD_ENGLISH: Dict[str, Tuple[str, ...]] = {
    "house_no": ("house no", "house number", "house", "hh no", "household no", "household number"),
    "surname": ("surname", "family name", "last name", "caste surname"),
    "household_head_male": ("household head male", "head male", "male head", "hh head male"),
    "household_head_female": ("household head female", "head female", "female head", "hh head female"),
    "address_tole": ("address tole", "tole", "settlement", "address", "टोल", "बस्ती"),
    "latitude": _LAT_CORE,
    "longitude": _LON_CORE,
    "female_count": ("female count", "female", "females", "women", "female members", "female population"),
    "male_count": ("male count", "male", "males", "men", "male members", "male population"),
    "land_area": ("land area", "land", "land holding", "landholding", "जग्गा", "जमिन", "जमीन"),
    "forest_based_occupation": ("forest based occupation", "forest occupation", "occupation forest"),
    "other_occupation": ("other occupation", "occupation other", "occupation"),
    "cow_ox_count": ("cow ox count", "cow ox", "cattle", "cows", "oxen"),
    "buffalo_count": ("buffalo count", "buffalo", "buffaloes"),
    "goat_sheep_count": ("goat sheep count", "goat sheep", "goats", "sheep"),
    "timber_demand_cft": ("timber demand cft", "timber demand", "timber cft", "timber"),
    "pole_demand": ("pole demand", "poles demand"),
    "firewood_demand_bhari": ("firewood demand bhari", "firewood demand", "firewood bhari", "firewood", "दाउरा"),
    "grass_demand_bhari": ("grass demand bhari", "grass demand", "grass bhari", "fodder demand", "घाँस"),
    "bedding_demand_bhari": ("bedding demand bhari", "bedding demand", "bedding bhari", "litter demand", "सोत्तर"),
    "caste_classification_ne": ("caste classification", "caste group", "ethnic group", "caste", "ethnicity", "जात", "जातजाति"),
    "other_group_membership": ("other group membership", "other membership", "group membership"),
    "prosperity_level": ("prosperity level", "prosperity", "wealth rank", "wellbeing rank", "economic status"),
    "remarks": ("remarks", "remark", "note", "notes", "comment", "comments"),
}


# ── activities: a programme table (क्र.सं. | कार्यक्रमको नाम | इकाई | दर (हजारमा) | बर्ष | जम्मा ...) ──────────────────────
# `इकाई` here is the unit of MEASURE (km, ha, number); the forest unit (block / compartment) is a different column.
_ACTIVITIES: Dict[str, Iterable[str]] = {
    "serial_no": ("क्र सं", "क्रसं", "सि नं", "सि.नं.", "सिनं", "sn", "s n", "serial no", "serial number", "sl no", "sno"),
    "activity": ("कार्यक्रमको नाम", "कार्यक्रम", "क्रियाकलाप", "क्रियाकलापको नाम", "activity", "activity name", "programme", "program", "programme name",
                 "program name", "operation", "name of activity"),
    "unit_of_measure": ("इकाई", "unit", "unit of measure", "measure unit", "uom", "unit name"),
    "quantity": ("परिमाण", "मात्रा", "quantity", "qty"),
    "rate": ("दर", "rate", "unit rate", "rate per unit"),
    "year": ("वर्ष", "बर्ष", "year", "plan year", "yr"),
    "total": ("जम्मा", "कुल", "जम्मा रकम", "total", "grand total"),
    "budget": ("बजेट", "रकम", "budget", "cost", "लागत", "अनुमानित लागत"),
    "forest_unit": ("block", "block name", "compartment", "compartment name", "ब्लक", "कम्पार्टमेन्ट"),
    "kind": ("kind", "feature kind", "category", "प्रकार"),
    "remarks": ("कैफियत", "remarks", "remark", "note", "notes"),
}


def _household() -> Dict[str, Iterable[str]]:
    from .household_table import HOUSEHOLD_HEADER_MAP

    table: Dict[str, List[str]] = {c: list(n) for c, n in _HOUSEHOLD_ENGLISH.items()}
    for ne, canonical in HOUSEHOLD_HEADER_MAP.items():
        table.setdefault(canonical, []).append(ne)
        table[canonical].append(canonical)  # the English field name of the template's second row
    return table


_SAMPLE_PLOTS: Dict[str, Iterable[str]] = {
    "plot_number": _PLOT,
    "block": _BLOCK,
    "radius_m": ("radius", "plot radius", "radius m", "त्रिज्या"),
    "longitude": _LON,
    "latitude": _LAT,
}
# the forest's identifying details (the essentials the Operational Plan cover prints): one row, one column per detail
_FOREST_METADATA: Dict[str, Iterable[str]] = {
    "forest_name": ("forest name", "name of forest", "community forest", "community forest name", "cf name", "वनको नाम", "सामुदायिक वनको नाम", "सामुदायिक वन"),
    "group_name": ("group name", "user group", "user group name", "cfug", "cfug name", "उपभोक्ता समूह", "उपभोक्ता समूहको नाम", "समूहको नाम"),
    "province": ("province", "pradesh", "प्रदेश"),
    "district": ("district", "जिल्ला"),
    "palika": ("palika", "municipality", "rural municipality", "local level", "गाउँपालिका", "नगरपालिका", "पालिका", "स्थानीय तह"),
    "ward": ("ward", "ward no", "ward number", "वडा", "वडा नं", "वडा नम्बर"),
    "division": ("division", "division forest office", "dfo", "डिभिजन", "डिभिजन वन कार्यालय", "जिल्ला वन कार्यालय"),
    "sub_division": ("sub division", "subdivision", "sub division forest office", "ilaka", "सब डिभिजन", "इलाका वन कार्यालय", "इलाका"),
    "cf_national_code": ("cf national code", "national code", "cf code", "forest code", "national database code", "राष्ट्रिय कोड", "सामुदायिक वन कोड", "वन कोड"),
    "fy_start": ("fy start", "fiscal year start", "plan start", "plan start fiscal year", "start fiscal year", "आर्थिक वर्ष सुरु", "योजना सुरु आर्थिक वर्ष"),
    "fy_end": ("fy end", "fiscal year end", "plan end", "plan end fiscal year", "end fiscal year", "आर्थिक वर्ष अन्त्य", "योजना अन्त्य आर्थिक वर्ष"),
}
_PURPOSE_TABLES = {"field_inventory": _FIELD_INVENTORY, "trees": _TREES, "activities": _ACTIVITIES, "sample_plots": _SAMPLE_PLOTS, "forest_metadata": _FOREST_METADATA}
COVERED_PURPOSES = ("field_inventory", "trees", "activities", "sample_plots", "households", "forest_metadata")
_BUILT: Dict[str, Dict[str, str]] = {}
_AMBIGUOUS: Dict[str, Dict[str, set]] = {}


def _table(purpose: str) -> Dict[str, str]:
    if purpose not in _BUILT:
        raw = _household() if purpose == "households" else _PURPOSE_TABLES.get(purpose)
        if raw is None:
            raise ValueError(f"no synonyms for purpose {purpose!r}")
        seen: Dict[str, set] = {}
        for canonical, names in raw.items():
            for n in names:
                seen.setdefault(_key(n), set()).add(canonical)
        _AMBIGUOUS[purpose] = {k: v for k, v in seen.items() if len(v) > 1}
        # a name two columns claim is a guess: it resolves to neither
        _BUILT[purpose] = {k: next(iter(v)) for k, v in seen.items() if len(v) == 1}
        for canonical in raw:
            _BUILT[purpose].setdefault(_key(canonical), canonical)
    return _BUILT[purpose]


@dataclass(frozen=True)
class ColumnMatch:
    header: str  # the user's header, as written
    canonical: str
    unit: Optional[str] = None  # written in the header; None = the convention applies (cm / m)


def resolve_column(header: object, purpose: str) -> Optional[ColumnMatch]:
    """The canonical column a header names for ``purpose``, with the unit written in it; None when it names no column we know."""
    table = _table(purpose)
    stem, unit = split_unit(header)
    for candidate, u in ((stem, unit), (str(header), None)):
        canonical = table.get(_key(candidate))
        if canonical:
            return ColumnMatch(str(header), canonical, u)
    return None


def plan_columns(headers: Iterable[object], purpose: str) -> Tuple[List[ColumnMatch], List[Tuple[str, str]]]:
    """``(matches, clashes)``: a header whose column an earlier header already took is a clash and is left to the user."""
    matches: List[ColumnMatch] = []
    clashes: List[Tuple[str, str]] = []
    taken: Dict[str, str] = {}
    for h in headers:
        m = resolve_column(h, purpose)
        if m is None:
            continue
        if m.canonical in taken:
            clashes.append((str(h), taken[m.canonical]))
            continue
        taken[m.canonical] = str(h)
        matches.append(m)
    return matches, clashes


# ── the schema's name for a canonical column (the three vocabularies: validator, schema, template) ─────────────────────
_SCHEMA_NAME_FIELD_INVENTORY = {"block_name": "block", "sample_plot_number": "plot_number"}
_SCHEMA_NAME_ACTIVITIES = {"forest_unit": "unit"}


def schema_column(purpose: str, canonical: str) -> str:
    """The name ``schema.py`` gives the column the resolver calls ``canonical`` (the same name when the two already agree)."""
    if purpose == "field_inventory":
        if canonical in _SCHEMA_NAME_FIELD_INVENTORY:
            return _SCHEMA_NAME_FIELD_INVENTORY[canonical]
        m = re.fullmatch(r"(regen|sapling|pole|tree)_(species_scientific|dbh|height)", canonical)
        if m:
            return {"species_scientific": f"{m.group(1)}_species", "dbh": f"{m.group(1)}_dbh_cm", "height": f"{m.group(1)}_height_m"}[m.group(2)]
    if purpose == "activities":
        return _SCHEMA_NAME_ACTIVITIES.get(canonical, canonical)
    return canonical


def schema_columns_present(purpose: str, headers: Iterable[object]) -> set:
    """Schema column names of ``purpose`` that the headers name (by any synonym): the classifier's view of a header row."""
    return {schema_column(purpose, m.canonical) for h in headers for m in [resolve_column(h, purpose)] if m}


def coordinate_columns(headers: Iterable[object], purpose: str = "trees", *, broad: bool = True) -> Tuple[Optional[str], Optional[str]]:
    """``(longitude / X header, latitude / Y header)`` of a table, or None for a role it has no column for.

    A header that is plainly longitude / latitude beats Easting / Northing / X / Y when a file has both (a UTM sheet that also carries degrees).
    ``broad=False`` accepts only the plain longitude / latitude names (the user-group picker asks the user rather than guess ``east`` / ``north``)."""
    core_lon = {_key(n) for n in _LON_CORE}
    core_lat = {_key(n) for n in _LAT_CORE}
    best: Dict[str, Tuple[int, str]] = {}
    for h in headers:
        m = resolve_column(h, purpose)
        if not m or m.canonical not in ("longitude", "latitude"):
            continue
        core = core_lon if m.canonical == "longitude" else core_lat
        rank = 0 if _key(split_unit(h)[0]) in core else 1
        if rank and not broad:
            continue
        if m.canonical not in best or rank < best[m.canonical][0]:
            best[m.canonical] = (rank, str(h))
    return (best.get("longitude", (0, None))[1], best.get("latitude", (0, None))[1])
