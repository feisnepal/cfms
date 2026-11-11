"""Semantic-palette SSOT: internal consistency + frontend-mirror lockstep.

`app.core.semantic_palettes` is the authority; `frontend/src/lib/semanticPalettes.ts`
must not drift from it. This test parses the TS file as text and compares hex
values — no DB, no fixtures.

THEMATIC_MAP_VARIABLES_PLAN §3.3 / Appendix C.2 / phase P0.
"""

import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.core import semantic_palettes as sp  # noqa: E402

_TS_PATH = os.path.normpath(
    os.path.join(
        os.path.dirname(__file__),
        "..",
        "..",
        "frontend",
        "src",
        "lib",
        "semanticPalettes.ts",
    )
)
_RAMPS_TS_PATH = os.path.normpath(
    os.path.join(
        os.path.dirname(__file__), "..", "..", "frontend", "src", "lib", "colorRamps.ts"
    )
)

_HEX = re.compile(r"#[0-9a-fA-F]{6}")


def _hexes(text: str) -> list[str]:
    return [h.lower() for h in _HEX.findall(text)]


# ── A. internal consistency ────────────────────────────────────────────────


def test_every_categorical_class_has_a_hex():
    for name, scheme in sp.CATEGORICAL.items():
        assert scheme, f"{name} is empty"
        for value, color in scheme.items():
            assert _HEX.fullmatch(color), f"{name}.{value} = {color!r} is not #rrggbb"


def test_dbh_classes_are_eight_and_hatched():
    assert len(sp.CATEGORICAL["dbh_classes"]) == 8
    assert len(sp.HATCH["dbh_classes"]) == 8
    assert list(sp.CATEGORICAL["dbh_classes"]) == list(sp.HATCH["dbh_classes"])


def test_condition_matches_frontend_condition_renderer_values():
    # layerRenderers.CONDITION_RENDERER uses these exact hexes.
    assert sp.CATEGORICAL["condition"] == {
        "Good": "#2e7d32",
        "Moderate": "#f9a825",
        "Weak": "#c62828",
    }
    assert sp.CATEGORICAL_OTHER["condition"] == "#bdbdbd"


def test_working_circle_protection_is_hatched():
    assert sp.HATCH["working_circle"]["protection"] == "////"
    assert sp.PROTECTION_HATCH == "////"


def test_diverging_and_bivariate_shapes():
    for name, stops in sp.DIVERGING.items():
        assert len(stops) == 5, name
    for name, stops in sp.BIVARIATE.items():
        assert len(stops) == 9, name


def test_ramps_are_verbatim_colorramps():
    assert set(sp.RAMPS) == {
        "blues",
        "greens",
        "reds",
        "oranges",
        "purples",
        "greys",
        "spectral",
        "viridis",
        "ylgn",
        "ylgnbu",
        "bupu",
        "ylorbr",
        "ylorrd",
    }
    for name, stops in sp.RAMPS.items():
        assert len(stops) == 5, name


def test_sequential_aliases_point_at_real_ramps():
    for measure, key in sp.SEQUENTIAL.items():
        base = key[:-2] if key.endswith("_r") else key
        assert base in sp.RAMPS, f"{measure} → {key} is not a ramp"


# ── B. break/sample helpers mirror colorRamps.ts ──────────────────────────


def test_sample_ramp_endpoints_and_midpoint():
    got = sp.sample_ramp("greens", 5)
    assert got == sp.RAMPS["greens"]  # n == stops → identity
    assert sp.sample_ramp("greens", 1) == ["#74c476"]  # middle stop
    assert sp.sample_ramp("greens", 0) == []


def test_sample_ramp_reversed():
    assert sp.sample_ramp("greys_r", 5) == list(reversed(sp.RAMPS["greys"]))


def test_sample_ramp_interpolates_in_rgb():
    # 3 samples across greens: first, exact middle stop, last
    a, b, c = sp.sample_ramp("greens", 3)
    assert a == "#edf8e9" and c == "#006d2c"
    assert b == "#74c476"


def test_equal_breaks_matches_ts_formula():
    # equalBreaks([0..100], 5) → [20, 40, 60, 80]
    assert sp.equal_breaks(list(range(0, 101)), 5) == [20.0, 40.0, 60.0, 80.0]
    assert sp.equal_breaks([], 5) == []
    assert sp.equal_breaks([1, 2, 3], 1) == []


def test_quantile_breaks_matches_ts_formula():
    vals = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
    br = sp.quantile_breaks(vals, 4)
    assert len(br) == 3
    assert br == [3.25, 5.5, 7.75]


def test_jenks_breaks_small_and_sorted():
    vals = [1, 1, 2, 10, 11, 12, 40, 41, 42]
    br = sp.jenks_breaks(vals, 3)
    assert len(br) == 2
    assert br == sorted(br)
    assert vals[0] < br[0] <= br[1] < vals[-1]


# ── C. frontend mirror lockstep ──────────────────────────────────────────


def test_ts_mirror_file_exists():
    assert os.path.isfile(_TS_PATH), _TS_PATH


def test_ts_categorical_blocks_match_python():
    ts = open(_TS_PATH, encoding="utf-8").read()

    def _ts_object(name: str) -> dict[str, str]:
        m = re.search(name + r"\s*:\s*\{([^}]*)\}", ts)
        assert m, f"{name} not found in {_TS_PATH}"
        pairs = re.findall(
            r"([A-Za-z0-9_'\"\- ]+?)\s*:\s*'(#[0-9a-fA-F]{6})'", m.group(1)
        )
        return {k.strip().strip("'\""): v.lower() for k, v in pairs}

    for name in (
        "condition",
        "growth_rate",
        "working_circle",
        "dbh_classes_3",
        "aspect",
    ):
        py = {k: v.lower() for k, v in sp.CATEGORICAL[name].items()}
        assert _ts_object(name) == py, f"CATEGORICAL.{name} drift TS vs PY"


def test_ts_diverging_bivariate_and_nodata_match_python():
    ts = open(_TS_PATH, encoding="utf-8").read()

    def _ts_array(name: str) -> list[str]:
        m = re.search(name + r"\s*:\s*\[([^\]]*)\]", ts)
        assert m, f"{name} not found"
        return [h.lower() for h in _HEX.findall(m.group(1))]

    for name, stops in sp.DIVERGING.items():
        assert _ts_array(name) == [s.lower() for s in stops], f"DIVERGING.{name} drift"
    for name, stops in sp.BIVARIATE.items():
        assert _ts_array(name) == [s.lower() for s in stops], f"BIVARIATE.{name} drift"

    assert f"'{sp.NO_DATA_FILL}'" in ts


def test_ts_full_hex_multiset_covers_python():
    """Every hex the Python SSOT defines must appear in the TS mirror."""
    ts_hex = set(_hexes(open(_TS_PATH, encoding="utf-8").read()))
    ts_hex |= set(_hexes(open(_RAMPS_TS_PATH, encoding="utf-8").read()))

    py_hex: set[str] = {sp.NO_DATA_FILL.lower()}
    for scheme in sp.CATEGORICAL.values():
        py_hex |= {v.lower() for v in scheme.values()}
    py_hex |= {v.lower() for v in sp.CATEGORICAL_OTHER.values()}
    for stops in (*sp.RAMPS.values(), *sp.DIVERGING.values(), *sp.BIVARIATE.values()):
        py_hex |= {s.lower() for s in stops}

    missing = py_hex - ts_hex
    assert (
        not missing
    ), f"hex values in the Python SSOT missing from the TS mirror: {sorted(missing)}"
