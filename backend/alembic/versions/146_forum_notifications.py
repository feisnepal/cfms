"""Forum F5: the notifications a member is owed (emailed at once or in a digest).

Revision ID: 146_forum_notifications
Revises: 145_forum_attachments
Create Date: 2026-10-28

A row goes with its post and with its user. No link to ``calculations``.
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "146_forum_notifications"
down_revision = "145_forum_attachments"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "forum_notifications",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("post_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("forum_posts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("question_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("forum_posts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("emailed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("kind IN ('answer','comment','accepted','new_in_tag')", name="ck_forum_notification_kind"),
    )
    op.create_index("ix_forum_notifications_pending", "forum_notifications", ["user_id", "emailed_at"])
    op.create_index("ix_forum_notifications_post", "forum_notifications", ["post_id"])
    op.create_index("ix_forum_notifications_question", "forum_notifications", ["question_id"])


def downgrade() -> None:
    op.drop_table("forum_notifications")
