"""Plan-scoped variable readiness — WORKSPACE_FLOW_NAV_PLAN §7.1 (phase P0).

Why this module exists
----------------------
Nothing in the system could answer *"which of this plan's variables have no
data for this forest?"* Every existing answer was the wrong shape:

* :meth:`VariableResolver.resolve_node_content` substitutes ``""`` for both an
  unknown key and a key with no data (``variable_resolver.py:343-344`` and
  ``:348-349``). One blank, two different faults.
* :meth:`VariableResolver.resolve_all` resolves the *entire* registry, so it is
  both expensive and unscoped — it reports on variables this plan never uses.
* ``validate_template`` (:mod:`template_validation`) checks only whether a token
  is *lexically* registered. ``unknown_token`` catches a typo; it says nothing
  about whether ``blocks_count`` has a value here.
* ``GET /{calculation_id}/variable-catalog`` exposes ``data_status``, but it is
  forest-scoped rather than plan-scoped and synthesises an unsaved plan.

The consequence was that a statutory document could render a blank where a
measured figure belongs, with nothing anywhere recording that it had.

What it reports
---------------
Four buckets, because "not ready" has distinct causes and a single count would
hide the one the user can actually act on. The tokens are collected from every
surface the document renders — ``content``, the node titles, and the cells of
``static_table`` / ``inline_tables`` (ND-8) — because a token that lives in a
cell is printed by ``_resolve_var_text`` just as plainly as one in the body:

``missing``
    A ``{{token}}`` this plan uses that has **no data** for this forest. The
    user can fix this by going and collecting it.
``unmet_maps``
    A ``{{thememap:…}}`` / ``{{opsmap:…}}`` token whose spec declares
    ``requires`` tags that are not satisfied. Delegated to
    :func:`prereq_check.check_spec`, which is already bilingual and
    three-state, so no parallel type is introduced here.
``unverified``
    A ``{{chart:…}}`` / ``{{table:…}}`` / ``{{map:…}}`` token. ``op_docx_builder``
    dispatches these by prefix and nothing checks whether they will render, so
    they are **counted rather than dropped** — a plan whose only problem is an
    unrenderable chart must not report "all variables resolved". It is
    deliberately **not** part of ``ready`` (ND-8, owner decision 2026-10-19):
    whether a chart renders depends on the builder, not on data the user can go
    and collect, so it is reported but never blocks issuance.
``empty_lists``
    A ``{{token}}`` that resolves to ``[]`` (ND-7, owner decision 2026-10-18).
    The document prints a grey "सूची खाली छ" note for it rather than the red
    "No data", because an empty list is a legitimate state (the owner may
    simply not have designated any protected trees yet) — so it is **reported
    but not blocking**. Before ND-7 an empty list sat in ``missing`` and made
    ``ready`` impossible to reach without data entry the owner had waived.

A token that is not in the registry at all is reported in ``missing`` with
``known: false``, so a typo is distinguishable from absent data.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Iterable, Iterator, List, Optional, Set, Tuple
from uuid import UUID

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

# Token prefixes `resolve_node_content` hands back verbatim for
# `op_docx_builder` to dispatch, rather than substituting a value
# (`variable_resolver.py:340`). Split three ways because the three groups are
# checked three different ways.
MAP_PREFIXES: Tuple[str, ...] = ("thememap:", "opsmap:")
OPAQUE_PREFIXES: Tuple[str, ...] = ("chart:", "map:", "table:", "inline_table:")
FULL_SUFFIX = ":full"


def _iter_cell_strings(obj: Any) -> Iterator[str]:
    """Yield every string leaf of a ``static_table`` / ``inline_tables`` value.

    A static table is a dict whose string leaves are cell text, and
    ``inline_tables`` is a list of the same shape, so the walk follows both.
    ``op_docx_builder`` renders these cells through ``_resolve_var_text``
    (ND-2), independently of ``content`` — so readiness has to walk them or a
    cell-only failure stays invisible.
    """
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for value in obj.values():
            yield from _iter_cell_strings(value)
    elif isinstance(obj, (list, tuple)):
        for value in obj:
            yield from _iter_cell_strings(value)


def _iter_content(tree: Any) -> Iterator[str]:
    """Yield every string this plan renders a ``{{token}}`` from.

    Four surfaces carry tokens: ``content``, the titles (``title_ne`` /
    ``title_en``) and the cell text of ``static_table`` and ``inline_tables``.
    Before ND-8 only ``content`` was walked, so a token that lived in a cell or
    a title was invisible to readiness even though the document printed it.

    ``plan.sections["tree"]`` is a list of plain dicts (the export path converts
    it with ``_dict_list_to_tree``), but callers holding ``TreeNode`` objects
    pass those instead, so both shapes are walked.
    """
    for node in tree or []:
        if isinstance(node, dict):
            for field in ("content", "title_ne", "title_en"):
                value = node.get(field)
                if value:
                    yield value
            yield from _iter_cell_strings(node.get("static_table"))
            yield from _iter_cell_strings(node.get("inline_tables"))
            yield from _iter_content(node.get("children") or [])
        else:
            for field in ("content", "title_ne", "title_en"):
                value = getattr(node, field, None)
                if value:
                    yield value
            yield from _iter_cell_strings(getattr(node, "static_table", None))
            yield from _iter_cell_strings(getattr(node, "inline_tables", None))
            yield from _iter_content(getattr(node, "children", None) or [])


def classify_tokens(tree: Any) -> Tuple[Set[str], Set[str], Set[str]]:
    """Split a plan's ``{{tokens}}`` into (value, map, opaque) sets.

    Deliberately not :func:`template_utils._extract_variables`: that helper
    *discards* ``chart:``/``map:``/``table:`` tokens and keeps
    ``thememap:``/``opsmap:`` as if they were plain values — precisely the
    inverse of what a readiness report needs, and it is why chart failures are
    invisible today.
    """
    from .variable_resolver import VARIABLE_PATTERN

    values: Set[str] = set()
    maps: Set[str] = set()
    opaque: Set[str] = set()
    for content in _iter_content(tree):
        for match in VARIABLE_PATTERN.finditer(content):
            token = match.group(1)
            if token.startswith(MAP_PREFIXES):
                maps.add(token)
            elif token.startswith(OPAQUE_PREFIXES):
                opaque.add(token)
            else:
                values.add(token)
    return values, maps, opaque


def _missing_entry(key: str, known: bool) -> Dict[str, Any]:
    from .variable_registry import VARIABLE_REGISTRY

    var_def = VARIABLE_REGISTRY.get(key)
    if var_def is None and key.startswith("section:") and key.count(":") >= 2:
        # "section:aspect_analysis:full" is the registered "section:aspect_analysis" in its "full" form
        var_def = VARIABLE_REGISTRY.get(key.rsplit(":", 1)[0])
    label_en = (getattr(var_def, "label_en", None) or key) if known else key
    label_ne = (getattr(var_def, "label_ne", None) or key) if known else key
    if known:
        reason_en = f"No data for '{label_en}' ({key}) in this forest."
        reason_ne = f"यस वनमा '{label_ne}' ({key}) को तथ्याङ्क उपलब्ध छैन।"
    else:
        reason_en = f"'{key}' is not a registered variable."
        reason_ne = f"'{key}' दर्ता गरिएको चल होइन।"
    return {
        "key": key,
        "known": known,
        "label_en": label_en,
        "label_ne": label_ne,
        "reason_en": reason_en,
        "reason_ne": reason_ne,
    }


def _empty_list_entry(key: str) -> Dict[str, Any]:
    """A token whose list value is empty (ND-7): reported, but never blocking."""
    from .variable_registry import VARIABLE_REGISTRY

    var_def = VARIABLE_REGISTRY.get(key)
    label_en = (getattr(var_def, "label_en", None) or key)
    label_ne = (getattr(var_def, "label_ne", None) or key)
    return {
        "key": key,
        "label_en": label_en,
        "label_ne": label_ne,
        "reason_en": f"'{label_en}' has no rows yet — an empty list is allowed and does not block the plan.",
        "reason_ne": f"'{label_ne}' मा अहिले कुनै पङ्क्ति छैन — खाली सूची स्वीकार्य छ र योजना रोकिँदैन।",
    }


def _unmet_map_tokens(
    db: Optional[Session], calc_id: Optional[UUID], map_tokens: Iterable[str]
) -> List[Dict[str, Any]]:
    from .prereq_check import check_spec
    from .thematic_map_spec import resolve_spec

    unmet: List[Dict[str, Any]] = []
    for token in sorted(map_tokens):
        # `resolve_spec` splits on the first colon, so a `:full` suffix has to
        # come off before lookup or the key misses the registry.
        key = token[: -len(FULL_SUFFIX)] if token.endswith(FULL_SUFFIX) else token
        try:
            spec = resolve_spec(key)
        except Exception:  # noqa: BLE001 -- a bad spec must not 500 the check
            logger.exception("plan_readiness: could not resolve map spec %s", key)
            spec = None
        if spec is None:
            unmet.append(
                {
                    "token": token,
                    "status": "unavailable",
                    "reason_en": f"Map variable '{token}' is not a registered spec.",
                    "reason_ne": f"नक्सा चल '{token}' दर्ता गरिएको स्पेक होइन।",
                    "hint_en": "",
                    "hint_ne": "",
                }
            )
            continue
        result = check_spec(db, calc_id, spec)
        if not result.met:
            unmet.append(
                {
                    "token": token,
                    "status": result.status,
                    "reason_en": result.reason_en,
                    "reason_ne": result.reason_ne,
                    "hint_en": result.hint_en,
                    "hint_ne": result.hint_ne,
                }
            )
    return unmet


def plan_readiness(
    db: Optional[Session],
    calculation_id: Optional[UUID],
    plan: Any,
    tree: Any = None,
) -> Dict[str, Any]:
    """Report which of *this plan's* variables lack data for this forest.

    :param tree: the document tree. Defaults to ``plan.sections["tree"]``.
    :returns: ``{total, resolved, missing, empty_lists, unverified, unverified_tokens,
        unmet_maps, ready}`` — every human-readable field carries both
        languages, matching :class:`prereq_check.PrereqResult`.

    Never raises. A readiness check that 500s is worse than one that reports
    nothing, because it takes the page down with it.
    """
    try:
        if tree is None:
            sections = getattr(plan, "sections", None) or {}
            # a section nobody has edited is judged on the template's text, so a variable with no data is found even though
            # the stored text already printed "No data" for it (plan_live.py)
            from .plan_live import effective_tree

            tree = effective_tree(sections.get("tree") or [])

        value_tokens, map_tokens, opaque_tokens = classify_tokens(tree)

        resolved: Dict[str, Any] = {}
        if value_tokens:
            from .variable_resolver import VariableResolver

            try:
                resolver = VariableResolver(db, calculation_id, plan)
                resolved = resolver.resolve_keys(sorted(value_tokens))
                # "section:x:full" is not a plain variable: the document builds it from the section generator's narrative
                # (op_docx_builder._add_section_full_docx), so it is available exactly when that narrative is not empty
                full_keys = [k for k in value_tokens if k.startswith("section:") and k.endswith(FULL_SUFFIX)]
                if full_keys:
                    generated = (resolver.get_raw_data() or {}).get("section_generators") or {}
                    for key in full_keys:
                        resolved[key] = generated.get(key[: -len(FULL_SUFFIX)]) or None
            except Exception:  # noqa: BLE001
                logger.exception(
                    "plan_readiness: resolution failed for calculation %s",
                    calculation_id,
                )
                resolved = {}

        missing: List[Dict[str, Any]] = []
        empty_lists: List[Dict[str, Any]] = []
        for key in sorted(value_tokens):
            if key not in resolved:
                missing.append(_missing_entry(key, known=False))
            else:
                val = resolved[key]
                if val is None or (isinstance(val, dict) and not val):
                    # a missing value (or an empty dict) is a genuine gap the user can fill
                    missing.append(_missing_entry(key, known=True))
                elif isinstance(val, list) and not val:
                    # ND-7: an empty list prints a grey "सूची खाली छ" note, not the red "No data" - report it, do not block
                    empty_lists.append(_empty_list_entry(key))

        unmet_maps = _unmet_map_tokens(db, calculation_id, map_tokens)

        total = len(value_tokens)
        return {
            "total": total,
            "resolved": total - len(missing) - len(empty_lists),
            "missing": missing,
            "empty_lists": empty_lists,
            "unverified": len(opaque_tokens),
            "unverified_tokens": sorted(opaque_tokens),
            "unmet_maps": unmet_maps,
            "ready": not missing and not unmet_maps,
        }
    except Exception:  # noqa: BLE001 -- never take the page down
        logger.exception("plan_readiness: unexpected failure")
        return {
            "total": 0,
            "resolved": 0,
            "missing": [],
            "empty_lists": [],
            "unverified": 0,
            "unverified_tokens": [],
            "unmet_maps": [],
            "ready": False,
        }
