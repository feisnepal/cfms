"""Template validation gate (OP_MULTI_TEMPLATE_PLAN.md §3.4).

Runs on submit, again inside approve/publish, and on demand from the
designer. Returns structured errors (block submit + publish) and warnings
(super admin may override).

The single highest-value check: every ``{{token}}`` in node content must
resolve against ``VARIABLE_REGISTRY`` — an unknown token renders as a silent
blank in a statutory document. ``{{chart:x}}`` / ``{{map:x}}`` / ``{{table:x}}``
are all registered with their prefixed key, so one lookup covers every kind.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from .variable_registry import VARIABLE_REGISTRY
from . import plan_kinds as plan_kinds_service

# Mirror the resolver's canonical pattern so we flag exactly what it would
# try (and fail) to resolve at render time.
_TOKEN_RE = re.compile(r"\{\{(\w+(?::\w+)*)\}\}")

VALID_NODE_TYPES = {"preamble", "toc", "section", "subsection", "appendix"}
VALID_CONTENT_TYPES = {"richtext", "chart", "table", "map", "static_table"}

MAX_DEPTH = 4


def _issue(
    severity: str,
    code: str,
    message: str,
    *,
    node_id: str | None = None,
    token: str | None = None,
) -> Dict[str, Any]:
    return {
        "severity": severity,
        "code": code,
        "message": message,
        "node_id": node_id,
        "token": token,
    }


def _as_dict(node: Any) -> Dict[str, Any]:
    if isinstance(node, dict):
        return node
    if hasattr(node, "model_dump"):
        return node.model_dump()
    return dict(node)


def _walk(nodes: List[Any], depth: int = 0):
    for n in nodes or []:
        d = _as_dict(n)
        yield d, depth
        yield from _walk(d.get("children") or [], depth + 1)


def _token_is_known(token: str) -> bool:
    # {{inline_table:N}} places the node's N-th inline table (the builder places it; it is not a data variable)
    if re.fullmatch(r"inline_table:\d+", token):
        return True
    base = token[:-5] if token.endswith(":full") else token
    if base in VARIABLE_REGISTRY:
        return True
    # `a:b:full` style already handled; also accept a bare prefixless key that
    # the registry stores prefixed is NOT a thing — registry keys are exact.
    return False


def _flag_map_variable(token: str, nid: str | None, warnings: List) -> None:
    """Advisory for a `thememap:`/`opsmap:` map variable used in a template
    (THEMATIC_MAP_VARIABLES_PLAN §3.9.1). A 🔴 (capability-not-in-the-system)
    variable is a warning, not an error — the map renders a placeholder and a
    designer may legitimately include it ahead of the data."""
    from .thematic_map_spec import resolve_spec

    spec = resolve_spec(token)
    if spec is None:
        warnings.append(
            _issue(
                "warning",
                "map_variable_unknown",
                f"Map variable '{token}' is not a registered spec.",
                node_id=nid,
                token=token,
            )
        )
        return
    try:
        from .prereq_check import NOT_AVAILABLE_TAGS

        red = sorted(set(spec.requires or []) & set(NOT_AVAILABLE_TAGS))
    except Exception:  # noqa: BLE001
        red = []
    if red:
        warnings.append(
            _issue(
                "warning",
                "map_variable_not_available",
                f"Map variable '{token}' needs a capability not in the system yet "
                f"({', '.join(red)}); it will render a 'data not available' note.",
                node_id=nid,
                token=token,
            )
        )


def _check_typed_node_ref(d: Dict[str, Any], errors: List, warnings: List) -> None:
    ct = d.get("content_type")
    nid = d.get("id")
    if ct == "chart":
        ck = d.get("chart_type")
        if not ck:
            errors.append(
                _issue(
                    "error",
                    "chart_node_no_type",
                    "Chart node has no chart_type.",
                    node_id=nid,
                )
            )
        else:
            key = ck if ck.startswith("chart:") else f"chart:{ck}"
            if key not in VARIABLE_REGISTRY:
                warnings.append(
                    _issue(
                        "warning",
                        "chart_type_unknown",
                        f"Chart type '{ck}' is not in the registry — "
                        f"verify it renders.",
                        node_id=nid,
                        token=ck,
                    )
                )
    elif ct == "map":
        mk = d.get("map_type")
        if not mk:
            errors.append(
                _issue(
                    "error",
                    "map_node_no_type",
                    "Map node has no map_type.",
                    node_id=nid,
                )
            )
        elif mk.startswith(("thememap:", "opsmap:")):
            _flag_map_variable(mk, nid, warnings)
        else:
            key = mk if mk.startswith("map:") else f"map:{mk}"
            if key not in VARIABLE_REGISTRY:
                warnings.append(
                    _issue(
                        "warning",
                        "map_type_unknown",
                        f"Map type '{mk}' is not in the registry.",
                        node_id=nid,
                        token=mk,
                    )
                )
    elif ct == "table":
        tk = d.get("table_id")
        if not tk and not d.get("static_table"):
            errors.append(
                _issue(
                    "error",
                    "table_node_no_ref",
                    "Table node has neither table_id nor static_table.",
                    node_id=nid,
                )
            )
        elif tk:
            key = tk if tk.startswith("table:") else f"table:{tk}"
            if key not in VARIABLE_REGISTRY:
                warnings.append(
                    _issue(
                        "warning",
                        "table_id_unknown",
                        f"Table id '{tk}' is not in the registry.",
                        node_id=nid,
                        token=tk,
                    )
                )
    elif ct == "static_table" and not d.get("static_table"):
        warnings.append(
            _issue(
                "warning",
                "static_table_empty",
                "Static-table node has no static_table payload.",
                node_id=nid,
            )
        )


MIN_PUBLISH_DESCRIPTION = 120


def validate_template(
    db: Session,
    tree: List[Any],
    *,
    plan_kind: Optional[str] = None,
    for_publish: bool = False,
    description: Optional[str] = None,
    is_system: bool = False,
) -> Dict[str, Any]:
    """Validate a template tree. Returns {ok, errors[], warnings[]}.

    ``is_system`` templates (the बृन्दावन base) are exempt from the
    publish-only description-length + plan-kind requirements — they are the
    fork parent, not a gallery pick.
    """
    errors: List[Dict[str, Any]] = []
    warnings: List[Dict[str, Any]] = []

    if not tree:
        errors.append(_issue("error", "empty_tree", "Template has no sections."))
        return {"ok": False, "errors": errors, "warnings": warnings}

    seen_ids: set[str] = set()
    titles: dict[str, int] = {}
    cover_count = 0
    toc_count = 0
    section_count = 0
    present_section_keys: set[str] = set()

    for d, depth in _walk(tree):
        nid = d.get("id") or ""

        if nid in seen_ids:
            errors.append(
                _issue(
                    "error", "duplicate_id", f"Duplicate node id '{nid}'.", node_id=nid
                )
            )
        seen_ids.add(nid)

        ntype = d.get("type")
        if ntype not in VALID_NODE_TYPES:
            errors.append(
                _issue(
                    "error",
                    "bad_node_type",
                    f"Node type '{ntype}' is not valid.",
                    node_id=nid,
                )
            )

        ctype = d.get("content_type", "richtext")
        if ctype not in VALID_CONTENT_TYPES:
            errors.append(
                _issue(
                    "error",
                    "bad_content_type",
                    f"content_type '{ctype}' is not valid.",
                    node_id=nid,
                )
            )

        if d.get("is_cover"):
            cover_count += 1
        if ntype == "toc":
            toc_count += 1
        if ntype in ("section", "subsection"):
            section_count += 1

        sk = d.get("section_key")
        if sk:
            present_section_keys.add(sk)

        if depth > MAX_DEPTH:
            warnings.append(
                _issue(
                    "warning",
                    "too_deep",
                    f"Node nested deeper than {MAX_DEPTH} levels.",
                    node_id=nid,
                )
            )

        title = (d.get("title_ne") or d.get("title_en") or "").strip()
        if title:
            titles[title] = titles.get(title, 0) + 1

        _check_typed_node_ref(d, errors, warnings)

        # Token resolution — the core check.
        content = d.get("content") or ""
        for m in _TOKEN_RE.finditer(content):
            tok = m.group(1)
            if tok.startswith(("thememap:", "opsmap:")):
                _flag_map_variable(tok, nid, warnings)
            elif not _token_is_known(tok):
                errors.append(
                    _issue(
                        "error",
                        "unknown_token",
                        f"{{{{{tok}}}}} does not resolve to a " f"registered variable.",
                        node_id=nid,
                        token=tok,
                    )
                )

        if (
            ctype == "richtext"
            and not content.strip()
            and not (d.get("children") or [])
            and ntype in ("section", "subsection")
        ):
            warnings.append(
                _issue(
                    "warning",
                    "empty_section",
                    f"Section '{title or nid}' has no content.",
                    node_id=nid,
                )
            )

    if cover_count > 1:
        errors.append(
            _issue(
                "error",
                "multiple_cover_nodes",
                f"{cover_count} nodes marked is_cover — exactly one is allowed.",
            )
        )
    elif cover_count == 0:
        errors.append(
            _issue(
                "error",
                "no_cover_node",
                "Template has no cover node. Mark the cover section "
                "(is_cover) — every template owns its own cover page.",
            )
        )

    if toc_count == 0:
        warnings.append(_issue("warning", "no_toc_node", "No table-of-contents node."))

    for t, n in titles.items():
        if n > 1:
            warnings.append(
                _issue(
                    "warning",
                    "duplicate_title",
                    f"Section title '{t}' appears {n} times.",
                )
            )

    # Plan-kind rules.
    if plan_kind:
        kind = plan_kinds_service.get_plan_kind(db, plan_kind)
        if kind is None:
            warnings.append(
                _issue(
                    "warning",
                    "unknown_plan_kind",
                    f"plan_kind '{plan_kind}' is not a known kind.",
                )
            )
        else:
            required = plan_kinds_service.effective_required_sections(db, plan_kind)
            for key in required:
                if key not in present_section_keys:
                    errors.append(
                        _issue(
                            "error",
                            "missing_required_section",
                            f"Required section '{key}' is missing for "
                            f"kind '{plan_kind}'.",
                        )
                    )
            if kind.min_sections and section_count < kind.min_sections:
                warnings.append(
                    _issue(
                        "warning",
                        "below_min_sections",
                        f"{section_count} sections, kind '{plan_kind}' "
                        f"expects at least {kind.min_sections}.",
                    )
                )
    # NULL plan_kind (the बृन्दावन base) is exempt from required-section checks.

    desc = (description or "").strip()
    if not is_system:
        if for_publish and len(desc) < MIN_PUBLISH_DESCRIPTION:
            errors.append(
                _issue(
                    "error",
                    "description_too_short",
                    f"A description of at least {MIN_PUBLISH_DESCRIPTION} characters "
                    f"is required to publish (currently {len(desc)}). It is the "
                    f"reader's only guide in the gallery.",
                )
            )
        elif not for_publish and len(desc) < MIN_PUBLISH_DESCRIPTION:
            warnings.append(
                _issue(
                    "warning",
                    "description_short",
                    f"Description is {len(desc)} characters; publishing needs "
                    f"at least {MIN_PUBLISH_DESCRIPTION}.",
                )
            )
        if for_publish and not plan_kind:
            errors.append(
                _issue(
                    "error",
                    "kind_required",
                    "Set the plan regime and stage before publishing.",
                )
            )

    return {"ok": len(errors) == 0, "errors": errors, "warnings": warnings}
