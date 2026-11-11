"""Template-owned cover page (OP_MULTI_TEMPLATE_PLAN.md §3.9).

A template may carry its own cover page: exactly one top-level tree node with
``is_cover = True``. When present, the DOCX builder and the HTML preview render
that node as page 1 (its own frame) and skip the built-in hardcoded cover.
When absent, the built-in ``_add_cover_page`` / hardcoded HTML block is used
unchanged.

``ensure_cover_node`` keeps the "exactly one cover node" invariant: it is called
on template create / clone / save-as, and by the one-time backfill
(migration 070) over existing template trees.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

# Seed content by op_plan_kinds.cover_style — used only when a brand-new cover
# node has to be created (no preamble node to promote). Real cover layouts are
# supplied later per D2b; these are sensible starting points.
DEFAULT_COVER_BY_STYLE: Dict[str, Dict[str, str]] = {
    "sustainable": {
        "title_ne": "दिगो वन व्यवस्थापन योजना",
        "title_en": "Sustainable Forest Management Plan",
        "content": (
            "{{forest_name}}\n"
            "{{district}} जिल्ला, {{municipality}}\n\n"
            "दिगो वन व्यवस्थापन योजना\n"
            "आ.व. {{plan_year_start}} देखि आ.व. {{plan_year_end}} सम्म"
        ),
    },
    "brief": {
        "title_ne": "संक्षिप्त वन व्यवस्थापन योजना",
        "title_en": "Brief Forest Management Plan",
        "content": (
            "{{forest_name}}\n"
            "{{district}} जिल्ला, {{municipality}}\n\n"
            "संक्षिप्त वन व्यवस्थापन योजना\n"
            "आ.व. {{plan_year_start}} देखि आ.व. {{plan_year_end}} सम्म"
        ),
    },
    "scientific": {
        "title_ne": "वैज्ञानिक वन व्यवस्थापन योजना",
        "title_en": "Scientific Forest Management Plan",
        "content": (
            "{{forest_name}}\n"
            "{{district}} जिल्ला, {{municipality}}\n\n"
            "वैज्ञानिक वन व्यवस्थापन योजना\n"
            "आ.व. {{plan_year_start}} देखि आ.व. {{plan_year_end}} सम्म"
        ),
    },
}

GENERIC_COVER = {
    "title_ne": "वन व्यवस्थापन कार्ययोजना",
    "title_en": "Forest Management Operational Plan",
    "content": (
        "{{forest_name}}\n"
        "{{district}} जिल्ला, {{municipality}}\n\n"
        "आ.व. {{plan_year_start}} देखि आ.व. {{plan_year_end}} सम्म"
    ),
}


def _is_cover(node: Any) -> bool:
    if isinstance(node, dict):
        return bool(node.get("is_cover"))
    return bool(getattr(node, "is_cover", False))


def _get(node: Any, key: str, default=None):
    if isinstance(node, dict):
        return node.get(key, default)
    return getattr(node, key, default)


def find_cover_node(tree: List[Any]) -> Optional[Any]:
    """First top-level node flagged is_cover (covers only live at the top)."""
    for n in tree or []:
        if _is_cover(n):
            return n
    return None


def partition_cover(tree: List[Any]) -> Tuple[Optional[Any], List[Any]]:
    """(cover_node_or_None, body_tree) where body_tree is the top level with the
    cover node removed. The list is a new list; nodes are the same objects."""
    cover = None
    body: List[Any] = []
    for n in tree or []:
        if cover is None and _is_cover(n):
            cover = n
            continue
        body.append(n)
    return cover, body


def _seed_cover_dict(cover_style: Optional[str]) -> Dict[str, Any]:
    seed = DEFAULT_COVER_BY_STYLE.get(cover_style or "", GENERIC_COVER)
    return {
        "id": "node_cover",
        "type": "preamble",
        "title_ne": seed["title_ne"],
        "title_en": seed["title_en"],
        "number": None,
        "level": 0,
        "content_type": "richtext",
        "content": seed["content"],
        "children": [],
        "is_locked": False,
        "hidden_in_export": False,
        "deleted": False,
        "is_cover": True,
        "cover_meta": {"border_style": "double", "align": "center"},
    }


def ensure_cover_node(
    tree: List[Dict[str, Any]], cover_style: Optional[str] = None
) -> List[Dict[str, Any]]:
    """Return `tree` (list of dicts) with the "exactly one cover node" invariant:

    - already exactly one is_cover node -> unchanged
    - more than one -> keep the first, clear is_cover on the rest
    - none -> promote the first top-level ``preamble`` node, else prepend a
      seeded cover node

    Also sets ``page_break_before = True`` on the node that follows the cover so
    the body starts on a fresh page in renderers that honour that flag.
    """
    if not isinstance(tree, list):
        return tree

    cover_idxs = [
        i for i, n in enumerate(tree) if isinstance(n, dict) and n.get("is_cover")
    ]

    if len(cover_idxs) == 1:
        idx = cover_idxs[0]
    elif len(cover_idxs) > 1:
        for i in cover_idxs[1:]:
            tree[i]["is_cover"] = False
        idx = cover_idxs[0]
    else:
        promote = next(
            (
                i
                for i, n in enumerate(tree)
                if isinstance(n, dict)
                and n.get("type") == "preamble"
                and not n.get("deleted")
            ),
            None,
        )
        if promote is not None:
            tree[promote]["is_cover"] = True
            tree[promote].setdefault(
                "cover_meta", {"border_style": "double", "align": "center"}
            )
            idx = promote
        else:
            tree.insert(0, _seed_cover_dict(cover_style))
            idx = 0

    if idx + 1 < len(tree) and isinstance(tree[idx + 1], dict):
        tree[idx + 1]["page_break_before"] = True

    return tree
