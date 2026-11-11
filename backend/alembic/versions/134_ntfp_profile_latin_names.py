"""ntfp_method_profile: Latin names for ढटेलो and विषफेज, taken from Schedule-7 (the guideline prints none).

Revision ID: 134_ntfp_profile_latin_names
Revises: 133_ntfp_sampling_design
Create Date: 2026-10-22

Idempotent: a database seeded by migration 132 after this change already has the new keys, and the UPDATEs then match nothing.
"""
from alembic import op
import sqlalchemy as sa

revision = "134_ntfp_profile_latin_names"
down_revision = "133_ntfp_sampling_design"
branch_labels = None
depends_on = None

FIXES = [("np:ढटेलो", "prinsepia utilis", "Prinsepia utilis"), ("np:बिषफेज", "polypodiodes amoena", "Polypodiodes amoena")]


def upgrade() -> None:
    for old, key, sci in FIXES:
        op.execute(sa.text(
            "UPDATE ntfp_method_profile SET species_key = :key, scientific_name = :sci, regulation_name = :sci, updated_at = now() "
            "WHERE species_key = :old"
        ).bindparams(key=key, sci=sci, old=old))


def downgrade() -> None:
    for old, key, _sci in FIXES:
        op.execute(sa.text(
            "UPDATE ntfp_method_profile SET species_key = :old, scientific_name = NULL, regulation_name = NULL WHERE species_key = :key"
        ).bindparams(key=key, old=old))
