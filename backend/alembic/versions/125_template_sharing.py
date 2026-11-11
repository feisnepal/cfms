"""op_templates: who may see a template (share_scope), its trust tier, its licence and its office; reports about templates.

Revision ID: 125_template_sharing
Revises: 124_potential_activity_map_geom
Create Date: 2026-10-17

Owner decisions 2026-10-16/17 (TEMPLATE_STORE_PROPOSAL.md):
  * any signed-in user may publish; only the super admin grants Verified and Official;
  * the default licence is "free to use with credit";
  * "My organisation" means a DFO office (an ``organizations`` row; the user's ``organization_id``);
  * anyone may report a template.

Existing rows keep working as they do today: a published or deprecated template, and the system template, become ``public``;
templates the super admin already approved become ``verified`` (the system template ``official``); everything else is ``private``
and ``community``.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "125_template_sharing"
down_revision = "124_potential_activity_map_geom"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("op_templates", sa.Column("share_scope", sa.String(10), nullable=False, server_default="private"))
    op.add_column("op_templates", sa.Column("tier", sa.String(10), nullable=False, server_default="community"))
    op.add_column("op_templates", sa.Column("license", sa.String(10), nullable=False, server_default="cc_by"))
    op.add_column(
        "op_templates",
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id", ondelete="SET NULL"), nullable=True),
    )
    op.create_check_constraint("ck_op_templates_share_scope", "op_templates", "share_scope IN ('private','office','public')")
    op.create_check_constraint("ck_op_templates_tier", "op_templates", "tier IN ('community','verified','official')")
    op.create_check_constraint("ck_op_templates_license", "op_templates", "license IN ('cc_by','cc0','view_only')")
    op.create_index("ix_op_templates_share_scope", "op_templates", ["share_scope"])

    op.execute("UPDATE op_templates SET share_scope = 'public' WHERE status IN ('published','deprecated') OR is_system")
    op.execute("UPDATE op_templates SET tier = 'verified' WHERE status IN ('published','deprecated')")
    op.execute("UPDATE op_templates SET tier = 'official' WHERE is_system")

    op.create_table(
        "op_template_reports",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("template_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("op_templates.id", ondelete="CASCADE"), nullable=False),
        sa.Column("reporter_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("reason", sa.Text, nullable=False),
        sa.Column("status", sa.String(10), nullable=False, server_default="open"),
        sa.Column("handled_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("handled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("handled_note", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("status IN ('open','dismissed','actioned')", name="ck_op_template_reports_status"),
    )
    op.create_index("ix_op_template_reports_template", "op_template_reports", ["template_id"])
    op.create_index("ix_op_template_reports_open", "op_template_reports", ["status"])
    # one open report per person per template: repeating the same complaint adds nothing
    op.create_index(
        "uq_op_template_reports_open_per_reporter",
        "op_template_reports",
        ["template_id", "reporter_id"],
        unique=True,
        postgresql_where=sa.text("status = 'open'"),
    )


def downgrade() -> None:
    op.drop_table("op_template_reports")
    op.drop_index("ix_op_templates_share_scope", table_name="op_templates")
    for name in ("ck_op_templates_license", "ck_op_templates_tier", "ck_op_templates_share_scope"):
        op.drop_constraint(name, "op_templates", type_="check")
    for col in ("organization_id", "license", "tier", "share_scope"):
        op.drop_column("op_templates", col)
