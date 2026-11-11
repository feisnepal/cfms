"""Forest metadata: the facts a person writes down in the field.

Revision ID: 098_forest_metadata
Revises: 097_document_submissions
Create Date: 2026-09-26

Why this migration exists (WORKSPACE_FLOW_NAV_PLAN D5)
-----------------------------------------------------
"Forest Metadata is collected in the field during field inventory, so it is a
third tab on the Field Inventory page, not a separate step."

It had nowhere to live. The form existed inside `ReportTab` as component state,
and the only consumer was `reportApi.generateReport(calculationId, metadata, ...)`,
which posted the whole dict from the browser. Two consequences, both real:

  * Reloading the page lost it. Nothing had been written down.
  * The .docx cover page was whatever one person happened to have typed. Two
    people generating a report for the same forest got two different cover
    pages, and neither was a record of anything -- it was a transient UI state
    that happened to be serialised into a download.

Why a table and not columns on `calculations`
---------------------------------------------
These are *authored* values, not computed ones. `result_data` is a JSONB bag
holding a species tally, a carbon figure and a geometry version; a form's
output does not belong in it. The distinguishing properties are that this set of
fields has a fixed shape, is validated, and changes on its own schedule (when
someone corrects a ward number), so it wants typed columns, length constraints
and an audit trail rather than a blob every reader has to guess the shape of.

Why 1:1
--------
One forest has one cover page. A UNIQUE constraint on `calculation_id` makes
that a fact the database enforces rather than a convention two code paths might
disagree about; without it a second save could leave two rows and nothing would
say which one the report should print.

ON DELETE CASCADE, deliberately the opposite of `document_submissions`
----------------------------------------------------------------------
Migration 097 installed append-only RULES and gave up foreign keys so that a
statutory record of submission outlives deletion of the forest it describes.
This row is the opposite case: it is a *description of* the forest, so it goes
when the forest does. An orphan would be worse than a loss here -- it would let
a deleted forest's cover page be regenerated, which is the one thing the cascade
prevents.

`fy_start` / `fy_end` are String, not Integer or Date
----------------------------------------------------
`services/report/document_builder.py:79` prints them verbatim onto the cover
page, and a Nepali fiscal year is legitimately written "2081/82", "2081/2082"
or "२०८१/८२". An int column would force one spelling and reject the other two.
The CHECK constraints cap the length instead, which is the guard that matters.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "098_forest_metadata"
down_revision = "097_document_submissions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "forest_metadata",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),

        # CASCADE -- see the module docstring. This row describes the forest, so
        # it must not outlive it the way `document_submissions` does. `ondelete`
        # belongs on the ForeignKeyConstraint, not the Column: SQLAlchemy passes
        # unknown column kwargs through to the dialect and rejects them.
        sa.Column("calculation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["calculation_id"], ["calculations.id"], ondelete="CASCADE"
        ),

        # --- identification ---------------------------------------------------
        sa.Column("forest_name", sa.String(255), nullable=True),
        sa.Column("group_name", sa.String(255), nullable=True),
        sa.Column("province", sa.String(255), nullable=True),
        sa.Column("district", sa.String(255), nullable=True),
        sa.Column("palika", sa.String(255), nullable=True),
        sa.Column("ward", sa.String(64), nullable=True),
        sa.Column("division", sa.String(255), nullable=True),
        sa.Column("sub_division", sa.String(255), nullable=True),
        sa.Column("address", sa.Text(), nullable=True),

        # --- the identifiers the forest office files the report under ----------
        sa.Column("serial_number", sa.String(64), nullable=True),
        sa.Column("cf_code", sa.String(32), nullable=True),
        sa.Column("cf_national_code", sa.String(32), nullable=True),

        # --- reporting period, printed verbatim on the cover page --------------
        sa.Column("fy_start", sa.String(32), nullable=True),
        sa.Column("fy_end", sa.String(32), nullable=True),

        # --- audit ------------------------------------------------------------
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        # A plain id, not an FK to users: deactivating someone must not erase the
        # record of who wrote the cover page.
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), nullable=True),

        # The 1:1, enforced here rather than in code.
        sa.UniqueConstraint("calculation_id", name="uq_forest_metadata_calculation_id"),

        # Length guards, because the fiscal year and the codes are free text.
        # `char_length(trim(x))` so a padded value cannot slip past a NOT NULL
        # length check that a later read would then treat as present.
        sa.CheckConstraint("char_length(trim(cf_code)) <= 32",
                           name="ck_forest_metadata_cf_code_len"),
        sa.CheckConstraint("char_length(trim(cf_national_code)) <= 32",
                           name="ck_forest_metadata_cf_national_code_len"),
        sa.CheckConstraint("char_length(trim(fy_start)) <= 32",
                           name="ck_forest_metadata_fy_start_len"),
        sa.CheckConstraint("char_length(trim(fy_end)) <= 32",
                           name="ck_forest_metadata_fy_end_len"),
    )

    op.create_index("ix_forest_metadata_updated_at", "forest_metadata",
                    ["updated_at"])

    # `updated_at` is maintained in Python by the service (onupdate=func.now()
    # only fires on an ORM flush). A trigger is what makes the column true for
    # every writer, including a future one that uses raw SQL -- and the same
    # reason 097 installed RULES rather than trusting the ORM.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION forest_metadata_touch_updated_at()
        RETURNS trigger AS $$
        BEGIN
            NEW.updated_at = now();
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER forest_metadata_touch_updated_at
        BEFORE UPDATE ON forest_metadata
        FOR EACH ROW EXECUTE FUNCTION forest_metadata_touch_updated_at();
        """
    )


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER IF EXISTS forest_metadata_touch_updated_at ON forest_metadata;"
    )
    op.execute("DROP FUNCTION IF EXISTS forest_metadata_touch_updated_at();")
    op.drop_index("ix_forest_metadata_updated_at", table_name="forest_metadata")
    op.drop_table("forest_metadata")
