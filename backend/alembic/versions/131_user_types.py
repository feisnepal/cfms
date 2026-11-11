"""User types (official / student / researcher / organization), organisation groups, access expiry.

Revision ID: 131_user_types
Revises: 130_signup_verification
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "131_user_types"
down_revision = "130_signup_verification"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("user_type", sa.String(16), nullable=True))
    op.add_column("users", sa.Column("type_details", JSONB, nullable=True))
    # Student / researcher access can end (end of the academic year); null means no end.
    op.add_column("users", sa.Column("access_expires_at", sa.DateTime(timezone=True), nullable=True))
    # 'owner' made the organisation, 'member' joined it; an owner of a verified organisation can vouch for members.
    op.add_column("users", sa.Column("org_member_role", sa.String(8), nullable=True))
    op.add_column("users", sa.Column("org_vouched_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("users", sa.Column("org_vouched_by", UUID(as_uuid=True), nullable=True))

    op.add_column("organizations", sa.Column("kind", sa.String(16), nullable=True))
    op.add_column("organizations", sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("organizations", sa.Column("created_by", UUID(as_uuid=True), nullable=True))

    # Anyone who already declared a designation is a sub-division official; the rest stay unspecified (legacy).
    op.execute("UPDATE users SET user_type = 'official' WHERE designation IS NOT NULL")
    # Organisations that existed before sign-up types were made by the owner.
    op.execute("UPDATE organizations SET verified_at = created_at")


def downgrade() -> None:
    for col in ("created_by", "verified_at", "kind"):
        op.drop_column("organizations", col)
    for col in ("org_vouched_by", "org_vouched_at", "org_member_role", "access_expires_at", "type_details", "user_type"):
        op.drop_column("users", col)
