"""Submission record: a statutory document leaves the building.

Revision ID: 097_document_submissions
Revises: 096_forest_boundary_pieces
Create Date: 2026-09-26

Why this migration exists (WORKSPACE_FLOW_NAV_PLAN §7.4, owner decision D8/D17)
-----------------------------------------------------------------------------
An operational plan is exported to .docx, printed, and submitted to the District
Forest Office. Completing that submission is how a cycle is closed: the plan is
the terminal deliverable, not an intermediate.

Migration 059 already records that a document was *issued* -- sha256 of the exact
bytes, a human-quotable verification code, and provenance binding it to the
geometry version and inventory runs that produced its numbers. It records nothing
about what happened to the document afterwards. A plan can be produced, printed,
handed to an office, and the system cannot distinguish that from a plan that was
produced, downloaded three times and never submitted. There is no date, no
recipient, no channel, and no reference number.

`reference_no` is the field the gap actually costs. It is the District Forest
Office's own file reference for the hard copy, and it is what the forest office is
asked for months later. Without it the submission cannot be evidenced at all.

Why a sibling table and not more columns
----------------------------------------
`document_issuances` is append-only by design: migration 059 installs
`document_issuances_no_update` and `_no_delete` RULES that refuse UPDATE and
DELETE through the application's own connection. A submission therefore *cannot* be
a second write to that row, which is the correct constraint -- an issuance is a
fact about bytes, and rewriting a fact is how audit trails die. It also means the
submission cannot be recorded on the issuance row, so it gets its own table with
the same append-only posture.

Per D17 this table is the *fact* and `operational_plans.status` is a read-only
projection of it, written in the same transaction. `status` has a `submitted` value
and the transitions at `api/operational_plans.py:576-603` and the i18n keys
`status.plan.submitted` already exist, but nothing ever set it. This table gives
them something true to be derived from.

No foreign keys, for the same reason as `document_issuances` (migration 059): the
record that a statutory document was submitted must outlive deletion of the forest
it describes. `forest_delete_rules.FOREST_DELETE_EXCEPTIONS` carries the reason.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "097_document_submissions"
down_revision = "096_forest_boundary_pieces"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "document_submissions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),

        # Which issuance this submission is about. Deliberately not an FK: see the
        # module docstring, and the same reasoning as migration 059 lines 74-77.
        sa.Column("issuance_id", postgresql.UUID(as_uuid=True), nullable=True, index=True),
        sa.Column("calculation_id", postgresql.UUID(as_uuid=True), nullable=True, index=True),
        sa.Column("plan_id", postgresql.UUID(as_uuid=True), nullable=True, index=True),

        # --- the submission itself -------------------------------------------
        # The receiving office. Free text, not an FK to an office table: the DFO
        # that receives a given plan is not modelled anywhere in this system, and
        # inventing a table for one string column would be the wrong shape.
        sa.Column("submitted_to", sa.String(255), nullable=False),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),

        # How it got there. The hard copy is `hand_delivery`; the other values are
        # for offices that also email or post a copy.
        sa.Column("channel", sa.String(32), nullable=False, server_default="hand_delivery"),

        # The DFO's own file reference for the printed copy. The field the forest
        # office is asked for months later, and the reason this table exists.
        sa.Column("reference_no", sa.String(64), nullable=True),

        sa.Column("notes", sa.Text, nullable=True),

        # --- who, from where --------------------------------------------------
        sa.Column("submitted_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("ip_address", sa.String(64), nullable=True),
        sa.Column("client_type", sa.String(32), nullable=True),
        sa.Column("correlation_id", sa.String(64), nullable=True),

        # H1.14 / S1-74: name the schema. cf_db carries
        # `search_path = rasters, public, sde`.
        schema="public",
    )
    op.create_index("ix_document_submissions_submitted_at", "document_submissions",
                    ["submitted_at"], schema="public")
    op.create_index("ix_document_submissions_plan_id_submitted_at", "document_submissions",
                    ["plan_id", "submitted_at"], schema="public")

    # Append-only, same posture and same limit as migration 059: this defends
    # against the application, a mistaken migration and a careless script. A
    # superuser can drop the rule. Genuine immutability needs an append-only store
    # off this host.
    op.execute(sa.text("""
        CREATE RULE document_submissions_no_update AS
            ON UPDATE TO public.document_submissions DO INSTEAD NOTHING
    """))
    op.execute(sa.text("""
        CREATE RULE document_submissions_no_delete AS
            ON DELETE TO public.document_submissions DO INSTEAD NOTHING
    """))


def downgrade() -> None:
    # Order matters: the rules must go before the table, or DROP TABLE trips the
    # no_delete rule this migration installed.
    op.execute(sa.text("DROP RULE IF EXISTS document_submissions_no_delete ON public.document_submissions"))
    op.execute(sa.text("DROP RULE IF EXISTS document_submissions_no_update ON public.document_submissions"))
    op.drop_index("ix_document_submissions_plan_id_submitted_at", table_name="document_submissions",
                  schema="public")
    op.drop_index("ix_document_submissions_submitted_at", table_name="document_submissions",
                  schema="public")
    op.drop_table("document_submissions", schema="public")
