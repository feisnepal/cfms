"""Backfill: every op_templates tree gets exactly one cover node.

Revision ID: 070_backfill_template_cover_nodes
Revises: 069_op_template_published_snapshot
Create Date: 2026-08-31

OP multi-template plan, Phase 3 (OP_MULTI_TEMPLATE_PLAN.md §3.9). Deferred
from Phase 0.

For each template tree:
  - already has a node with is_cover=true  -> leave it
  - more than one                          -> keep the first, clear the rest
  - none                                   -> tag the first top-level
      `preamble` node as the cover; if there is no preamble node, prepend a
      minimal cover node

Then set page_break_before=true on the node after the cover so the body starts
on a fresh page. Logic is inlined (no app imports in migrations), matching the
shared helper in app/services/operational_plan/cover.py.
"""

import json

import sqlalchemy as sa
from alembic import op

revision = "070_backfill_template_cover_nodes"
down_revision = "069_op_template_published_snapshot"
branch_labels = None
depends_on = None

_GENERIC_COVER = {
    "id": "node_cover",
    "type": "preamble",
    "title_ne": "वन व्यवस्थापन कार्ययोजना",
    "title_en": "Forest Management Operational Plan",
    "number": None,
    "level": 0,
    "content_type": "richtext",
    "content": "{{forest_name}}\n{{district}} जिल्ला, {{municipality}}",
    "children": [],
    "is_locked": False,
    "hidden_in_export": False,
    "deleted": False,
    "is_cover": True,
    "cover_meta": {"border_style": "double", "align": "center"},
}


def _ensure_cover(tree):
    if not isinstance(tree, list) or not tree:
        return [dict(_GENERIC_COVER)], True

    cover_idxs = [i for i, n in enumerate(tree) if isinstance(n, dict) and n.get("is_cover")]
    changed = False

    if len(cover_idxs) == 1:
        idx = cover_idxs[0]
    elif len(cover_idxs) > 1:
        for i in cover_idxs[1:]:
            tree[i]["is_cover"] = False
        idx = cover_idxs[0]
        changed = True
    else:
        promote = next(
            (i for i, n in enumerate(tree)
             if isinstance(n, dict) and n.get("type") == "preamble" and not n.get("deleted")),
            None,
        )
        if promote is not None:
            tree[promote]["is_cover"] = True
            tree[promote].setdefault("cover_meta", {"border_style": "double", "align": "center"})
            idx = promote
        else:
            tree.insert(0, dict(_GENERIC_COVER))
            idx = 0
        changed = True

    if idx + 1 < len(tree) and isinstance(tree[idx + 1], dict):
        if not tree[idx + 1].get("page_break_before"):
            tree[idx + 1]["page_break_before"] = True
            changed = True

    return tree, changed


def upgrade() -> None:
    bind = op.get_bind()
    rows = bind.execute(sa.text(
        "SELECT id, tree FROM public.op_templates"
    )).fetchall()
    for row in rows:
        tree = row.tree
        if isinstance(tree, str):
            tree = json.loads(tree)
        new_tree, changed = _ensure_cover(tree if isinstance(tree, list) else [])
        if changed:
            bind.execute(
                sa.text("UPDATE public.op_templates SET tree = CAST(:t AS jsonb) WHERE id = :id"),
                {"t": json.dumps(new_tree), "id": row.id},
            )


def downgrade() -> None:
    # Irreversible-in-practice: we cannot know which is_cover flags / page breaks
    # this migration added vs. which a designer set. No-op; the flags are inert
    # when the cover feature is reverted.
    pass
