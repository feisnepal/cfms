"""
Route-level tests for Operational Plan endpoints
Verifies all routes are registered and variable/table schemas work.
"""
import sys
import os
import asyncio
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.main import app
from app.services.operational_plan.variable_registry import (
    get_all_variables, get_variables_by_category,
    get_variable, search_variables,
)
from app.services.operational_plan.tree_models import TreeNode, TreeOperations
from app.services.operational_plan.auto_numbering import recompute_numbers
from app.services.operational_plan.seed_data import get_full_seed_document

passed = 0
failed = 0


def test(name, fn):
    global passed, failed
    try:
        fn()
        passed += 1
        print(f"  ✓ {name}")
    except Exception as e:
        failed += 1
        print(f"  ✗ {name}: {e}")


async def _run_async(fn, *args, **kwargs):
    return await fn(*args, **kwargs)


# ═══════════════════════════════════════
# Variable Registry Tests
# ═══════════════════════════════════════
def test_list_variables():
    vars = get_all_variables()
    assert len(vars) >= 150


def test_filter_category_a():
    vars = get_variables_by_category("A")
    assert len(vars) >= 100


def test_filter_category_c():
    vars = get_variables_by_category("C")
    assert len(vars) >= 40


def test_get_variable():
    v = get_variable("forest_name")
    assert v is not None and v.key == "forest_name" and v.category == "A"


def test_variable_not_found():
    assert get_variable("nonexistent") is None


def test_forest_district_variable():
    v = get_variable("forest_district")
    assert v is not None and v.category == "C" and v.var_type == "string"


def test_ug_district_variable():
    v = get_variable("ug_district")
    assert v is not None and v.category == "C" and v.var_type == "string"


def test_district_variable():
    v = get_variable("district")
    assert v is not None and v.category == "A" and v.var_type == "string"


def test_search():
    results = search_variables("elevation")
    assert len(results) > 0 and any("elevation" in r.key for r in results)


# ═══════════════════════════════════════
# Route Registration
# ═══════════════════════════════════════
def test_all_routes_registered():
    patterns = [
        "/api/operational-plans",
        "/api/operational-plans/calculation/",
        "/api/operational-plans/variables",
        "/api/operational-plans/variables/",
        "/api/operational-plans/{plan_id}",
        "/api/operational-plans/{plan_id}/tree",
        "/api/operational-plans/{plan_id}/tree/nodes",
        "/api/operational-plans/{plan_id}/tree/nodes/{node_id}",
        "/api/operational-plans/{plan_id}/tree/reorder",
        "/api/operational-plans/{plan_id}/auto-populate",
        "/api/operational-plans/{plan_id}/metadata-form",
        "/api/operational-plans/locations/districts",
        "/api/operational-plans/locations/municipalities-by-district",
        "/api/operational-plans/locations/wards-by-district",
        "/api/operational-plans/locations/physiography-by-district",
        "/api/op-tables",
        "/api/op-tables/{table_id}",
        "/api/op-tables/{table_id}/data",
        "/api/op-tables/{table_id}/auto-populate",
    ]
    paths = [str(r.path) for r in app.routes if hasattr(r, "path")]
    for p in patterns:
        assert any(p in rp for rp in paths), f"Missing: {p}"


# ═══════════════════════════════════════
# Async endpoint smoke tests
# ═══════════════════════════════════════
def test_variable_endpoint():
    from app.api.operational_plans import list_variables
    result = asyncio.run(_run_async(list_variables, category=None, search=None))
    assert "total" in result and "variables" in result
    assert result["total"] >= 150


def test_variable_endpoint_filtered():
    from app.api.operational_plans import list_variables
    result = asyncio.run(_run_async(list_variables, category="C", search=None))
    assert result["total"] >= 40


def test_variable_detail():
    from app.api.operational_plans import get_variable_detail
    result = asyncio.run(_run_async(get_variable_detail, "forest_name"))
    assert result.key == "forest_name"


def test_table_catalog():
    from app.api.op_table_catalog import list_op_tables
    result = asyncio.run(_run_async(list_op_tables))
    # Catalog has grown beyond the original 32 entries; guard against accidental
    # removal while tolerating legitimate additions.
    assert len(result.tables) >= 32


def test_table_detail():
    from app.api.op_table_catalog import get_op_table
    result = asyncio.run(_run_async(get_op_table, "table_5"))
    assert result.table_id == "table_5" and result.title_en == "Block Details"


def test_table_not_found():
    from app.api.op_table_catalog import get_op_table
    from fastapi import HTTPException
    try:
        asyncio.run(_run_async(get_op_table, "table_99"))
        assert False, "Should have raised 404"
    except HTTPException as e:
        assert e.status_code == 404


# ═══════════════════════════════════════
# Seed data round-trip
# ═══════════════════════════════════════
def test_seed_data_roundtrip():
    tree = get_full_seed_document()
    recompute_numbers(tree, language="NP")
    dicts = [n.model_dump() for n in tree]
    restored = [TreeNode.from_dict(d) for d in dicts]
    assert len(restored) == len(tree)
    for orig, rest in zip(tree, restored):
        assert orig.id == rest.id and orig.title_ne == rest.title_ne


if __name__ == "__main__":
    print(f"\n{'='*60}")
    print(f"  Operational Plan — API & Route Tests")
    print(f"{'='*60}\n")

    test("List all variables (>=150)", test_list_variables)
    test("Filter variables by category A", test_filter_category_a)
    test("Filter variables by category C (21)", test_filter_category_c)
    test("Get variable (forest_name)", test_get_variable)
    test("Variable not found", test_variable_not_found)
    test("Forest district variable (Category C)", test_forest_district_variable)
    test("UG district variable (Category C)", test_ug_district_variable)
    test("District system variable (Category A)", test_district_variable)
    test("Search variables (elevation)", test_search)
    test("All OP routes registered", test_all_routes_registered)
    test("Variable endpoint (async)", test_variable_endpoint)
    test("Variable endpoint filtered C", test_variable_endpoint_filtered)
    test("Variable detail endpoint", test_variable_detail)
    test("Table catalog (32 tables)", test_table_catalog)
    test("Table detail (table_5)", test_table_detail)
    test("Table not found (404)", test_table_not_found)
    test("Seed data round-trip", test_seed_data_roundtrip)

    total = passed + failed
    print(f"\n{'='*60}")
    print(f"  Results: {passed}/{total} passed", end="")
    if failed > 0:
        print(f", {failed} FAILED")
    else:
        print(" — ALL TESTS PASSED! ✓")
    print(f"{'='*60}\n")
    sys.exit(1 if failed > 0 else 0)
