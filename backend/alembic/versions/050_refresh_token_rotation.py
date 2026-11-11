"""Refresh-token rotation and instant revocation (H2.5 / S1-05).

`POST /auth/refresh` decoded the presented access token with
`options={"verify_exp": False}` and issued a fresh one. Any access token ever
minted — including one that expired months ago — could be exchanged for a live
token, indefinitely, by anyone holding it. There was no way to revoke a session:
logging out discarded the token client-side and left it fully valid on the
server. One stolen token was permanent access.

This adds the storage that makes sessions revocable:

`refresh_tokens` records every refresh token by `jti`, grouped into a `family`
per login. Refreshing consumes one and issues its successor. Presenting a token
that has already been consumed means two parties hold the same credential, so
the whole family is revoked rather than the single token — the legitimate holder
is logged out and the thief gains nothing.

`users.token_generation` is the revocation switch for access tokens, which are
stateless and cannot be individually recalled. Each access token carries the
generation it was minted under; logout and password change increment the
counter, and every token stamped with an older generation stops working. It
costs no extra query — `get_current_user` already loads the user row on every
request.

A counter rather than a timestamp on purpose. The obvious design is
"tokens_valid_after" and it does not work: JWT `iat` has one-second resolution,
so a token issued 300ms before logout carries the same second as the logout and
survives it, while rounding the cutoff up instead locks out the legitimate login
that follows within the same second. An integer has no such ambiguity.

Revision ID: 050_refresh_token_rotation
Revises: 049_fix_plot_location
Create Date: 2026-08-20
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "050_refresh_token_rotation"
down_revision = "049_fix_plot_location"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "refresh_tokens",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        # The token's own jti. Unique because a replay of a consumed token is
        # the signal this table exists to detect.
        sa.Column("jti", sa.String(64), nullable=False, unique=True),
        # All tokens descended from one login. Revoked as a unit on reuse.
        sa.Column("family", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("issued_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        # Set when this token is exchanged. A second exchange attempt is reuse.
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_reason", sa.String(64), nullable=True),
        # Coarse provenance, for telling a stolen session apart from a second
        # device when someone reports a reuse alert. Deliberately not an IP.
        sa.Column("user_agent", sa.String(256), nullable=True),
    )
    op.create_index("ix_refresh_tokens_jti", "refresh_tokens", ["jti"], unique=True)
    op.create_index("ix_refresh_tokens_family", "refresh_tokens", ["family"])
    op.create_index("ix_refresh_tokens_user_id", "refresh_tokens", ["user_id"])
    op.create_index("ix_refresh_tokens_expires_at", "refresh_tokens", ["expires_at"])

    op.add_column(
        "users",
        sa.Column("token_generation", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("users", "token_generation")
    op.drop_index("ix_refresh_tokens_expires_at", table_name="refresh_tokens")
    op.drop_index("ix_refresh_tokens_user_id", table_name="refresh_tokens")
    op.drop_index("ix_refresh_tokens_family", table_name="refresh_tokens")
    op.drop_index("ix_refresh_tokens_jti", table_name="refresh_tokens")
    op.drop_table("refresh_tokens")
