"""ntfp_regulation: the designated NTFP list as a database table (Forest Regulations 2079, Schedule-7), seeded with its 318 entries.

Revision ID: 128_ntfp_regulation
Revises: 127_ntfp_schedule7_species
Create Date: 2026-10-17

Owner decision 2026-10-17: the list must be a database table, because it will be used beyond the plan (an NTFP inventory system later), and
a price rate or a name in a code file cannot be corrected by an admin or amended with the regulation. The table is ``ntfp_regulation``.
The rows come from ``app.core.ntfp_schedule7`` (checked against the published text), loaded once here; from then on the table is the
source and the code file is only the seed.
"""
import uuid

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "128_ntfp_regulation"
down_revision = "127_ntfp_schedule7_species"
branch_labels = None
depends_on = None

CODE = "FR-2079-S7"


def upgrade() -> None:
    table = op.create_table(
        "ntfp_regulation",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("regulation_code", sa.String(40), nullable=False),
        sa.Column("source_ne", sa.String(255), nullable=False),
        sa.Column("source_en", sa.String(255), nullable=False),
        sa.Column("group_code", sa.String(4), nullable=False),
        sa.Column("group_ne", sa.String(120), nullable=False),
        sa.Column("group_en", sa.String(120), nullable=False),
        sa.Column("serial", sa.Integer, nullable=False),
        sa.Column("nepali_name", sa.String(255), nullable=False),
        sa.Column("scientific_name_printed", sa.String(500), nullable=True),
        sa.Column("match_names", postgresql.JSONB, nullable=False, server_default="[]"),
        sa.Column("price_npr", sa.Numeric(12, 2), nullable=False),
        sa.Column("price_unit", sa.String(10), nullable=False, server_default="kg"),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("regulation_code", "group_code", "serial", name="uq_ntfp_regulation_entry"),
        sa.CheckConstraint("price_unit IN ('kg','piece')", name="ck_ntfp_regulation_unit"),
        sa.CheckConstraint("price_npr >= 0", name="ck_ntfp_regulation_price"),
    )
    op.create_index("ix_ntfp_regulation_code", "ntfp_regulation", ["regulation_code"])

    from app.core.ntfp_schedule7 import GROUPS, ROWS, SOURCE, SOURCE_EN, scientific_names

    op.bulk_insert(
        table,
        [
            {
                "id": uuid.uuid4(),
                "regulation_code": CODE,
                "source_ne": SOURCE,
                "source_en": SOURCE_EN,
                "group_code": group,
                "group_ne": GROUPS[group][0],
                "group_en": GROUPS[group][1],
                "serial": serial,
                "nepali_name": nepali,
                "scientific_name_printed": printed or None,
                "match_names": scientific_names(printed),
                "price_npr": price,
                "price_unit": unit,
            }
            for group, serial, nepali, printed, price, unit in ROWS
        ],
    )


def downgrade() -> None:
    op.drop_index("ix_ntfp_regulation_code", table_name="ntfp_regulation")
    op.drop_table("ntfp_regulation")
