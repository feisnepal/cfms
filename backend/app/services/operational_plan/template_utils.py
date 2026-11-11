"""
Utilities for auto-generating template metadata (sections_summary, variables_summary).
"""
import re
from typing import List, Set
from .variable_registry import get_all_variables

_VARIABLE_PATTERN = re.compile(r"\{\{(\w+:?\w+)\}\}")


def _walk_tree_titles(tree: list) -> List[str]:
    """Extract all section titles from a tree."""
    titles = []
    for node in tree:
        if isinstance(node, dict):
            title = node.get("title_ne") or node.get("title_en", "")
            if title:
                titles.append(title)
            for child in node.get("children", []):
                titles.extend(_walk_tree_titles([child]))
        else:
            if hasattr(node, "title_ne") and node.title_ne:
                titles.append(node.title_ne)
            elif hasattr(node, "title_en") and node.title_en:
                titles.append(node.title_en)
            if hasattr(node, "children"):
                titles.extend(_walk_tree_titles(node.children))
    return titles


def _extract_variables(tree: list) -> Set[str]:
    """Extract all {{variable}} references from tree content."""
    variables = set()
    for node in tree:
        if isinstance(node, dict):
            content = node.get("content", "")
            if content:
                for m in _VARIABLE_PATTERN.finditer(content):
                    var_name = m.group(1)
                    if var_name.startswith("chart:") or var_name.startswith("map:") or var_name.startswith("table:"):
                        continue
                    variables.add(var_name)
            for child in node.get("children", []):
                variables.update(_extract_variables([child]))
        else:
            if hasattr(node, "content") and node.content:
                for m in _VARIABLE_PATTERN.finditer(node.content):
                    var_name = m.group(1)
                    if var_name.startswith("chart:") or var_name.startswith("map:") or var_name.startswith("table:"):
                        continue
                    variables.add(var_name)
            if hasattr(node, "children"):
                variables.update(_extract_variables(node.children))
    return variables


def generate_template_summaries(tree: list) -> dict:
    """Generate sections_summary and variables_summary from a tree."""
    sections = _walk_tree_titles(tree)
    variables = _extract_variables(tree)

    # Map variable keys to human-readable labels
    registry = {v.key: v for v in get_all_variables()}
    variable_labels = []
    for var_key in sorted(variables):
        var_def = registry.get(var_key)
        label = var_def.label_ne if var_def and var_def.label_ne else var_def.label_en if var_def else var_key
        variable_labels.append(f"{var_key} ({label})" if label != var_key else var_key)

    return {
        "sections_summary": sections,
        "variables_summary": variable_labels,
    }
