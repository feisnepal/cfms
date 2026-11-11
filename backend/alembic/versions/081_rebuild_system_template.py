"""Re-sync the is_system op_templates row to the code-owned seed tree.

Revision ID: 081_rebuild_system_template
Revises: 080_cba_rate_profiles
Create Date: 2026-09-09

OP_TEMPLATE_MANAGEMENT_PLAN.md T1.

The System Template (``op_templates.is_system = true``) is the tokenised master
document every OP template is forked from, and the fallback
``create_operational_plan`` clones. On the long-lived ``cf_db`` it drifted:
migration 019 seeded it from the seed tree years ago, then ~9 scratchpad
``patch_system_template*.py`` runs hand-edited it (stub sections, a missing
``{{fi_mai_table}}``, ~30 unregistered legacy tokens).

This one-shot data migration rebuilds it from
``seed_data.get_default_seed_tree()`` + one cover node, snapshotting the current
tree into ``op_template_versions`` first. Idempotent — on a fresh DB (where 019
already seeded the current tree and 070 added its cover node) it is a no-op.

Like migration 019, this deliberately imports app code: the migration's purpose
is to make the row match *current* code, so the coupling is intended and
one-shot. The reusable, re-runnable version is
``scripts/rebuild_system_template.py``.
"""

from alembic import op
from sqlalchemy.orm import Session

revision = "081_rebuild_system_template"
down_revision = "080_cba_rate_profiles"
branch_labels = None
depends_on = None


def upgrade() -> None:
    from scripts.rebuild_system_template import rebuild_system_template

    session = Session(bind=op.get_bind())
    report = rebuild_system_template(session)
    session.flush()
    print(f"[081] system template rebuild: {report}")


def downgrade() -> None:
    # No structural change to undo. The pre-rebuild tree is kept in
    # op_template_versions; restore it from there via the template editor's
    # version history / rollback if needed.
    pass
