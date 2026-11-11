"""The "species by regulation group" template section: the fi_reg_* / fi_regc_* tables, bar charts and narration.

Two sibling subsections (all categories: 21 named + Other (Terai/Hill); classified species only: the 21 named). Captions are
unnumbered on purpose: templates such as Rambhadevi number their captions 1..N in document order, and an inserted caption
must not shift or duplicate those.

    section_nodes()                      -> two TreeNode (for seed_data)
    insert_into_tree(tree, parent_title) -> add them to a plain-dict template tree (idempotent), True when changed
"""

import copy
import uuid
from typing import Any, Dict, List, Optional

_NS = uuid.UUID("7c1e4f52-3b8a-4d0e-9a16-5e2b7d9c4a38")
MARKER = "{{fi_regc_species_tree_per_ha_table}}"


def _block(prefix: str, scope_ne: str) -> str:
    p = prefix
    return (
        f"{scope_ne} अनुसार वर्गीकरण गर्दा वनको अवस्था निम्नानुसार रहेको छ ।\n"
        f"{{{{section:{p}_species_narration:full}}}}\n"
        "पुनरुत्पादनको अवस्था (प्रति हेक्टर)\n"
        f"{{{{{p}_species_regen_per_ha_table}}}}\n"
        "पोलको अवस्था (प्रति हेक्टर)\n"
        f"{{{{{p}_species_pole_per_ha_table}}}}\n"
        f"{{{{chart:{p}_species_pole_count_bar}}}}\n"
        f"{{{{chart:{p}_species_pole_volume_bar}}}}\n"
        "रुखको अवस्था (प्रति हेक्टर)\n"
        f"{{{{{p}_species_tree_per_ha_table}}}}\n"
        f"{{{{chart:{p}_species_tree_count_bar}}}}\n"
        f"{{{{chart:{p}_species_tree_volume_bar}}}}\n"
        "सव कम्पार्टमेन्ट अनुसार पुनरुत्पादनको अवस्था\n"
        f"{{{{{p}_unit_species_regen_per_ha_table}}}}\n"
        "सव कम्पार्टमेन्ट अनुसार पोलको अवस्था\n"
        f"{{{{{p}_unit_species_pole_per_ha_table}}}}\n"
        "सव कम्पार्टमेन्ट अनुसार रुखको अवस्था\n"
        f"{{{{{p}_unit_species_tree_per_ha_table}}}}"
    )


# (key, title_ne, title_en, content)
SECTIONS = [
    ("fi_reg", "नियमावली प्रजाति वर्ग अनुसार वनको अवस्था", "Forest Condition by Regulation Species Group",
     _block("fi_reg", "वन नियमावलीले तोकेका २१ प्रजातिलाई नाम अनुसार र अन्य सबै प्रजातिलाई अन्य प्रजाति (तराई वा पहाड)")),
    ("fi_regc", "तोकिएका २१ प्रजाति मात्रको अवस्था", "Designated Species Only",
     _block("fi_regc", "वन नियमावलीले तोकेका २१ प्रजाति मात्र")),
]


def section_nodes() -> List[Any]:
    """TreeNode objects for seed_data (imported lazily: seed_data imports this module)."""
    from .tree_models import TreeNode

    return [
        TreeNode(type="subsection", title_ne=t_ne, title_en=t_en, content=content, content_type="richtext")
        for _k, t_ne, t_en, content in SECTIONS
    ]


def _find(tree: List[Dict[str, Any]], pred) -> Optional[tuple]:
    """(siblings list, index) of the first node satisfying pred, depth first."""
    for i, n in enumerate(tree):
        if pred(n):
            return tree, i
        hit = _find(n.get("children") or [], pred)
        if hit:
            return hit
    return None


def _has_marker(tree: List[Dict[str, Any]]) -> bool:
    return any(MARKER in (n.get("content") or "") or _has_marker(n.get("children") or []) for n in tree)


def insert_into_tree(tree: List[Dict[str, Any]], *, after_token: Optional[str] = None,
                     into_section_title: Optional[str] = None) -> bool:
    """Add the two subsections to a plain-dict tree; False when already there or the anchor is not found.

    after_token: becomes the next siblings of the node whose content holds this token.
    into_section_title: appended as last children of the node with this ``title_ne``.
    """
    if _has_marker(tree):
        return False
    if after_token:
        hit = _find(tree, lambda n: after_token in (n.get("content") or ""))
        if not hit:
            return False
        siblings, idx = hit
        proto, at, level = siblings[idx], idx + 1, siblings[idx].get("level")
    else:
        hit = _find(tree, lambda n: (n.get("title_ne") or "") == into_section_title)
        if not hit:
            return False
        siblings, idx = hit
        parent = siblings[idx]
        parent.setdefault("children", [])
        siblings = parent["children"]
        proto = siblings[-1] if siblings else parent
        at, level = len(siblings), (siblings[-1].get("level") if siblings else (parent.get("level") or 1) + 1)
    for k, t_ne, t_en, content in SECTIONS:
        node = copy.deepcopy(proto)
        for key in list(node):  # a fresh node: keep the shape (all keys) but none of the content
            node[key] = None if key not in ("children", "deleted", "is_locked", "landscape", "is_cover", "restart_pages",
                                            "hidden_in_export", "page_break_before") else node[key]
        node.update({
            "id": str(uuid.uuid5(_NS, f"{k}:{proto.get('id')}")), "type": "subsection", "level": level,
            "title_ne": t_ne, "title_en": t_en, "content": content, "content_type": "richtext", "children": [],
            "deleted": False, "is_locked": False, "landscape": False, "is_cover": False, "restart_pages": False,
            "hidden_in_export": False, "page_break_before": False, "number_sep": proto.get("number_sep"),
        })
        siblings.insert(at, node)
        at += 1
    return True
