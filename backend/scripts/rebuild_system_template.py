#!/usr/bin/env python
"""Re-sync the one ``is_system`` op_templates row to the code-owned seed tree.

OP_TEMPLATE_MANAGEMENT_PLAN.md T1.

The **System Template** is the tokenised master document every Operational Plan
template is forked from, and the fallback ``create_operational_plan`` clones
when no template is chosen. Its structure is
``seed_data.get_default_seed_tree()`` + exactly one cover node — nothing more.
This module rebuilds the row from that definition.

It replaces the ad-hoc ``patch_system_template*.py`` scratchpad scripts: the
System Template is no longer hand-edited out of band. Changes land in
``app/services/operational_plan/seed_data.py`` (and then here / migration 081),
or through the super-admin template editor.

Idempotent:
  - row already byte-identical to ``build_system_tree()``  -> no-op
  - row drifted                                            -> snapshot the
      current tree into ``op_template_versions`` then overwrite, bump the
      version + publish counter, regenerate the summaries
  - no ``is_system`` row at all                            -> create it,
      ``status = 'published'``

Run:
    python -m scripts.rebuild_system_template             # apply
    python -m scripts.rebuild_system_template --dry-run   # report only
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

SYSTEM_TEMPLATE_NAME = "पूर्वनिर्धारित प्रणाली टेम्पलेट"
SYSTEM_TEMPLATE_DESC = (
    "System Template — the tokenised master document that every Operational "
    "Plan template is forked from, and the fallback used when a plan is created "
    "with no template. Super-admin editable only; its structure is tracked in "
    "app/services/operational_plan/seed_data.py."
)


def _assign_stable_ids(nodes: list[dict], _counter: Optional[list] = None) -> None:
    """Depth-first, assign deterministic ``sys_NNN`` ids in place.

    ``seed_data`` builds ``TreeNode`` objects with random uuid4 ids, so two
    ``build_system_tree()`` calls would otherwise never compare equal — the
    rebuild could never be a no-op. Stable ids also make the version-history
    diff and the T4 adopt-from-plan node matching meaningful.
    """
    if _counter is None:
        _counter = [0]
    for n in nodes:
        _counter[0] += 1
        n["id"] = f"sys_{_counter[0]:03d}"
        _assign_stable_ids(n.get("children") or [], _counter)


def build_system_tree() -> list[dict]:
    """The System Template document tree: the code-owned seed tree, numbered,
    with the "exactly one cover node" invariant applied and deterministic node
    ids. A list of plain dicts ready for the ``op_templates.tree`` JSONB
    column."""
    from app.services.operational_plan.seed_data import get_default_seed_tree
    from app.services.operational_plan.auto_numbering import recompute_numbers
    from app.services.operational_plan.cover import ensure_cover_node

    tree = get_default_seed_tree()
    recompute_numbers(tree, language="NP")
    dicts = [n.model_dump() for n in tree]
    dicts = ensure_cover_node(dicts, cover_style=None)
    _assign_stable_ids(dicts)
    return dicts


def _canonical(tree: Any) -> str:
    return json.dumps(tree, ensure_ascii=False, sort_keys=True)


def _summaries(tree: list[dict]) -> dict:
    from app.services.operational_plan.template_utils import (
        generate_template_summaries,
    )

    return generate_template_summaries(tree)


def rebuild_system_template(
    session: Session, *, dry_run: bool = False, actor_id: Optional[str] = None
) -> dict:
    """Rebuild (or create) the ``is_system`` template row from
    :func:`build_system_tree`. Returns a report dict:
    ``{action, changed, template_id, sections, from_version, to_version}``.

    The caller owns the transaction — this function does not commit.
    """
    new_tree = build_system_tree()
    new_json = _canonical(new_tree)
    summ = _summaries(new_tree)
    ss = json.dumps(summ["sections_summary"], ensure_ascii=False)
    vs = json.dumps(summ["variables_summary"], ensure_ascii=False)

    row = (
        session.execute(
            text(
                "SELECT id, tree, version, published_version, status "
                "FROM public.op_templates "
                "WHERE is_system IS TRUE ORDER BY updated_at DESC LIMIT 1"
            )
        )
        .mappings()
        .first()
    )

    if row is None:
        report = {
            "action": "create",
            "changed": True,
            "template_id": None,
            "sections": len(summ["sections_summary"]),
            "from_version": None,
            "to_version": 1,
        }
        if not dry_run:
            new_id = session.execute(
                text(
                    "INSERT INTO public.op_templates "
                    "(name, description, tree, is_system, status, version, "
                    " published_version, changelog, sections_summary, "
                    " variables_summary, created_by) "
                    "VALUES (:n, :d, CAST(:t AS jsonb), true, 'published', 1, 1, "
                    " :cl, CAST(:ss AS jsonb), CAST(:vs AS jsonb), :actor) "
                    "RETURNING id"
                ).bindparams(
                    n=SYSTEM_TEMPLATE_NAME,
                    d=SYSTEM_TEMPLATE_DESC,
                    t=new_json,
                    cl="System Template created from the seed tree (T1).",
                    ss=ss,
                    vs=vs,
                    actor=actor_id,
                )
            ).scalar()
            report["template_id"] = str(new_id)
        return report

    tid = str(row["id"])
    if _canonical(row["tree"]) == new_json:
        return {
            "action": "noop",
            "changed": False,
            "template_id": tid,
            "sections": len(summ["sections_summary"]),
            "from_version": row["version"],
            "to_version": row["version"],
        }

    from_v = row["version"] or 1
    to_v = from_v + 1
    if not dry_run:
        # Snapshot the current tree so the rebuild is reversible from the
        # template's version history.
        session.execute(
            text(
                "INSERT INTO public.op_template_versions "
                "(id, template_id, version, tree, name, description, changelog) "
                "SELECT gen_random_uuid(), id, COALESCE(version, 1), tree, name, "
                "       COALESCE(description, ''), "
                "       'Pre-rebuild snapshot (T1) ' || now()::text "
                "FROM public.op_templates WHERE id = :id"
            ).bindparams(id=tid)
        )
        session.execute(
            text(
                "UPDATE public.op_templates SET "
                "  tree = CAST(:t AS jsonb), "
                "  description = :d, "
                "  status = 'published', "
                "  version = :to_v, "
                "  published_version = COALESCE(published_version, 0) + 1, "
                "  changelog = :cl, "
                "  sections_summary = CAST(:ss AS jsonb), "
                "  variables_summary = CAST(:vs AS jsonb), "
                "  updated_at = now() "
                "WHERE id = :id"
            ).bindparams(
                id=tid,
                t=new_json,
                d=SYSTEM_TEMPLATE_DESC,
                cl="Re-synced the System Template to the seed tree (T1).",
                ss=ss,
                vs=vs,
                to_v=to_v,
            )
        )
    return {
        "action": "rebuild",
        "changed": True,
        "template_id": tid,
        "sections": len(summ["sections_summary"]),
        "from_version": from_v,
        "to_version": to_v,
    }


def _main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report what would change without writing.",
    )
    args = parser.parse_args(argv)

    from app.core.database import SessionLocal

    session = SessionLocal()
    try:
        report = rebuild_system_template(session, dry_run=args.dry_run)
        if args.dry_run:
            session.rollback()
        else:
            session.commit()
    finally:
        session.close()

    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(_main())
