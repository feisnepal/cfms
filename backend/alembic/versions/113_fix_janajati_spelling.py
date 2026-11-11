"""Caste classification spelling: जनजाति -> जनजाती (owner, 2026-10-05).

Revision ID: 113_fix_janajati_spelling
Revises: 112_add_household_summary_data
Create Date: 2026-10-05

"जनजाती" is the correct spelling and the one the classification table already used for some rows, so the same
group was split in two in every caste distribution. Replaces the EXACT classification value only; running prose
(activity names, templates) that merely contains the word is deliberately left alone. Idempotent.
"""
from alembic import op

revision = "113_fix_janajati_spelling"
down_revision = "112_add_household_summary_data"
branch_labels = None
depends_on = None

OLD = "\u091c\u0928\u091c\u093e\u0924\u093f"   # जनजाति
NEW = "\u091c\u0928\u091c\u093e\u0924\u0940"   # जनजाती


def upgrade() -> None:
    bind = op.get_bind()
    params = {"old": OLD, "new": NEW}
    for stmt in (
        "UPDATE public.caste_classification SET classification_ne = :new WHERE classification_ne = :old",
        "UPDATE public.household_information SET caste_classification_ne = :new WHERE caste_classification_ne = :old",
        # summary-only forests keep the distribution as JSONB {classification: households}: merge the two keys
        """UPDATE public.household_summary_data
              SET caste_distribution = (caste_distribution - CAST(:old AS text))
                  || jsonb_build_object(
                       CAST(:new AS text),
                       COALESCE((caste_distribution ->> CAST(:old AS text))::int, 0)
                       + COALESCE((caste_distribution ->> CAST(:new AS text))::int, 0))
            WHERE caste_distribution ? CAST(:old AS text)""",
        # the two UI strings that name the classification
        "UPDATE public.translations SET ne = replace(ne, :old, :new) WHERE key IN ('committeeValidation.casteInvalid', 'household.add.caste')",
    ):
        bind.exec_driver_sql(stmt.replace(":old", "%(old)s").replace(":new", "%(new)s"), params)


def downgrade() -> None:
    # The old spelling was wrong; there is nothing to restore.
    pass
