"""Tamper-evidence and provenance for the documents this system exists to produce.

Revision ID: 059_document_issuance_integrity
Revises: 058_audit_provenance_and_pii_reads
Create Date: 2026-08-27

Why this migration exists (H7.4 / S1-54)
----------------------------------------
Operational plans carry statutory weight -- that is the system's entire reason
to exist. A search for `sha256`, `hashlib`, `signature` or `checksum` across the
document-generation services returns exactly one hit, and it is image caching in
`plan_map_service.py`, not document integrity.

So the artifact has:

* **No content hash.** Nothing can demonstrate that a `.docx` sitting in a
  district forest office is the one this system generated, or that it has not
  been edited since.
* **No provenance binding.** Nothing ties a plan to the geometry version, the
  inventory dataset and the DBH system that produced its numbers -- even though
  `calculations.geometry_version` and `dbh_class_systems` are already in the
  schema and the binding is therefore nearly free.
* **No record of issuance.** `calculation_audit_log` tracks state transitions,
  not document emission. A plan can be produced and no row anywhere says so.

If a plan's figures are ever disputed there is currently no way to establish
which inputs generated them. That is the same standard the report sets for
defects -- detected, attributable, recoverable -- simply never applied to the
legal artifact.

Append-only, and what that does and does not mean
-------------------------------------------------
The report asks for the issuance record to be append-only. This migration adds
a rule that refuses `UPDATE` and `DELETE` on the table, so a row cannot be
altered through the application's own connection. That is a real constraint, not
a convention in a docstring.

It is honest about its limit: a superuser can drop the rule. It defends against
the application, a mistaken migration and a careless script -- not against
someone with full database rights. Genuine immutability needs an append-only
store off this host, which is task 5.3's territory.

Why the hash is of the FINAL bytes
-----------------------------------
The verification code is embedded in the document, so the code must exist before
the bytes are final, and the hash must be taken after. Hashing first and
embedding afterwards would produce a hash of a document that was never issued --
a verification that fails for every genuine copy, which is worse than none.
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "059_document_issuance_integrity"
down_revision = "058_audit_provenance_and_pii_reads"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "document_issuances",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),

        # Short, human-quotable, printed in the document. Somebody reads this
        # down a telephone from a paper copy, so it is not a UUID.
        sa.Column("verification_code", sa.String(24), nullable=False, unique=True),

        # SHA-256 of the exact bytes that were sent to the client.
        sa.Column("sha256", sa.String(64), nullable=False, index=True),
        sa.Column("byte_size", sa.BigInteger, nullable=False),

        # No foreign key, for the same reason as `household_access_log`:
        # migration 057 made the calculation keys cascade, and the record that a
        # statutory document was issued must outlive the deletion of the forest
        # it describes.
        sa.Column("calculation_id", postgresql.UUID(as_uuid=True), nullable=True, index=True),
        sa.Column("plan_id", postgresql.UUID(as_uuid=True), nullable=True, index=True),

        sa.Column("document_type", sa.String(32), nullable=False),
        sa.Column("filename", sa.String(255), nullable=True),
        sa.Column("forest_name", sa.String(255), nullable=True),

        # --- provenance: which inputs produced these numbers ---------------
        sa.Column("geometry_version", sa.BigInteger, nullable=True),
        sa.Column("inventory_calculation_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("field_inventory_calculation_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("dbh_system_id", postgresql.UUID(as_uuid=True), nullable=True),
        # Anything else worth binding that has no column of its own yet.
        sa.Column("provenance", postgresql.JSONB, nullable=True),

        # --- who issued it, from where -------------------------------------
        sa.Column("issued_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("ip_address", sa.String(64), nullable=True),
        sa.Column("client_type", sa.String(32), nullable=True),
        # Ties issuance to its request's log lines (H3.9).
        sa.Column("correlation_id", sa.String(64), nullable=True),

        # H1.14 / S1-74: name the schema. cf_db carries
        # `search_path = rasters, public, sde`.
        schema="public",
    )
    op.create_index("ix_document_issuances_issued_at", "document_issuances",
                    ["issued_at"], schema="public")

    # Append-only. See the module docstring for what this does and does not
    # defend against.
    op.execute(sa.text("""
        CREATE RULE document_issuances_no_update AS
            ON UPDATE TO public.document_issuances DO INSTEAD NOTHING
    """))
    op.execute(sa.text("""
        CREATE RULE document_issuances_no_delete AS
            ON DELETE TO public.document_issuances DO INSTEAD NOTHING
    """))


def downgrade() -> None:
    op.execute(sa.text("DROP RULE IF EXISTS document_issuances_no_delete ON public.document_issuances"))
    op.execute(sa.text("DROP RULE IF EXISTS document_issuances_no_update ON public.document_issuances"))
    op.drop_index("ix_document_issuances_issued_at", table_name="document_issuances",
                  schema="public")
    op.drop_table("document_issuances", schema="public")
