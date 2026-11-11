"""Create op_plan_kinds and seed the six (stage x regime) kinds.

Revision ID: 067_op_plan_kinds
Revises: 066_op_template_lifecycle_columns
Create Date: 2026-08-31

OP multi-template plan, Phase 0 (OP_MULTI_TEMPLATE_PLAN.md §3.2 / §7 D2a/D2b).

Six kinds: {sustainable,brief,scientific}_fmp_{new,revision}. Each *_revision
row points at its *_new row via parent_kind_key; its effective required
sections are resolved in code as parent UNION own.

Per D2a the existing बृन्दावन base template (is_system AND is_default) serves
as the default for ALL six kinds until purpose-built templates are published.
Per D2b required_section_keys / export_basename are seeded empty and filled
later via the kinds-manager UI — no migration needed for that.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "067_op_plan_kinds"
down_revision = "066_op_template_lifecycle_columns"
branch_labels = None
depends_on = None

SCHEMA = "public"

# (key, stage, regime, parent, label_ne, label_en, cover_style, sort_order)
_KINDS = [
    ("sustainable_fmp_new", "new", "sustainable_fmp", None,
     "दिगो वन व्यवस्थापन योजना (नयाँ)", "Sustainable Forest Management Plan (New)",
     "sustainable", 10),
    ("brief_fmp_new", "new", "brief_fmp", None,
     "संक्षिप्त वन व्यवस्थापन योजना (नयाँ)", "Brief Forest Management Plan (New)",
     "brief", 20),
    ("scientific_fmp_new", "new", "scientific_fmp", None,
     "वैज्ञानिक वन व्यवस्थापन योजना (नयाँ)", "Scientific Forest Management Plan (New)",
     "scientific", 30),
    ("sustainable_fmp_revision", "revision", "sustainable_fmp", "sustainable_fmp_new",
     "दिगो वन व्यवस्थापन योजना (पुनरावलोकन)", "Sustainable Forest Management Plan (Revision)",
     "sustainable", 11),
    ("brief_fmp_revision", "revision", "brief_fmp", "brief_fmp_new",
     "संक्षिप्त वन व्यवस्थापन योजना (पुनरावलोकन)", "Brief Forest Management Plan (Revision)",
     "brief", 21),
    ("scientific_fmp_revision", "revision", "scientific_fmp", "scientific_fmp_new",
     "वैज्ञानिक वन व्यवस्थापन योजना (पुनरावलोकन)", "Scientific Forest Management Plan (Revision)",
     "scientific", 31),
]


def upgrade() -> None:
    op.create_table(
        "op_plan_kinds",
        sa.Column("key", sa.String(50), primary_key=True),
        sa.Column("plan_stage", sa.String(20), nullable=False),
        sa.Column("plan_regime", sa.String(30), nullable=False),
        sa.Column("parent_kind_key", sa.String(50),
                  sa.ForeignKey("public.op_plan_kinds.key"), nullable=True),
        sa.Column("label_ne", sa.String(255), nullable=False),
        sa.Column("label_en", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True, server_default=""),
        sa.Column("required_section_keys", postgresql.JSONB(), nullable=False,
                  server_default=sa.text("'[]'::jsonb")),
        sa.Column("variable_allowlist", postgresql.JSONB(), nullable=True),
        sa.Column("allowlist_strict", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("default_template_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("public.op_templates.id"), nullable=True),
        sa.Column("cover_style", sa.String(30), nullable=True),
        sa.Column("export_basename", sa.String(255), nullable=True),
        sa.Column("min_sections", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        schema=SCHEMA,
    )

    ins = sa.text(
        """
        INSERT INTO public.op_plan_kinds
            (key, plan_stage, plan_regime, parent_kind_key, label_ne, label_en,
             cover_style, sort_order)
        VALUES
            (:key, :stage, :regime, :parent, :label_ne, :label_en, :cover, :sort)
        """
    )
    bind = op.get_bind()
    # Parents (*_new) first so the self-FK on *_revision resolves.
    for key, stage, regime, parent, label_ne, label_en, cover, sort in _KINDS:
        if parent is None:
            bind.execute(ins, dict(key=key, stage=stage, regime=regime, parent=parent,
                                   label_ne=label_ne, label_en=label_en, cover=cover, sort=sort))
    for key, stage, regime, parent, label_ne, label_en, cover, sort in _KINDS:
        if parent is not None:
            bind.execute(ins, dict(key=key, stage=stage, regime=regime, parent=parent,
                                   label_ne=label_ne, label_en=label_en, cover=cover, sort=sort))

    # D2a: point every kind at the बृन्दावन base template, if one exists.
    bind.execute(sa.text(
        """
        UPDATE public.op_plan_kinds
        SET default_template_id = (
            SELECT id FROM public.op_templates
            WHERE is_system IS TRUE AND is_default IS TRUE
            ORDER BY updated_at DESC
            LIMIT 1
        )
        WHERE default_template_id IS NULL
        """
    ))


def downgrade() -> None:
    op.drop_table("op_plan_kinds", schema=SCHEMA)
