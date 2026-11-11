"""The authoritative FRTC 2015 legend (RS-0.2, owner-supplied 2026-09-30).

RS-0.2 was opened on 2026-09-29 with a false premise -- D32 established the
label was never *shown* -- and it then sat BLOCKED on data for a day because
guessing a legend was not acceptable. It is now closed with the real legend:

    Source: FRTC, Kathmandu
    Description: Forest type classification for Nepal
    26 classes, pixel 0.000269495 dd (30 m), Byte, categorical

Two facts make this row worth pinning hard.

**Every name was wrong.** Not one of the previous 26 matched. The old dict was a
generic land-cover scheme wearing FRTC's name -- it offered "Grassland",
"Wetland", "Built-up", "Plantation" and "Religious Forest", none of which are
FRTC forest types. So this file transcribes the legend independently of the
implementation: if someone "helpfully" restores a plausible-looking name, this
fails even though the code still runs and still draws.

**Code 26 is "Unclassified", and it is the majority.** 26 is 423k of 545k
pixels in the test window (~78%). It was previously labelled "Protected
Forest", so the bulk of the country carried a class it is not. The legend's
OWN name for 26 is "Non forest"; the owner directed (2026-10-01, RS-9.5) that
this codebase say "Unclassified" instead, because RS-4.1a found 26 is ~90%
co-located with ESA closed-canopy tree cover -- "Non forest" would assert
something the data contradicts, while "Unclassified" states only the true
fact: FRTC did not assign these pixels one of the 25 named types.

FRTC 26 IS an *anonymous* class (RS-9.5, carved as geometry via
`anonymous_codes=(26,)`, never reported as a type) -- the same treatment NASA
2020 code 0 gets, decided independently from FRTC's own distribution and the
class-26 finding above, not inherited from NASA's rule. Code 0 already means
non-forest, NoData and sea/water in the NASA, NDVI and ESA products
respectively -- each source's vocabulary stays its own.
"""
from pathlib import Path

import pytest

from app.core import forest_types as ft

#: Transcribed from the owner's legend, in order. Kept as a literal list rather
#: than compared pairwise so that a REORDERING is also a failure.
FRTC_2015_LEGEND = [
    "Shorea robusta Forest",
    "Tropical Mixed Broadleaved Forest",
    "Subtropical Mixed Broadleaved Forest",
    "Shorea robusta - Mixed Broadleaved Forest",
    "Abies Mixed Forest",
    "Upper Temperate Coniferous Forest",
    "Cool Temperate Mixed Broadleaved Forest",
    "Castanopsis Lower Temperate Mixed Broadleaved Forest",
    "Pinus roxburghii Forest",
    "Alnus Forest",
    "Schima Forest",
    "Pinus roxburghii - Mixed Broadleaved Forest",
    "Pinus wallichiana Forest",
    "Warm Temperate Mixed Broadleaved Forest",
    "Upper Temperate Quercus Forest",
    "Rhododendron arboreum Forest",
    "Temperate Rhododendron Mixed Broadleaved Forest",
    "Dalbergia sissoo-Senegalia catechu Forest",
    "Terminalia - Tropical Mixed Broadleaved Forest",
    "Temperate Mixed Broadleaved Forest",
    "Tropical Deciduous Indigenous Riverine Forest",
    "Tropical Riverine Forest",
    "Lower Temperate Mixed robusta Forest",
    "Pinus roxburghii - Shorea robusta Forest",
    "Lower Temperate Pinus roxburghii - Quercus Forest",
    "Unclassified",
]

FRONTEND_PALETTE = (
    Path(__file__).resolve().parents[3]
    / "frontend" / "src" / "lib" / "semanticPalettes.ts"
)


def test_the_legend_has_exactly_26_classes():
    assert len(FRTC_2015_LEGEND) == 26


def test_every_code_carries_the_authoritative_name_in_order():
    assert [c.name_en for c in ft.FRTC_FOREST_TYPES.values()] == FRTC_2015_LEGEND


def test_class_26_is_unclassified_and_not_a_forest_type():
    """The gate's named case. This is the single most consequential entry.

    The legend's own name for 26 is "Non forest"; this codebase deliberately
    says "Unclassified" instead (owner directive 2026-10-01, RS-9.5) because
    RS-4.1a found 26 is ~90% co-located with closed-canopy tree cover, so
    "Non forest" would be a false claim the data contradicts."""
    assert ft.FRTC_FOREST_TYPES[26].name_en == "Unclassified"
    assert ft.get_forest_type_class(26).name_en == "Unclassified"


def test_no_non_forest_entry_is_presented_as_a_forest_type():
    """Guard against the old failure mode generically: a class whose name says
    "forest" while the legend calls it non-forest is a mislabel, whatever code
    it sits on."""
    assert not any(
        code != 26 and "non forest" in cls.name_en.lower()
        for code, cls in ft.FRTC_FOREST_TYPES.items()
    )


def test_the_previous_fabricated_names_are_gone():
    """Named explicitly, because these read as plausible and a future edit could
    reintroduce one without failing anything else."""
    gone = [
        "Tropical Sal Forest", "Tropical Deciduous Forest", "Tropical Thorn Forest",
        "Sub-tropical Pine Forest", "Sub-tropical Broadleaf Forest",
        "Lower Temperate Broadleaf Forest", "Lower Temperate Mixed Forest",
        "Upper Temperate Broadleaf Forest", "Upper Temperate Mixed Forest",
        "Temperate Coniferous Forest", "Sub-alpine Forest", "Alpine Scrub",
        "Grassland", "Shrubland", "Wetland", "Water Body", "Barren/Rock",
        "Snow/Glacier", "Agriculture", "Built-up", "Riverine Forest",
        "Plantation", "Community Forest", "Leasehold Forest", "Religious Forest",
        "Protected Forest",
    ]
    present = {c.name_en for c in ft.FRTC_FOREST_TYPES.values()}
    assert not (set(gone) & present), sorted(set(gone) & present)


def test_every_class_has_a_colour_and_a_nepali_name():
    """`ForestType` requires both, so this is structural -- but a hex of
    ``None`` or an empty Nepali string would still slip through a dataclass."""
    for code, cls in ft.FRTC_FOREST_TYPES.items():
        assert cls.color_hex and cls.color_hex.startswith("#"), code
        assert len(cls.color_hex) == 7, (code, cls.color_hex)
        assert cls.name_np and cls.name_np.strip(), code


def test_every_class_has_a_distinct_colour():
    """26 classes drawn from a handful of colours would make the legend
    unreadable, and would hide a copy-paste error in the table."""
    hexes = [c.color_hex.lower() for c in ft.FRTC_FOREST_TYPES.values()]
    assert len(set(hexes)) == 26, len(set(hexes))


def test_the_tile_layer_description_states_26_classes():
    """RS-0.2's gate named `tile_service.py`'s count as wrong: it advertised 25
    classes for a 26-class legend, and did not say what 26 is."""
    from app.services.tile_service import TileService

    entry = TileService.RASTER_METADATA["forest_type"]
    assert entry["year"] == "2015"
    assert "26" in entry["description"]
    assert "25 classes" not in entry["description"]
    assert "Unclassified" in entry["description"]


def test_the_frontend_palette_mirrors_every_name_and_hex():
    """The OP map and the tile beside it must not disagree (the RS-0.5 defect).
    The frontend palette is keyed by NAME, so a backend rename orphans its keys
    silently -- this is the only thing that notices."""
    src = FRONTEND_PALETTE.read_text(encoding="utf-8")
    block = src[src.index("  forest_type: {"):]
    block = block[: block.index("  },")]
    for cls in ft.FRTC_FOREST_TYPES.values():
        assert f"'{cls.name_en}':" in block, f"frontend palette missing {cls.name_en!r}"
        assert cls.color_hex.lower() in block, f"frontend palette missing hex for {cls.code}"


def test_unknown_codes_still_degrade_rather_than_raise():
    """`get_forest_type()` raises KeyError by design; the render path must use the
    non-raising accessor or an odd code kills the map."""
    assert ft.get_forest_type_class(0).name_en == "Unknown"
    assert ft.get_forest_type_class(27).name_en == "Unknown"
    assert ft.get_forest_type_class(99).name_en == "Unknown"


@pytest.mark.parametrize("code", list(range(1, 27)))
def test_each_code_resolves_to_itself(code):
    assert ft.get_forest_type_class(code).code == code
    assert ft.get_forest_type(code).code == code
