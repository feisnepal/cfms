"""OP document tree section numbering in Devanagari script.

Recomputes section/subsection numbers for the entire document tree
when sections are added, removed, or reordered. Supports both Nepali
(Devanagari digits) and English (Arabic digits) numbering.

See also:
    .tree_models.TreeNode — the document tree node model
    .seed_data.get_default_seed_tree — initial tree structure
"""

from typing import List
from .tree_models import TreeNode

DEVANAGARI_DIGITS = {
    0: "०", 1: "१", 2: "२", 3: "३", 4: "४",
    5: "५", 6: "६", 7: "७", 8: "८", 9: "९",
}


def to_devanagari_number(n: int) -> str:
    """Convert an integer to its Devanagari numeral representation."""
    if n == 0:
        return "०"
    result = ""
    while n > 0:
        result = DEVANAGARI_DIGITS[n % 10] + result
        n //= 10
    return result


def _num(n: int, language: str) -> str:
    return to_devanagari_number(n) if language == "NP" else str(n)


def recompute_numbers(tree: List[TreeNode], language: str = "NP") -> None:
    """Recompute section/subsection numbers for the document tree in the given language."""
    section_counter = 0

    for node in list(tree):
        if node.type in ("preamble", "toc"):
            node.number = None
            node.level = 0
            recompute_numbers(node.children, language)

        elif node.type == "section":
            section_counter += 1
            node.number = _num(section_counter, language)
            node.level = 0
            _number_descendants(node, language, 1)

        else:
            recompute_numbers(node.children, language)


def _number_descendants(parent: TreeNode, language: str, depth: int) -> None:
    for i, child in enumerate(parent.children):
        child_num = i + 1
        num_str = _num(child_num, language)
        child.number = f"{parent.number}.{num_str}"
        child.level = depth
        _number_descendants(child, language, depth + 1)
