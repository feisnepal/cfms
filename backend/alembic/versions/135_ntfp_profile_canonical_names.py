"""ntfp_method_profile: one canonical Latin name per species, the guideline's own spelling kept as an alias.

Revision ID: 135_ntfp_profile_canonical_names
Revises: 134_ntfp_profile_latin_names
Create Date: 2026-10-22

Owner, 2026-10-22: use the same name everywhere. The profiles had been keyed by the guideline's names (Nardostachys grandiflora, Valeriana
jatamansii, Cinnamomum glaucescens); the species master and Schedule-7 spell them jatamansi / jatamansi / tenuipile. The key, the scientific name
and the regulation name are now the canonical ones (``app.core.species_synonyms``) and ``aliases`` holds the guideline's spelling.
Idempotent: a database seeded by migration 132 after this change already has the canonical keys.
"""
import json

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "135_ntfp_profile_canonical_names"
down_revision = "134_ntfp_profile_latin_names"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("ntfp_method_profile", sa.Column("aliases", postgresql.JSONB, nullable=False, server_default="[]"))

    from app.core.ntfp_methods import profiles
    from app.core.species_synonyms import _norm

    for p in profiles():
        if not p["aliases"]:
            continue
        old_keys = [_norm(a) for a in p["aliases"]]
        op.execute(sa.text(
            "UPDATE ntfp_method_profile SET species_key = :key, scientific_name = :sci, regulation_name = :reg, "
            "aliases = CAST(:aliases AS jsonb), updated_at = now() WHERE species_key = :key OR species_key = ANY(:old)"
        ).bindparams(key=p["species_key"], sci=p["scientific_name"], reg=p["regulation_name"], aliases=json.dumps(p["aliases"]), old=old_keys))


def downgrade() -> None:
    op.drop_column("ntfp_method_profile", "aliases")  # the canonical keys stay: they are the corrected data
