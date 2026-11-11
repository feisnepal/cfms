"""RS-0.5 — ``raster_zonal`` registration must match reality.

Defects this locks down (all found by inspection, 2026-09-29):

1. ``forest_health`` was registered in ``_CONT`` (continuous) with range
   ``(0.5, 5.5)``, so a unit was labelled with the *mean of class codes*
   1..5 — a number that names no class. It is an integer class raster.
2. ``nasa_forest_2020`` was in neither registry, so it could not render on an
   OP thematic map at all.
3. The two new classes had no backend vocabulary, so any label/hex would have
   been re-invented in a third place (``FOREST_TYPE_LABELS`` is what that
   looks like, and it already drifted).
4. Registry table names are not checked against the tile catalog, which is how
   ``_CAT['slope']`` came to point at a different table than the map renders.

No database is required: every test here is pure-python or uses a fake session.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.core import forest_types as ft
from app.core import semantic_palettes as sp
from app.services.operational_plan import raster_zonal as rz

# ── 1. the type of each raster: categorical vs continuous ───────────────
# Verified against the dev DB by ST_ValueCount over a Kathmandu window
# (2026-09-29): nepal_forest_health -> {0,1,2,3,4,5}; nasa_forest_2020 ->
# {0,1,2,3}; both use 0 as NoData, so every class is a small integer.
CATEGORICAL_ONLY = ("forest_health", "nasa_quality", "slope", "aspect", "landcover", "forest_type")


def test_forest_health_is_categorical_not_continuous():
    """The defect: a mean of class codes 1..5 is not a health value."""
    assert "forest_health" in rz._CAT
    assert "forest_health" not in rz._CONT


def test_nasa_quality_is_registered():
    """The defect: absent from both registries, so it could not render."""
    assert "nasa_quality" in rz._CAT
    assert "nasa_quality" not in rz._CONT


@pytest.mark.parametrize("key", CATEGORICAL_ONLY)
def test_no_key_is_in_both_registries(key):
    """A table in both registries is an ambiguity waiting to happen."""
    assert not (key in rz._CONT and key in rz._CAT)


# ── 2. the vocabularies exist, in one place, with all three fields ──────
def test_health_vocabulary_covers_every_raster_code():
    """0 is NoData, so it must not be a class."""
    assert sorted(ft.FOREST_HEALTH_CLASSES) == [1, 2, 3, 4, 5]
    for code, cls in ft.FOREST_HEALTH_CLASSES.items():
        assert cls.code == code
        assert cls.name_en and cls.name_np and cls.color_hex.startswith("#")
        assert cls.ndvi_range, "health classes are defined by an NDVI band"


def test_nasa_vocabulary_covers_every_raster_code():
    assert sorted(ft.NASA_FOREST_QUALITY) == [1, 2, 3]
    for code, cls in ft.NASA_FOREST_QUALITY.items():
        assert cls.code == code
        assert cls.name_en and cls.name_np and cls.color_hex.startswith("#")


def test_unknown_code_falls_back_without_raising():
    """ST_ValueCount can return a code nobody registered; it must not 500."""
    for getter in (ft.get_forest_health, ft.get_nasa_forest_quality):
        unknown = getter(99)
        assert unknown.name_en == "Unknown"
        assert unknown.color_hex == "#808080"


# ── 3. palette keys and class records agree (no third vocabulary) ──────
@pytest.mark.parametrize(
    "palette,table",
    [("forest_health_class", ft.FOREST_HEALTH_CLASSES), ("nasa_quality", ft.NASA_FOREST_QUALITY)],
)
def test_palette_covers_every_class_with_matching_hex(palette, table):
    p = sp.CATEGORICAL[palette]
    assert set(p) == {c.name_en for c in table.values()}, "legend keys drift from the SSOT"
    for cls in table.values():
        assert p[cls.name_en] == cls.color_hex, f"{palette}/{cls.code} hex drift"


# ── 4. the measure record shape the render path reads ──────────────────
class _FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def first(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return self._rows


class _FakeDB:
    """Serves one fixed result for any query.

    ``counts`` answers ``ST_ValueCount`` (categorical). ``summary`` answers
    ``ST_SummaryStats``-style continuous queries as ``(mean, lo, hi, n)``.
    Which one is returned is decided from the SQL, so one fake serves both
    registry families.
    """

    def __init__(self, counts=None, summary=None):
        self.counts = counts or {}
        self.summary = summary or (1.0, 0.0, 2.0, 10)
        self.queries = 0

    def execute(self, q, params=None):
        self.queries += 1
        sql = str(getattr(q, "text", q))
        if "SUM((pvc).value * (pvc).count)" in sql:
            return _FakeResult([self.summary])
        return _FakeResult([(c, n) for c, n in self.counts.items()])

    def begin_nested(self):
        import contextlib

        return contextlib.nullcontext()


def test_health_record_has_dominant_and_shares():
    db = _FakeDB({1: 10, 2: 20, 3: 70})
    rec = rz._rec_for_measure(db, "POLYGON((0 0,1 0,1 1,0 0))", "forest_health_dominant")
    assert rec["forest_health_dominant"] == "Moderate"
    # composition components keyed by EN class name, summing to 100
    assert rec["Stressed"] == 10.0
    assert rec["Poor"] == 20.0
    assert rec["Moderate"] == 70.0
    assert rec["Stressed"] + rec["Poor"] + rec["Moderate"] == 100.0
    # glyph list is (NP name, pct, hex) ordered by share
    assert rec["_forest_health_glyph"][0] == ("मध्यम", 70.0, "#FFD700")
    assert "forest_health_mean" not in rec, "must not resurrect a mean of class codes"


def test_nasa_record_has_dominant_and_shares():
    db = _FakeDB({1: 5, 2: 95})
    rec = rz._rec_for_measure(db, "POLYGON((0 0,1 0,1 1,0 0))", "nasa_quality_dominant")
    assert rec["nasa_quality_dominant"] == "Young Secondary Forest"
    assert rec["Primary Forest"] == 5.0
    assert rec["Young Secondary Forest"] == 95.0
    assert rec["_nasa_quality_glyph"][0] == ("कम उमेरको दोस्रो पुस्ताको वन", 95.0, "#FF0000")


def test_empty_raster_yields_empty_record_not_a_crash():
    """A unit the raster does not cover must render blank, not error."""
    db = _FakeDB({})
    for measure in ("forest_health_dominant", "forest_health_classes", "nasa_quality_dominant"):
        assert rz._rec_for_measure(db, "POLYGON((0 0,1 0,1 1,0 0))", measure) == {}


def test_unknown_raster_code_still_produces_a_record():
    """Defensive: a code with no registered class must not raise mid-render."""
    db = _FakeDB({7: 100})
    rec = rz._rec_for_measure(db, "POLYGON((0 0,1 0,1 1,0 0))", "nasa_quality_dominant")
    assert rec["nasa_quality_dominant"] == "Unknown"
    assert rec["Unknown"] == 100.0


# ── 4b. owner decisions 2026-09-29 (D36): slope + forest_type ──────────
def test_slope_reads_the_authoritative_table():
    """rasters.slope_regulation is what constants.py, the tile catalog and
    auto_block_service.vectorize_slope all use. This registry was the last
    place on rasters.slope, so the OP map computed slope from a different
    raster than the slope map drawn next to it."""
    assert rz._CAT["slope"][0] == "rasters.slope_regulation"


def test_forest_type_labels_come_from_core():
    """No third vocabulary: nothing may define its own forest-type label dict.

    Scans app/ for a definition, so re-introducing a local label table anywhere
    (not just in raster_zonal) fails here.
    """
    assert not hasattr(rz, "FOREST_TYPE_LABELS")
    app_root = Path(rz.__file__).resolve().parents[3] / "app"
    offenders = [
        str(p.relative_to(app_root))
        for p in app_root.rglob("*.py")
        if re.search(r"^FOREST_TYPE_LABELS\s*[:=]", p.read_text(encoding="utf-8"), re.M)
    ]
    assert not offenders, f"a local forest-type label dict still exists: {offenders}"


def test_forest_type_palette_matches_core_vocabulary():
    """26 classes, keys and hexes identical to core.forest_types."""
    p = sp.CATEGORICAL["forest_type"]
    assert len(p) == 26
    for cls in ft.FRTC_FOREST_TYPES.values():
        assert p[cls.name_en] == cls.color_hex


def test_forest_type_record_labels_every_code_the_raster_carries():
    """The old dict could not label 14, 15, 20, 23, 25, 26 — codes that make
    up most of this raster. All 12 codes observed in the dev DB must resolve."""
    observed = [1, 2, 3, 6, 7, 9, 14, 15, 20, 23, 25, 26]
    db = _FakeDB({c: 10 for c in observed})
    rec = rz._rec_for_measure(db, "POLYGON((0 0,1 0,1 1,0 0))", "forest_type_dominant")
    for code in observed:
        assert ft.get_forest_type_class(code).name_en in rec, f"code {code} unlabelled"
    # Tie on every code -> the lowest code wins, and code 1 is now
    # "Shorea robusta Forest" per the authoritative FRTC 2015 legend
    # (owner-supplied 2026-09-30, RS-0.2). It used to be "Tropical Sal Forest",
    # which was part of a fabricated 26-name list.
    assert rec["forest_type_dominant"] == "Shorea robusta Forest"
    assert len(rec["_forest_type_glyph"]) == len(observed)


def test_forest_type_unknown_code_degrades_not_raises():
    """core.forest_types.get_forest_type() raises KeyError; the render path
    must use the non-raising accessor or an odd code kills the map."""
    assert ft.get_forest_type_class(99).name_en == "Unknown"
    db = _FakeDB({99: 5})
    rec = rz._rec_for_measure(db, "POLYGON((0 0,1 0,1 1,0 0))", "forest_type_dominant")
    assert rec["forest_type_dominant"] == "Unknown"


# ── 5. the specs point at measures that actually exist ────────────────
def _opsmap_specs() -> dict:
    """The S9 ``source="raster_zonal"`` specs live in the thememap catalog
    (BUILTIN_OPSMAP_SPECS holds the op-map family and has none of them)."""
    from app.services.operational_plan import thematic_map_spec as tms

    return tms.BUILTIN_THEMEMAP_SPECS


def test_health_spec_is_categorical_not_a_mean_choropleth():
    spec = _opsmap_specs()["zone__forest_health"]
    assert spec.measure == "forest_health_dominant"
    assert spec.value_kind == "categorical"
    assert spec.palette == "forest_health_class"


def test_nasa_specs_exist():
    specs = _opsmap_specs()
    for key, measure, palette in (
        ("zone__nasa_quality_dominant", "nasa_quality_dominant", "nasa_quality"),
        ("zone__nasa_quality__pie", "nasa_quality_classes", "nasa_quality"),
    ):
        assert key in specs, f"{key} missing"
        assert specs[key].measure == measure
        assert specs[key].palette in sp.CATEGORICAL


def test_every_raster_zonal_measure_resolves():
    """No spec may name a measure the dispatcher does not handle.

    Guards the silent-empty-map failure mode: an unknown measure returns {}
    and the map simply renders nothing. (canopy_mean/elevation_* also need
    rasterio/filesystem, so they are excluded from the fake-DB sweep.)
    """
    unhandled = []
    for spec in _opsmap_specs().values():
        if spec.source != "raster_zonal":
            continue
        if spec.measure in ("canopy_mean",):  # reads canopy_height5m.tif
            continue
        db = _FakeDB({1: 1})
        if rz._rec_for_measure(db, "POLYGON((0 0,1 0,1 1,0 0))", spec.measure) == {}:
            unhandled.append((spec.key, spec.measure))
    assert not unhandled, f"measures with no handler (blank maps): {unhandled}"
