"""The archive a deleted calculation goes into. Nothing is destroyed.

Owner's decision, 2026-08-27: a deleted calculation is kept "in another table in
the intact way, separated from all other processes, like it is dead". No
permanent delete; a super admin may export it, and there is deliberately no
restore path.

`services/calculation_archive.py` writes these rows, immediately before the
delete and in the same transaction. Migrations 056 and 057 made the foreign
keys to `calculations.id` cascade, which is what allows the delete to succeed at
all -- before them, any calculation that had ever been submitted was
undeletable, because `log_state_transition` writes `calculation_audit_log` and
that key was NO ACTION.

**Those cascades are safe only because the archive runs first.** If archiving
were ever made conditional, they would quietly begin destroying exactly the data
this table exists to keep.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Index, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID

from ..core.database import Base


class DeletedCalculation(Base):
    """One snapshot per deleted calculation."""

    __tablename__ = "deleted_calculations"
    __table_args__ = (
        Index("ix_deleted_calculations_deleted_at", "deleted_at"),
        # Named explicitly, and note the `ix_public_` prefix: migration 056
        # created this table with `op.create_table(..., schema="public")` and
        # `index=True` on the column, and alembic folds the schema into the
        # generated index name. The model's own `index=True` would produce
        # `ix_deleted_calculations_original_calculation_id` instead, and the
        # difference shows up as permanent schema drift -- an index reported
        # both added and removed on every check.
        #
        # Matching the database rather than renaming it: the name is
        # functionally irrelevant and a migration to change it would be a
        # deployment step bought for cosmetics. Worth knowing for the next
        # table created with an explicit schema.
        Index(
            "ix_public_deleted_calculations_original_calculation_id",
            "original_calculation_id",
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # Deliberately NOT a foreign key. The row it names is gone by design, which
    # is the whole point of this table -- a constraint would make it impossible
    # to write the one record that matters.
    original_calculation_id = Column(UUID(as_uuid=True), nullable=False)

    # Denormalised out of the payload so a super admin can find "that Rukum
    # forest somebody deleted last year" without grepping a JSONB column.
    forest_name = Column(String(255), nullable=True)
    owner_user_id = Column(UUID(as_uuid=True), nullable=True)

    # The calculation row plus every row that referenced it. Geometry is stored
    # as WKT rather than the driver's binary EWKB: an archive nobody can read is
    # not an archive, and WKT survives a PostGIS upgrade in a way a blob may not.
    payload = Column(JSONB, nullable=False)

    # Counts lifted out of the payload so the listing endpoint does not have to
    # parse megabytes of JSON to show a row.
    row_count = Column(Integer, nullable=False, default=0, server_default=text("0"))
    table_count = Column(Integer, nullable=False, default=0, server_default=text("0"))

    deleted_by = Column(UUID(as_uuid=True), nullable=True)
    deleted_by_role = Column(String(32), nullable=True)
    reason = Column(Text, nullable=True)
    deleted_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        server_default=text("now()"),
        nullable=False,
    )

    def __repr__(self) -> str:
        return (
            f"<DeletedCalculation(forest_name={self.forest_name!r}, "
            f"rows={self.row_count}, deleted_at={self.deleted_at})>"
        )
