"""
Comprehensive tests for Operational Plan service layer
Run: python -m app.services.operational_plan.tests
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))

from typing import List
from app.services.operational_plan.tree_models import TreeNode, TreeOperations
from app.services.operational_plan.auto_numbering import recompute_numbers, to_devanagari_number
from app.services.operational_plan.seed_data import get_full_seed_document, get_default_seed_tree
from app.services.operational_plan.variable_registry import (
    VARIABLE_REGISTRY, get_all_variables, get_variable,
    get_variables_by_category, search_variables,
)


passed = 0
failed = 0
errors = []


def test(name: str, fn):
    """Run a named test function with pass/fail tracking."""
    global passed, failed
    try:
        fn()
        passed += 1
        print(f"  ✓ {name}")
    except Exception as e:
        failed += 1
        msg = f"  ✗ {name}: {e}"
        errors.append(msg)
        print(msg)


def assert_eq(a, b, msg=""):
    """Assert two values are equal with optional error message."""
    if a != b:
        raise AssertionError(f"{msg}: expected {b!r}, got {a!r}")


# ═══════════════════════════════════════
# 1. TreeNode basics
# ═══════════════════════════════════════
def test_treenode_creation():
    """Test TreeNode initialization with default values."""
    n = TreeNode(title_ne="Test", type="section")
    assert n.id and len(n.id) > 0
    assert n.title_ne == "Test"
    assert n.type == "section"
    assert n.content_type == "richtext"
    assert n.is_locked == False
    assert n.hidden_in_export == False
    assert n.children == []
    n.touch()
    assert n.last_modified is not None


def test_treenode_with_children():
    """Test TreeNode with child nodes attached."""
    child = TreeNode(title_ne="Child", type="subsection")
    parent = TreeNode(title_ne="Parent", type="section", children=[child])
    assert len(parent.children) == 1
    assert parent.children[0].id == child.id


def test_treenode_to_from_dict():
    """Test TreeNode serialization to dict and back."""
    n = TreeNode(title_ne="Hello", type="section", number="१")
    d = n.model_dump()
    assert d["title_ne"] == "Hello"
    assert d["number"] == "१"
    n2 = TreeNode.from_dict(d)
    assert n2.title_ne == "Hello"
    assert n2.number == "१"


# ═══════════════════════════════════════
# 2. TreeOperations
# ═══════════════════════════════════════
def test_find_node():
    """Test TreeOperations.find_node by node ID."""
    c1 = TreeNode(title_ne="C1")
    c2 = TreeNode(title_ne="C2")
    p = TreeNode(title_ne="P", children=[c1, c2])
    tree = [p]

    found = TreeOperations.find_node(tree, c1.id)
    assert found is not None
    assert found.title_ne == "C1"

    found = TreeOperations.find_node(tree, c2.id)
    assert found.title_ne == "C2"

    found = TreeOperations.find_node(tree, "nonexistent")
    assert found is None


def test_find_parent():
    """Test TreeOperations.find_parent to locate the parent of a child node."""
    c = TreeNode(title_ne="Child")
    p = TreeNode(title_ne="Parent", children=[c])
    tree = [p]

    parent = TreeOperations.find_parent(tree, c.id)
    assert parent is not None
    assert parent.title_ne == "Parent"

    parent = TreeOperations.find_parent(tree, p.id)
    assert parent is None


def test_add_node_root():
    """Test adding a node at the root level of an empty tree."""
    tree: List[TreeNode] = []
    n = TreeNode(title_ne="New")
    tree = TreeOperations.add_node(tree, None, n)
    assert len(tree) == 1
    assert tree[0].id == n.id


def test_add_node_child():
    """Test adding a child node under an existing parent."""
    p = TreeNode(title_ne="Parent")
    tree = [p]
    c = TreeNode(title_ne="Child")
    tree = TreeOperations.add_node(tree, p.id, c)
    assert len(p.children) == 1
    assert p.children[0].id == c.id


def test_add_node_position():
    """Test adding a node at a specific position among siblings."""
    tree = [TreeNode(title_ne="A"), TreeNode(title_ne="B")]
    c = TreeNode(title_ne="C")
    tree = TreeOperations.add_node(tree, None, c, position=1)
    assert tree[1].title_ne == "C"


def test_update_node():
    """Test updating a node's properties (title, content)."""
    n = TreeNode(title_ne="Old")
    tree = [n]
    tree = TreeOperations.update_node(tree, n.id, {"title_ne": "New", "content": "Hello"})
    assert n.title_ne == "New"
    assert n.content == "Hello"


def test_delete_node():
    """Test deleting a node from the tree."""
    n = TreeNode(title_ne="Delete Me")
    tree = [n]
    tree = TreeOperations.delete_node(tree, n.id)
    assert len(tree) == 0


def test_delete_locked_node_fails():
    """Test that deleting a locked node raises ValueError."""
    n = TreeNode(title_ne="Locked", is_locked=True)
    tree = [n]
    try:
        TreeOperations.delete_node(tree, n.id)
        assert False, "Should have raised ValueError"
    except ValueError:
        pass


def test_flatten():
    """Test TreeOperations.flatten returns all nodes in depth-first order."""
    c = TreeNode(title_ne="C")
    p = TreeNode(title_ne="P", children=[c])
    g = TreeNode(title_ne="G", children=[p])
    tree = [g]
    flat = TreeOperations.flatten(tree)
    assert len(flat) == 3
    assert flat[0].title_ne == "G"
    assert flat[1].title_ne == "P"
    assert flat[2].title_ne == "C"


# ═══════════════════════════════════════
# 3. Auto-numbering
# ═══════════════════════════════════════
def test_devanagari_digits():
    """Test Devanagari number conversion for various integers."""
    assert to_devanagari_number(0) == "०"
    assert to_devanagari_number(1) == "१"
    assert to_devanagari_number(10) == "१०"
    assert to_devanagari_number(25) == "२५"
    assert to_devanagari_number(100) == "१००"


def test_recompute_numbers_flat():
    """Test auto-numbering assigns sequential Devanagari numbers to flat sections."""
    tree = [
        TreeNode(title_ne="A", type="section"),
        TreeNode(title_ne="B", type="section"),
        TreeNode(title_ne="C", type="section"),
    ]
    recompute_numbers(tree, language="NP")
    assert tree[0].number == "१"
    assert tree[1].number == "२"
    assert tree[2].number == "३"


def test_recompute_numbers_nested():
    """Test auto-numbering produces hierarchical decimal numbering for nested sections."""
    c1 = TreeNode(title_ne="C1", type="subsection")
    c2 = TreeNode(title_ne="C2", type="subsection")
    p = TreeNode(title_ne="P", type="section", children=[c1, c2])
    tree = [p]
    recompute_numbers(tree, language="NP")
    assert p.number == "१"
    assert p.children[0].number == "१.१"
    assert p.children[1].number == "१.२"


def test_recompute_preamble():
    """Test that preamble sections are not numbered."""
    tree = [
        TreeNode(title_ne="Preamble", type="preamble"),
        TreeNode(title_ne="Section", type="section"),
    ]
    recompute_numbers(tree, language="NP")
    assert tree[0].number is None
    assert tree[1].number == "१"


def test_recompute_english():
    """Test English numbering mode produces Arabic numerals."""
    tree = [
        TreeNode(title_ne="S1", type="section"),
        TreeNode(title_ne="S2", type="section"),
    ]
    recompute_numbers(tree, language="EN")
    assert tree[0].number == "1"
    assert tree[1].number == "2"


# ═══════════════════════════════════════
# 4. Seed data
# ═══════════════════════════════════════
def test_seed_data_structure():
    """Test the seed document contains sections, preambles, and schedules."""
    tree = get_full_seed_document()
    assert len(tree) > 0, "Seed tree should not be empty"
    assert any(n.type == "section" for n in tree), "Should have sections"
    assert any(n.type == "preamble" for n in tree), "Should have preambles"
    assert any("अनुसूची" in n.title_ne for n in tree), "Should have schedules"


def test_seed_data_auto_number():
    """Test that seed document sections are correctly auto-numbered."""
    tree = get_full_seed_document()
    recompute_numbers(tree, language="NP")
    sections = [n for n in TreeOperations.flatten(tree) if n.type == "section"]
    assert sections[0].number == "१"
    assert sections[-1].number is not None


def test_seed_data_variables_present():
    """Test that all variables used in seed data exist in the registry."""
    tree = get_full_seed_document()
    import re
    pattern = re.compile(r"\{\{(\w+:?\w+)\}\}")
    for node in TreeOperations.flatten(tree):
        if node.content:
            matches = pattern.findall(node.content)
            for var in matches:
                if var.startswith("chart:") or var.startswith("table:"):
                    continue
                if var not in VARIABLE_REGISTRY:
                    raise AssertionError(f"Variable {var!r} used in seed data but not in registry")


# ═══════════════════════════════════════
# 5. Variable Registry
# ═══════════════════════════════════════
def test_registry_count():
    """Test the variable registry contains at least 150 entries."""
    vars = get_all_variables()
    assert len(vars) >= 150, f"Expected >= 150 variables, got {len(vars)}"


def test_registry_categories():
    """Test all six categories (A-F) have at least one variable."""
    for cat in ["A", "B", "C", "D", "E", "F"]:
        vars = get_variables_by_category(cat)
        assert len(vars) > 0, f"Category {cat} should have at least 1 variable"


def test_registry_search():
    """Test variable search by keyword returns results."""
    results = search_variables("forest")
    assert len(results) > 0


def test_registry_get():
    """Test get_variable returns correct variable for existing key and None for missing key."""
    v = get_variable("forest_name")
    assert v is not None
    assert v.category == "A"
    assert v.label_ne == "वनको नाम"

    v = get_variable("nonexistent")
    assert v is None


def test_registry_hybrid():
    """Test hybrid category B variables have resolve_hybrid resolver."""
    v = get_variable("altitude_mean_m")
    assert v is not None
    assert v.category == "B"
    assert v.resolver == "resolve_hybrid"


def test_registry_user_input():
    """Test user input category C variables have auto_populate set to False."""
    v = get_variable("plan_year_start")
    assert v is not None
    assert v.category == "C"
    assert v.auto_populate == False


def test_registry_computed():
    """Test computed category D variables have a compute_fn."""
    v = get_variable("total_plan_area_ha")
    assert v is not None
    assert v.category == "D"
    assert v.compute_fn is not None


def test_registry_no_duplicates():
    """Test that no duplicate variable keys exist in the registry."""
    keys = [v.key for v in get_all_variables()]
    assert len(keys) == len(set(keys)), "Duplicate variable keys found!"


# ═══════════════════════════════════════
# 6. Complex scenarios
# ═══════════════════════════════════════
def test_complex_tree_operations():
    """Test complex tree operations (add, move, delete) on the full seed document."""
    tree = get_full_seed_document()
    recompute_numbers(tree)

    # Add a new section
    n = TreeNode(title_ne="नयाँ परिच्छेद", type="section")
    tree = TreeOperations.add_node(tree, None, n)
    recompute_numbers(tree)
    assert n.number is not None
    assert n.number != ""

    # Add a child subsection
    c = TreeNode(title_ne="नयाँ उप-परिच्छेद", type="subsection")
    tree = TreeOperations.add_node(tree, n.id, c)
    recompute_numbers(tree)
    assert c.number is not None
    assert "." in c.number

    # Delete the child
    flat_before = len(TreeOperations.flatten(tree))
    tree = TreeOperations.delete_node(tree, c.id)
    flat_after = len(TreeOperations.flatten(tree))
    assert flat_after == flat_before - 1

    # Move node
    first_section = [n for n in tree if n.type == "section"][0]
    tree = TreeOperations.move_node(tree, n.id, first_section.id, 0)
    assert n in first_section.children


def test_variable_count_by_category():
    """Test exact variable counts per category match expected values."""
    counts = {}
    for v in get_all_variables():
        counts[v.category] = counts.get(v.category, 0) + 1
    assert counts.get("A", 0) >= 100, f"Category A should have >=100 variables, got {counts.get('A', 0)}"
    assert counts.get("B", 0) == 11, f"Category B should have 11 variables, got {counts.get('B', 0)}"
    assert counts.get("C", 0) == 21, f"Category C should have 21 variables, got {counts.get('C', 0)}"
    assert counts.get("D", 0) == 10, f"Category D should have 10 variables, got {counts.get('D', 0)}"
    assert counts.get("E", 0) == 5, f"Category E should have 5 variables, got {counts.get('E', 0)}"
    assert counts.get("F", 0) == 6, f"Category F should have 6 variables, got {counts.get('F', 0)}"


# ═══════════════════════════════════════
# Run tests
# ═══════════════════════════════════════
if __name__ == "__main__":
    print(f"\n{'='*60}")
    print(f"  Operational Plan — Service Layer Tests")
    print(f"{'='*60}\n")

    test("TreeNode creation", test_treenode_creation)
    test("TreeNode with children", test_treenode_with_children)
    test("TreeNode to/from dict", test_treenode_to_from_dict)

    test("TreeOperations: find_node", test_find_node)
    test("TreeOperations: find_parent", test_find_parent)
    test("TreeOperations: add_node root", test_add_node_root)
    test("TreeOperations: add_node child", test_add_node_child)
    test("TreeOperations: add_node position", test_add_node_position)
    test("TreeOperations: update_node", test_update_node)
    test("TreeOperations: delete_node", test_delete_node)
    test("TreeOperations: delete locked node fails", test_delete_locked_node_fails)
    test("TreeOperations: flatten", test_flatten)

    test("Auto-numbering: Devanagari digits", test_devanagari_digits)
    test("Auto-numbering: flat sections", test_recompute_numbers_flat)
    test("Auto-numbering: nested sections", test_recompute_numbers_nested)
    test("Auto-numbering: preamble", test_recompute_preamble)
    test("Auto-numbering: English", test_recompute_english)

    test("Seed data: structure", test_seed_data_structure)
    test("Seed data: auto-number", test_seed_data_auto_number)
    test("Seed data: variables in registry", test_seed_data_variables_present)

    test("Registry: count >= 150", test_registry_count)
    test("Registry: all 6 categories populated", test_registry_categories)
    test("Registry: search", test_registry_search)
    test("Registry: get_variable", test_registry_get)
    test("Registry: hybrid variables", test_registry_hybrid)
    test("Registry: user input variables", test_registry_user_input)
    test("Registry: computed variables", test_registry_computed)
    test("Registry: no duplicate keys", test_registry_no_duplicates)

    test("Complex: full tree operations", test_complex_tree_operations)
    test("Complex: variable counts by category", test_variable_count_by_category)

    print(f"\n{'='*60}")
    total = passed + failed
    print(f"  Results: {passed}/{total} passed", end="")
    if failed > 0:
        print(f", {failed} FAILED")
        for e in errors:
            print(f"  {e}")
    else:
        print(" — ALL TESTS PASSED! ✓")
    print(f"{'='*60}\n")
