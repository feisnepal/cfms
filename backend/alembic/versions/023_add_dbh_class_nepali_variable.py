"""Add Nepali DBH class growing stock variable to system template

Revision ID: 023
Revises: 022
Create Date: 2026-05-22 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
import json


revision = '023'
down_revision = '022'
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()

    # Find the system default template
    result = conn.execute(
        sa.text(
            "SELECT id, tree FROM public.op_templates WHERE is_system = true AND is_default = true"
        )
    ).fetchone()

    if result is None:
        return

    tmpl_id, tree_json_str = result

    # Parse the tree
    tree = json.loads(json.dumps(tree_json_str)) if isinstance(tree_json_str, dict) else tree_json_str
    # tree_json_str from SQLAlchemy may already be a dict (JSONB)
    if not isinstance(tree, list):
        try:
            tree = json.loads(tree_json_str)
        except (TypeError, json.JSONDecodeError):
            return

    # Walk the tree and find the "कम्पार्टमेण्ट अनुसार वनको मौज्दात" subsection
    # which we renamed to "ब्यास वर्ग अनुसार वन मौज्दात" — the old name may still exist
    def walk_and_update(nodes):
        changed = False
        for node in nodes:
            children = node.get("children", [])
            if children:
                changed = walk_and_update(children) or changed
            content = node.get("content", "") or ""
            title_en = node.get("title_en", "") or ""
            title_ne = node.get("title_ne", "") or ""

            # Update the Growing Stock subsection to include the DBH class table
            if title_en == "Growing Stock" and "{{fi_growing_stock_m3_per_ha}}" in content:
                # Check if already updated
                if "{{fi_block_dbh_class_growing_stock_np}}" not in content:
                    node["title_en"] = "DBH Class Growing Stock"
                    node["title_ne"] = "ब्यास वर्ग अनुसार वन मौज्दात"
                    node["content"] = (
                        "ब्लक अनुसार ब्यास वर्गको वन मौज्दात निम्नानुसार छ:\n\n"
                        "{{fi_block_dbh_class_growing_stock_np}}"
                    )
                    changed = True
        return changed

    changed = walk_and_update(tree)
    if not changed:
        return

    # Update the template with the new tree JSON
    updated_json = json.dumps(tree, ensure_ascii=False)
    conn.execute(
        sa.text(
            "UPDATE public.op_templates SET tree = CAST(:tree AS jsonb) WHERE id = :id"
        ).bindparams(tree=updated_json, id=tmpl_id)
    )


def downgrade() -> None:
    pass
