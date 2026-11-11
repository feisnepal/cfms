"""biodiversity_species: add the designated NTFP species the master did not have (Forest Regulations 2079, Schedule-7).

Revision ID: 127_ntfp_schedule7_species
Revises: 126_template_item_type
Create Date: 2026-10-17

The regulation's Schedule-7 (वन नियमावली, २०७९ अनुसूची-७) names the herbs and other forest products that count as non-timber forest
products. Compared with the species master on 2026-10-17, only 55 of its 217 species-level entries (and 16 of its 46 genus-level
"spp." entries) were there, so a forest recording an NTFP species could not pick most of them. This adds the missing ones (a species the
list names, or a genus the list names when the master has no species of that genus at all), so every entry can be recorded.

Added rows carry the regulation as their source in ``notes`` and nothing else guessed about them: no sub-category, no use, no IUCN
status. Existing rows are never changed. The list itself (parts harvested, price rates) is read from ``app.core.ntfp_schedule7``.
"""
import re

import sqlalchemy as sa
from alembic import op

revision = "127_ntfp_schedule7_species"
down_revision = "126_template_item_type"
branch_labels = None
depends_on = None

SOURCE_NOTE = "वन नियमावली, २०७९ अनुसूची-७ (तोकिएको गैरकाष्ठ वन पैदावार)"


def _words(name: str):
    # the same normalisation as app.core.ntfp_schedule7: a hyphen is dropped, not turned into a space
    return re.sub(r"[^a-z ]", " ", (name or "").lower().replace("-", "")).split()


def upgrade() -> None:
    from app.core.ntfp_schedule7 import ROWS, scientific_names

    conn = op.get_bind()
    have_species, have_genus = set(), set()
    for (sci,) in conn.execute(sa.text("SELECT scientific_name FROM biodiversity_species WHERE category = 'vegetation'")):
        w = _words(sci)
        if len(w) >= 2 and w[1] not in ("spp", "sp"):
            have_species.add(" ".join(w[:2]))
        if w:
            have_genus.add(w[0])

    added = set()
    insert = sa.text(
        "INSERT INTO biodiversity_species (category, nepali_name, english_name, scientific_name, notes) "
        "VALUES ('vegetation', :ne, :en, :sci, :note)"
    )
    for _group, _serial, nepali, printed, _price, _unit in ROWS:
        for name in scientific_names(printed):
            if name in added:
                continue
            if " " in name:  # a species the list names
                if name in have_species:
                    continue
                sci = name[0].upper() + name[1:]
            else:  # a genus the list names ("... spp."): only if the master has no species of it at all
                if name in have_genus:
                    continue
                sci = name.capitalize() + " spp."
            added.add(name)
            conn.execute(insert, {"ne": nepali, "en": sci, "sci": sci, "note": SOURCE_NOTE})


def downgrade() -> None:
    # only the rows this migration added, and only if no forest has recorded them since
    op.execute(
        sa.text(
            "DELETE FROM biodiversity_species WHERE notes = :note "
            "AND id NOT IN (SELECT species_id FROM calculation_biodiversity)"
        ).bindparams(note=SOURCE_NOTE)
    )
