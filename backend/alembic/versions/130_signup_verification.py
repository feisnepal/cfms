"""Sign-up verification: designation, verified phone/email, social identities, one-time codes.

Revision ID: 130_signup_verification
Revises: 129_template_source_version
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "130_signup_verification"
down_revision = "129_template_source_version"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("designation", sa.String(20), nullable=True))
    op.add_column("users", sa.Column("sub_division", sa.String(255), nullable=True))
    op.add_column("users", sa.Column("instagram_handle", sa.String(64), nullable=True))
    op.add_column("users", sa.Column("phone_verified_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("users", sa.Column("email_verified_at", sa.DateTime(timezone=True), nullable=True))
    # The limited tier: ACTIVE but never approved by a super admin.
    op.add_column("users", sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("users", sa.Column("approved_by", UUID(as_uuid=True), nullable=True))
    # A Facebook account may share no email; a phone-only account has none yet.
    op.alter_column("users", "email", existing_type=sa.String(255), nullable=True)

    # Everyone who exists today was either approved or is the owner: keep them whole.
    op.execute("UPDATE users SET approved_at = created_at WHERE status = 'ACTIVE'")
    # Existing addresses were entered by or for the owner; trust them so they can use "forgot password".
    op.execute("UPDATE users SET email_verified_at = created_at WHERE email IS NOT NULL")

    # A verified number belongs to exactly one account.
    op.create_index("uq_users_verified_phone", "users", ["phone"], unique=True,
                    postgresql_where=sa.text("phone_verified_at IS NOT NULL"))

    op.create_table(
        "user_identities",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("provider", sa.String(20), nullable=False),
        sa.Column("subject", sa.String(128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("provider", "subject", name="uq_user_identities_provider_subject"),
    )

    # One table for every short-lived secret: phone OTP codes and emailed links.
    # Only a hash is stored; `target` is the phone or email it was sent to.
    op.create_table(
        "auth_challenges",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("purpose", sa.String(24), nullable=False),  # phone_verify | login | password_reset | email_verify
        sa.Column("channel", sa.String(8), nullable=False),   # sms | email
        sa.Column("target", sa.String(255), nullable=False),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True),
        sa.Column("secret_hash", sa.String(64), nullable=False),
        sa.Column("attempts", sa.Integer, nullable=False, server_default="0"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_auth_challenges_target_created", "auth_challenges", ["target", "created_at"])
    op.create_index("ix_auth_challenges_secret_hash", "auth_challenges", ["secret_hash"])


def downgrade() -> None:
    op.drop_table("auth_challenges")
    op.drop_table("user_identities")
    op.drop_index("uq_users_verified_phone", table_name="users")
    # Rows with no email cannot go back to NOT NULL.
    op.execute("DELETE FROM users WHERE email IS NULL")
    op.alter_column("users", "email", existing_type=sa.String(255), nullable=False)
    for col in ("approved_by", "approved_at", "email_verified_at", "phone_verified_at",
                "instagram_handle", "sub_division", "designation"):
        op.drop_column("users", col)
