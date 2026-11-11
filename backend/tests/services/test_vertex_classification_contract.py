"""VR-2 — backend half of the vertex-classification CONTRACT.

Reads ``tests/fixtures/vertex_contract.json`` at the repo root, the SAME file
`frontend/src/lib/__tests__/vertexClassifier.contract.test.ts` reads, and
asserts the backend engine produces exactly the recorded index sets.

Why this exists: every bug in this feature so far was two components
disagreeing about the same coordinate — the marker key space (F-5), the
partner search radius (F-8), the capture precision (F-9), the parent-shell
anchor (F-10).  The frontend classifier is a hand-written mirror of this
module, and nothing forced the two to agree.  Changing one without the other
now fails CI on both sides instead of in the browser.
"""
import json
from pathlib import Path

import pytest

from app.services.vertex_classification_service import classify_vertices

# backend/tests/services/… → repo root
FIXTURE = Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "vertex_contract.json"


def _load_cases():
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    return data["cases"]


CASES = _load_cases()


def test_fixture_is_reachable_and_populated():
    assert FIXTURE.exists(), f"contract fixture missing at {FIXTURE}"
    assert len(CASES) >= 8
    # Every case must carry the fields both sides consume.
    for case in CASES:
        for key in ("name", "layer_type", "geometry", "expected"):
            assert key in case, f"{case.get('name', '?')} missing '{key}'"


@pytest.mark.parametrize("case", CASES, ids=[c["name"] for c in CASES])
def test_backend_matches_the_contract(case):
    result = classify_vertices(
        case["geometry"],
        case["layer_type"],
        case.get("same_level_features") or [],
        parent_shell=case.get("parent_shell"),
    )
    expected = case["expected"]
    assert result["shared"] == expected["shared"], f"{case['name']}: shared"
    assert result["shell"] == expected["shell"], f"{case['name']}: shell"
    assert result["editable"] == expected["editable"], f"{case['name']}: editable"
    assert result["vertex_count"] == expected["vertex_count"], f"{case['name']}: vertex_count"


def test_holes_contribute_no_indices():
    """D-3 pinned directly: the hole ring must not appear in the index space."""
    case = next(c for c in CASES if c["name"] == "polygon_with_hole")
    rings = case["geometry"]["coordinates"]
    assert len(rings) == 2, "fixture must actually contain a hole"
    result = classify_vertices(
        case["geometry"], case["layer_type"], case["same_level_features"],
        parent_shell=case.get("parent_shell"),
    )
    # 4 exterior corners only — never 8.
    assert result["vertex_count"] == 4


def test_multipolygon_indices_run_across_parts_in_order():
    case = next(c for c in CASES if c["name"] == "multipolygon_two_parts")
    result = classify_vertices(
        case["geometry"], case["layer_type"], case["same_level_features"],
        parent_shell=case.get("parent_shell"),
    )
    assert result["vertex_count"] == 8
    # Only the second part touches the neighbour → indices 4..7, not 0..3.
    assert all(i >= 4 for i in result["shared"])
