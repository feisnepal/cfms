"""The ``dbh_class_breakdown`` reader/writer contract.

``_ge40_from_breakdown`` spent its life asking for ``timber`` and ``count``; the
writer has always stored ``timber_m3_per_ha`` and ``count_per_ha``. Every class
therefore read 0.0, the total was 0.0, the function returned ``(None, None)`` and
the SFM page rendered that as *"Indicative - pending inventory"* -- for an
inventory that was complete. On calculation ``b67f9e1c`` this made growing stock
>= 40 cm null on all 24 units and total annual harvest read 0.0 against a
measured 4,569 m3/yr of AAH.

The two tests that matter here are :func:`test_reader_accepts_the_writers_own_keys`
and :func:`test_ge40_class_keys_match_the_registry_the_writer_uses`. They read the
contract off the writer rather than off a copy of it, so a rename on either side
fails a test instead of silently producing zero again.

See ``SUSTAINABLE_FM_TRACKER.md`` row P1.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from app.core.dbh_classifier import DbhClassRegistry
from app.services.sustainable_fm.species_assemblage import (
    _BREAKDOWN_MEASURE_KEYS,
    _ge40_class_keys,
    _ge40_from_breakdown,
    _norm_class_key,
)

APP = Path(__file__).resolve().parents[1] / "app"
WRITER = APP / "services" / "field_inventory_service.py"
READER = APP / "services" / "sustainable_fm" / "species_assemblage.py"

# Keys the writer emits as numbers rather than as labels.
NUMERIC = ("count_per_ha", "timber_m3_per_ha", "firewood_m3_per_ha")
LABELS = ("label_en", "label_np")
# The names the broken reader looked for. Kept as the regression's fingerprint.
OLD_READER_KEYS = ("timber", "count")


def _writer_breakdown_keys() -> set:
    """Every string key of the dict the writer assigns to ``dbh_class_breakdown``.

    Read off the writer's AST -- deliberately not a transcribed copy, because a
    copy is exactly how the reader and the writer came to disagree.
    """
    tree = ast.parse(WRITER.read_text(encoding="utf-8"))
    alias = None
    found: set = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if isinstance(target, ast.Attribute) and target.attr == "dbh_class_breakdown":
                if isinstance(node.value, ast.Name):
                    alias = node.value.id
    assert alias, "no assignment to .dbh_class_breakdown found in %s" % WRITER.name
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign) or not isinstance(node.value, ast.Dict):
            continue
        for target in node.targets:
            # ``breakdown = {...}`` or ``breakdown[key] = {...}`` -- the writer builds
            # the dict inside a loop, so the subscript form is the one that matters.
            is_alias = (isinstance(target, ast.Name) and target.id == alias) or (
                isinstance(target, ast.Subscript)
                and isinstance(target.value, ast.Name)
                and target.value.id == alias
            )
            if is_alias:
                found.update(
                    k.value
                    for k in node.value.keys
                    if isinstance(k, ast.Constant) and isinstance(k.value, str)
                )
    assert found, "found .dbh_class_breakdown = %s but no dict literal assigned to it" % alias
    return found


def _writer_class_keys() -> list:
    """The class keys the writer emits, from its own ``DBH_CLASSES`` list."""
    system = DbhClassRegistry.get_system("guideline_2061")
    if hasattr(system, "classes"):
        system = system.classes
    return [c.key for c in system]


def _breakdown(shape: str = "stored") -> dict:
    """A breakdown in the shape the writer really produces."""
    if shape == "stored":
        out = {}
        for i, key in enumerate(_writer_class_keys()):
            out[key] = {
                "count_per_ha": round(10.0 + i, 2),
                "timber_m3_per_ha": round(1.0 + i, 2),
                "firewood_m3_per_ha": 0.5,
                "label_en": "class %d" % i,
                "label_np": "वर्ग %d" % i,
            }
        return out
    if shape == "legacy":
        return {k: {"timber": 1.0 + i, "count": 10.0 + i} for i, k in enumerate(_writer_class_keys())}
    if shape == "unknown":
        return {k: {"volume_m3_ha": 1.0} for k in _writer_class_keys()}
    raise AssertionError(shape)


# ── the contract ──────────────────────────────────────────────────────────────
def test_reader_reads_the_timber_measure_the_writer_emits():
    """The measure this function exists to read must be the one the writer stores."""
    emitted = _writer_breakdown_keys()
    assert emitted, "could not find the writer's breakdown dict in %s" % WRITER.name
    assert "timber_m3_per_ha" in emitted, (
        "the writer no longer stores timber_m3_per_ha; this test needs re-reading "
        "before the reader is trusted (writer now emits %s)" % sorted(emitted)
    )
    assert "timber_m3_per_ha" in _BREAKDOWN_MEASURE_KEYS
    # The reader must prefer the volume measure over any count.
    assert _BREAKDOWN_MEASURE_KEYS.index("timber_m3_per_ha") < _BREAKDOWN_MEASURE_KEYS.index(
        "count_per_ha"
    )


def test_firewood_is_deliberately_not_read_as_growing_stock():
    """The writer emits firewood. Reading it would understate the >= 40 cm share."""
    assert "firewood_m3_per_ha" in _writer_breakdown_keys()
    assert "firewood_m3_per_ha" not in _BREAKDOWN_MEASURE_KEYS
    # And prove it: doubling the firewood must not move the ratio.
    breakdown = _breakdown("stored")
    before, _ = _ge40_from_breakdown(breakdown, 100.0, 1.0)
    for value in breakdown.values():
        value["firewood_m3_per_ha"] = 10_000.0
    after, _ = _ge40_from_breakdown(breakdown, 100.0, 1.0)
    assert before == after


def test_one_basis_is_used_so_volumes_and_counts_are_never_summed():
    """A count value must never enter a volume sum, however large it is."""
    keys = _writer_class_keys()
    with_counts = {
        keys[0]: {"timber_m3_per_ha": 10.0, "count_per_ha": 1_000_000.0},
        keys[-1]: {"timber_m3_per_ha": 90.0, "count_per_ha": 1.0},
    }
    volumes_only = {
        keys[0]: {"timber_m3_per_ha": 10.0},
        keys[-1]: {"timber_m3_per_ha": 90.0},
    }
    assert _ge40_from_breakdown(with_counts, 100.0, 1.0) == _ge40_from_breakdown(
        volumes_only, 100.0, 1.0
    )


def test_a_class_with_no_timber_contributes_zero_and_is_reported(caplog):
    """It must not be invented from its stem count."""
    keys = _writer_class_keys()
    mixed = {
        keys[0]: {"timber_m3_per_ha": 10.0, "count_per_ha": 1_000_000.0},
        keys[-1]: {"count_per_ha": 1_000_000.0},  # no timber at all
    }
    with caplog.at_level("WARNING"):
        per_ha, _ = _ge40_from_breakdown(mixed, 100.0, 1.0)
    assert per_ha == 0.0
    assert any("were read as 0" in r.message for r in caplog.records)
    assert any(keys[-1] in r.message for r in caplog.records)


def test_the_old_reader_keys_are_not_what_the_writer_emits():
    """The regression's fingerprint: the old names are not the stored names."""
    emitted = _writer_breakdown_keys()
    for key in OLD_READER_KEYS:
        assert key not in emitted, (
            "%r is emitted by the writer, so this test no longer describes the bug"
            % key
        )


def test_ge40_class_keys_match_the_registry_the_writer_uses():
    system = DbhClassRegistry.get_system("guideline_2061")
    if hasattr(system, "classes"):
        system = system.classes
    expected = {_norm_class_key(c.key) for c in system if float(c.lower or 0) >= 40.0}
    assert expected, "registry returned no classes >= 40 cm"
    assert _ge40_class_keys() == expected
    # No class below 40 cm may leak in.
    below = {_norm_class_key(c.key) for c in system if float(c.lower or 0) < 40.0}
    assert not (_ge40_class_keys() & below)


def test_no_inline_class_list_survives_in_the_reader():
    """A literal set of class names is what the old reader used to carry."""
    source = READER.read_text(encoding="utf-8")
    for match in re.finditer(r"\{\s*[\"'0-9][^{}]*?[\"'0-9]\s*\}", source):
        literal = match.group(0)
        if re.search(r"[\"']\d", literal):  # looks like a class key, not a config dict
            raise AssertionError(
                "inline class-key set found in species_assemblage.py: %r -- derive it "
                "from the registry instead (_ge40_class_keys)" % literal
            )


# ── behaviour ─────────────────────────────────────────────────────────────────
def test_stored_shape_yields_a_ratio():
    per_ha, absolute = _ge40_from_breakdown(_breakdown("stored"), 100.0, 2.0)
    assert per_ha is not None and absolute is not None
    assert 0.0 < per_ha <= 100.0
    assert absolute == pytest.approx(per_ha * 2.0, rel=1e-3)


def test_stored_shape_gives_a_different_answer_from_the_old_broken_reader():
    """Guards that the fix actually moved the number, not just stopped returning None."""
    stored = _breakdown("stored")
    per_ha, _ = _ge40_from_breakdown(stored, 100.0, 2.0)
    # What the old reader computed: 0.0 total -> None.
    old_total = 0.0
    for value in stored.values():
        old_total += float(value.get("timber") or 0.0) + float(value.get("count") or 0.0)
    assert old_total == 0.0
    assert per_ha is not None


def test_legacy_shape_still_reads():
    per_ha, _ = _ge40_from_breakdown(_breakdown("legacy"), 100.0, 1.0)
    assert per_ha is not None


def test_unknown_shape_returns_none_and_logs(caplog):
    with caplog.at_level("WARNING"):
        assert _ge40_from_breakdown(_breakdown("unknown"), 100.0, 1.0) == (None, None)
    assert any("no recognised measure key" in r.message for r in caplog.records)


def test_partial_unknown_shape_still_computes_but_says_so(caplog):
    breakdown = _breakdown("stored")
    first = next(iter(breakdown))
    breakdown[first] = {"volume_m3_ha": 3.0}
    with caplog.at_level("WARNING"):
        per_ha, _ = _ge40_from_breakdown(breakdown, 100.0, 1.0)
    assert per_ha is not None
    assert any("were read as 0" in r.message for r in caplog.records)
    assert any(first in r.message for r in caplog.records)


def test_missing_breakdown_or_gs_returns_none():
    assert _ge40_from_breakdown(None, 100.0, 1.0) == (None, None)
    assert _ge40_from_breakdown({}, 100.0, 1.0) == (None, None)
    assert _ge40_from_breakdown(_breakdown("stored"), None, 1.0) == (None, None)


def test_zero_total_returns_none_without_warning(caplog):
    zero = {k: {"timber_m3_per_ha": 0.0} for k in _writer_class_keys()}
    with caplog.at_level("WARNING"):
        assert _ge40_from_breakdown(zero, 100.0, 1.0) == (None, None)
    assert not [r for r in caplog.records if "no recognised measure key" in r.message]


def test_ratio_is_clamped():
    """A breakdown larger than the reported growing stock must not exceed it."""
    breakdown = {k: {"timber_m3_per_ha": 0.0} for k in _writer_class_keys()}
    ge40_key = next(iter(sorted(_ge40_class_keys())))
    breakdown[ge40_key] = {"timber_m3_per_ha": 500.0}
    per_ha, _ = _ge40_from_breakdown(breakdown, 10.0, 1.0)
    assert per_ha == pytest.approx(10.0)


def test_key_normalisation():
    for raw, want in (
        ("60+", "60_plus"),
        ("60_plus_", "60_plus"),
        ("40-50", "40_50"),
        (" 50_60 ", "50_60"),
        ("Pole (20-30)", "pole_20_30"),
    ):
        assert _norm_class_key(raw) == want, raw
