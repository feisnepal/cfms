"""ntfp_method_value: a Schedule-7 locator listed a line twice when one printed line names the species under several Latin names ("Schedule-7 lines क 1, क 1").

Revision ID: 139_ntfp_value_locator_dedupe
Revises: 138_ntfp_method_sources
Create Date: 2026-10-22

Data fix for rows seeded by migration 138 before the seed code was corrected; a no-op on a database seeded after it.
"""
import re

import sqlalchemy as sa
from alembic import op

revision = "139_ntfp_value_locator_dedupe"
down_revision = "138_ntfp_method_sources"
branch_labels = None
depends_on = None

PREFIX = "Schedule-7 lines "


def upgrade() -> None:
    bind = op.get_bind()
    rows = bind.execute(sa.text("SELECT id, locator FROM ntfp_method_value WHERE source_key = 'S7-2079' AND locator LIKE :p"), {"p": PREFIX + "%"}).all()
    for rid, locator in rows:
        parts = [p.strip() for p in re.split(r",\s*", locator[len(PREFIX):]) if p.strip()]
        fixed = PREFIX + ", ".join(dict.fromkeys(parts))
        if fixed != locator:
            bind.execute(sa.text("UPDATE ntfp_method_value SET locator = :l WHERE id = :i"), {"l": fixed, "i": rid})


def downgrade() -> None:
    pass  # the duplicates were a defect: nothing to restore
