"""The unit-access ratchet (FS-0.6): its patterns, its arithmetic, and that the repository passes it."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "check_unit_access.py"
_spec = importlib.util.spec_from_file_location("check_unit_access", _SCRIPT)
gate = importlib.util.module_from_spec(_spec)
sys.modules["check_unit_access"] = gate
_spec.loader.exec_module(gate)


@pytest.mark.parametrize(
    "line",
    [
        "ForestBlock.division_level == 0",
        "(extra_columns->>'division_level')::int <= 1",
        "WHERE division_level IN (0, 1)",
        "ForestBlock.division_level.in_([0, 1])",
        "ForestBlock(division_level=0, index=1)",
        "b.division_level >= 2",
        "(r.division_level or 1) == 2",
        "1 <= division_level",
        "AND division_level > 1",
    ],
)
def test_numeric_level_pattern_catches_a_number_compared_with_the_level(line):
    assert gate.PATTERNS["numeric_level"].search(line)


@pytest.mark.parametrize(
    "line",
    [
        "division_level = level",
        "ForestBlock(division_level=lvl, index=3)",
        "x = row.division_level",
        "'division_level': row.division_level,",
        "sorted(rows, key=lambda r: r.division_level)",
        "division_level == deepest",
    ],
)
def test_numeric_level_pattern_ignores_non_numeric_uses(line):
    assert not gate.PATTERNS["numeric_level"].search(line)


def test_jsonb_array_patterns():
    r, w = gate.PATTERNS["jsonb_array_read"], gate.PATTERNS["jsonb_array_write"]
    assert r.search('rd.get("blocks", [])') and r.search("rd['compartments']")
    assert w.search('new_rd["compartments"] = []') and not w.search('rd["blocks"] == x')
    assert not r.search('"total_blocks": 3')


def test_regressions_flags_only_increases_and_new_files():
    base = {c: {} for c in gate.CATEGORIES}
    base["numeric_level"] = {"a.py": 2}
    cur = {c: {} for c in gate.CATEGORIES}
    cur["numeric_level"] = {"a.py": 2, "b.py": 1}
    assert gate.regressions(cur, base) == ["numeric_level: b.py has 1 (baseline 0)"]
    cur["numeric_level"] = {"a.py": 1}
    assert gate.regressions(cur, base) == []  # going DOWN is the point


def test_the_repository_passes_its_own_gate():
    assert gate.regressions(gate.scan(), gate.load_baseline()) == []


def test_the_units_module_and_the_orm_model_are_exempt():
    assert "backend/app/services/forest_units/" in gate.ALLOWED_PREFIXES
    assert "backend/app/models/forest_block.py" in gate.ALLOWED_PREFIXES
