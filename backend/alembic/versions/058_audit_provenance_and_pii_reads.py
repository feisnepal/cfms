"""Client provenance on geometry audits; a read log for household PII.

Revision ID: 058_audit_provenance_and_pii_reads
Revises: 057_cascade_remaining_calculation_fks
Create Date: 2026-08-27

Why this migration exists (H8.7 / S2-68)
----------------------------------------
S2-68 makes two demands beyond wiring the geometry audit, and they are separate
problems.

**1. Client forensics.** No audit table records the client, the address, or the
version. The report is blunt about what that cost: during the audit it was
"impossible to determine from the data which writes came from the mobile app and
which from the web client", which blocked any attempt to characterise the mobile
client's behaviour from the server side. The same blindness will block the
investigation the day a sync defect corrupts data.

Provenance is already being written into `new_properties` as JSON by
`editing.py::_audit_geometry_write`. That works, and it is the wrong shape for
the question people will ask: "show me every write from a mobile client in
March" should be an indexed predicate, not a JSON scan. These are first-class
columns, backfilled from the JSON already present.

**2. Household reads are unlogged.** `household_information` holds caste
classification and precise coordinates (S1-53). There is no record of who read
or exported those 298 rows -- and for special-category data an access log is
normally a hard requirement rather than a nicety. The write side is audited by
`calculation_audit_log`; the read side has nothing at all.

What is NOT here, and why
-------------------------
`device_id` and `app_version` are part of S2-68 and are deliberately absent.
`device_id` needs the `devices` table from task 2.16; `app_version` needs the
`X-App-Version` header from task 8.4. Both are unstarted. Adding the columns now
would produce fields that are always NULL and a tracker row claiming the work is
done -- which is the exact failure this whole phase keeps finding. They are
recorded as blocked instead, and added when there is something to put in them.
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "058_audit_provenance_and_pii_reads"
down_revision = "057_cascade_remaining_calculation_fks"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- 1. provenance on the geometry audit -------------------------------
    op.add_column("geometry_audits",
                  sa.Column("client_type", sa.String(32), nullable=True),
                  schema="public")
    op.add_column("geometry_audits",
                  sa.Column("ip_address", sa.String(64), nullable=True),
                  schema="public")
    # Ties an audit row to the log lines of the request that produced it (H3.9).
    # Before 3.9 the correlation id reached a response header and nothing else,
    # so this column would have been unfillable.
    op.add_column("geometry_audits",
                  sa.Column("correlation_id", sa.String(64), nullable=True),
                  schema="public")
    op.add_column("geometry_audits",
                  sa.Column("user_agent", sa.String(300), nullable=True),
                  schema="public")

    # "Every write from a mobile client since March" is the question this table
    # exists to answer, and it should not be a sequential scan of JSON.
    op.create_index("ix_geometry_audits_client_type", "geometry_audits",
                    ["client_type"], schema="public")
    op.create_index("ix_geometry_audits_correlation_id", "geometry_audits",
                    ["correlation_id"], schema="public")

    # Backfill from the JSON already being written, so rows recorded between
    # the wiring and this migration are not second-class.
    op.execute(sa.text("""
        UPDATE public.geometry_audits
        SET client_type    = COALESCE(client_type,    new_properties->>'client_type'),
            ip_address     = COALESCE(ip_address,     new_properties->>'ip_address'),
            correlation_id = COALESCE(correlation_id, new_properties->>'correlation_id'),
            user_agent     = COALESCE(user_agent,     new_properties->>'user_agent')
        WHERE new_properties IS NOT NULL
    """))

    # --- 2. household read-access log --------------------------------------
    op.create_table(
        "household_access_log",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        # No foreign key to `calculations`. This log must outlive the data it
        # describes -- a deleted calculation does not un-happen the reads, and
        # migration 057 made those keys cascade.
        sa.Column("calculation_id", postgresql.UUID(as_uuid=True), nullable=True,
                  index=True),
        # NULL for a listing or an export, set when one record was fetched.
        sa.Column("household_id", postgresql.UUID(as_uuid=True), nullable=True),
        # "list" | "detail" | "export" | "summary" -- what was seen, since
        # exporting 298 households is not the same event as opening one.
        sa.Column("access_type", sa.String(32), nullable=False),
        sa.Column("record_count", sa.Integer, nullable=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True, index=True),
        sa.Column("ip_address", sa.String(64), nullable=True),
        sa.Column("client_type", sa.String(32), nullable=True),
        sa.Column("correlation_id", sa.String(64), nullable=True),
        sa.Column("accessed_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        # H1.14 / S1-74: name the schema explicitly. cf_db carries
        # `search_path = rasters, public, sde`, so an unqualified create_table
        # lands in `rasters` -- which is how six application tables ended up
        # beside the raster layers and had to be moved by migration 051.
        schema="public",
    )
    op.create_index("ix_household_access_log_accessed_at", "household_access_log",
                    ["accessed_at"], schema="public")


def downgrade() -> None:
    op.drop_index("ix_household_access_log_accessed_at",
                  table_name="household_access_log", schema="public")
    op.drop_table("household_access_log", schema="public")

    op.drop_index("ix_geometry_audits_correlation_id",
                  table_name="geometry_audits", schema="public")
    op.drop_index("ix_geometry_audits_client_type",
                  table_name="geometry_audits", schema="public")
    for column in ("user_agent", "correlation_id", "ip_address", "client_type"):
        op.drop_column("geometry_audits", column, schema="public")
