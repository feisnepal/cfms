"""Chatbot C1.1: who may use the assistant, how much they used, and what they said.

Revision ID: 147_chatbot_access_usage_messages
Revises: 146_forum_notifications
Create Date: 2026-11-10

CHATBOT_PLAN.md section 4. Every row belongs to a user (ON DELETE CASCADE). **No row links to ``calculations`` or any forest**: a deleted
forest must leave no chat row behind and none may block it (forest-delete rule); a forest id only ever appears as a value in a short-lived
confirm token (C6) or the existing audit trail.
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "147_chatbot_access_usage_messages"
down_revision = "146_forum_notifications"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # One row per user who asked for or was given access. D2/D7: approval by a super admin now; ``plan`` leaves room for payment later
    # without a redesign (no payment code is built).
    op.create_table(
        "chat_access",
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("status", sa.String(10), nullable=False, server_default="requested"),
        sa.Column("daily_cap_tokens", sa.Integer, nullable=False, server_default="100000"),  # D10
        sa.Column("plan", sa.String(20), nullable=False, server_default="approved"),         # later: free / paid
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("request_note", sa.Text, nullable=True),
        sa.Column("approved_by_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("status IN ('requested','approved','revoked')", name="ck_chat_access_status"),
        sa.CheckConstraint("daily_cap_tokens >= 0", name="ck_chat_access_cap"),
    )
    op.create_index("ix_chat_access_status", "chat_access", ["status"])

    # Tokens per user per day (Nepal calendar day, computed in the service). ``reserved`` is the reserve-then-settle hold (R2).
    op.create_table(
        "chat_usage",
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("day", sa.Date, primary_key=True),
        sa.Column("tokens_in", sa.Integer, nullable=False, server_default="0"),
        sa.Column("tokens_out", sa.Integer, nullable=False, server_default="0"),
        sa.Column("reserved", sa.Integer, nullable=False, server_default="0"),
        sa.Column("messages", sa.Integer, nullable=False, server_default="0"),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("tokens_in >= 0 AND tokens_out >= 0 AND reserved >= 0 AND messages >= 0", name="ck_chat_usage_nonneg"),
    )
    op.create_index("ix_chat_usage_day", "chat_usage", ["day"])

    # The conversation. Message text is kept 30 days, then ``content`` is nulled and only the counters stay (D11, R13).
    op.create_table(
        "chat_messages",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("role", sa.String(10), nullable=False),
        sa.Column("content", sa.Text, nullable=True),
        sa.Column("tool_names", postgresql.ARRAY(sa.String(60)), nullable=False, server_default="{}"),
        sa.Column("provider", sa.String(30), nullable=True),
        sa.Column("model", sa.String(80), nullable=True),
        sa.Column("tokens_in", sa.Integer, nullable=False, server_default="0"),
        sa.Column("tokens_out", sa.Integer, nullable=False, server_default="0"),
        sa.Column("feedback", sa.SmallInteger, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("content_purged_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("role IN ('user','assistant','tool')", name="ck_chat_message_role"),
        sa.CheckConstraint("feedback IS NULL OR feedback IN (-1, 1)", name="ck_chat_message_feedback"),
    )
    op.create_index("ix_chat_messages_user_created", "chat_messages", ["user_id", "created_at"])
    op.create_index("ix_chat_messages_session_created", "chat_messages", ["session_id", "created_at"])
    # the 30-day purge only looks at rows that still hold text
    op.create_index("ix_chat_messages_unpurged", "chat_messages", ["created_at"], postgresql_where=sa.text("content IS NOT NULL"))
    op.create_index("ix_chat_messages_feedback", "chat_messages", ["created_at"], postgresql_where=sa.text("feedback = -1"))

    # One row (id = 1): the kill switch and the shared daily ceiling (R3). A free-tier provider has one pool for everybody.
    op.create_table(
        "chat_settings",
        sa.Column("id", sa.SmallInteger, primary_key=True),
        sa.Column("enabled", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("pool_daily_tokens", sa.Integer, nullable=True),  # null = no shared ceiling
        sa.Column("updated_by_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("id = 1", name="ck_chat_settings_single_row"),
    )
    op.execute("INSERT INTO chat_settings (id, enabled) VALUES (1, true)")


def downgrade() -> None:
    op.drop_table("chat_settings")
    op.drop_table("chat_messages")
    op.drop_table("chat_usage")
    op.drop_table("chat_access")
