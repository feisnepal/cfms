"""Durable idempotency records for mobile-facing writes.

Revision ID: 053_idempotency_records
Revises: 052_drop_redundant_jti_unique
Create Date: 2026-08-25

Why this migration exists (H2.17 / S2-17)
-----------------------------------------
A field device uploads over a connection that drops, then retries. Without a
durable record of what has already been accepted, the retry writes a second
copy of the same trees, plots or households -- and those rows feed the volume,
biomass and carbon figures in a statutory document. A duplicate tree looks
exactly like a real tree, so nothing surfaces it.

An idempotency mechanism already existed, in Redis, covering 2 of 86
mobile-facing write endpoints. It could not be extended as it stood:

* it checked and then acted, so two concurrent retries could both pass the
  check and both execute -- the exact duplicate it was there to prevent;
* it failed OPEN. A Redis error was reported as "not seen before", so the guard
  switched itself off precisely when the system was under stress;
* it fell through when the key existed but the cached response did not, which
  is what an eviction or a crashed first attempt leaves behind;
* the request body was not part of the key, so the same key with different data
  returned the first response and silently discarded the second payload; and
* the in-memory fallback was per-process and never expired -- useless once
  gunicorn runs multiple workers (task 3.3), and an unbounded leak until then.

The UNIQUE constraint below is the whole point. Reservation becomes
`INSERT ... ON CONFLICT DO NOTHING`: the database decides who got there first,
atomically, in one statement, and decides once even across workers. The record
is durable, so a Redis restart no longer forgets what has been accepted.

`expires_at` is indexed because the cleanup job deletes by it, and a sequential
scan over this table on a busy sync day is not something to discover in
production.
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "053_idempotency_records"
down_revision = "052_drop_redundant_jti_unique"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "idempotency_records",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        # Client-supplied opaque string, not a uuid column: a malformed key
        # should be rejected by validation with a clear message, not by a cast
        # error inside the database.
        sa.Column("key", sa.String(255), nullable=False),
        sa.Column("resource", sa.String(255), nullable=False),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("state", sa.String(16), nullable=False,
                  server_default=sa.text("'in_flight'")),
        sa.Column("response", postgresql.JSONB, nullable=True),
        sa.Column("error", sa.Text, nullable=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        # H1.14 / S1-74: name the schema explicitly. cf_db carries
        # `search_path = rasters, public, sde`, so an unqualified create_table
        # lands in `rasters` -- which is how six application tables ended up
        # beside the raster layers and had to be moved by migration 051.
        schema="public",
    )

    # The mechanism rests on this one constraint.
    op.create_unique_constraint(
        "uq_idempotency_key_resource", "idempotency_records",
        ["key", "resource"], schema="public",
    )

    # The cleanup job deletes by expiry.
    op.create_index(
        "ix_idempotency_expires_at", "idempotency_records", ["expires_at"],
        schema="public",
    )
    op.create_index(
        "ix_idempotency_records_user_id", "idempotency_records", ["user_id"],
        schema="public",
    )


def downgrade() -> None:
    op.drop_index("ix_idempotency_records_user_id",
                  table_name="idempotency_records", schema="public")
    op.drop_index("ix_idempotency_expires_at",
                  table_name="idempotency_records", schema="public")
    op.drop_constraint("uq_idempotency_key_resource", "idempotency_records",
                       schema="public")
    op.drop_table("idempotency_records", schema="public")
