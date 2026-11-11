"""Forum F1b: screenshots on posts.

Revision ID: 145_forum_attachments
Revises: 144_forum_search_and_tags
Create Date: 2026-10-27

Files live under ``uploads/forum/<post id>/``; a row goes with its post. No link to ``calculations``.
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "145_forum_attachments"
down_revision = "144_forum_search_and_tags"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "forum_attachments",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("post_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("forum_posts.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("uploader_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("file_name", sa.String(255), nullable=False),
        sa.Column("stored_name", sa.String(80), nullable=False),
        sa.Column("content_type", sa.String(40), nullable=False),
        sa.Column("size_bytes", sa.Integer, nullable=False),
        sa.Column("width", sa.Integer, nullable=False),
        sa.Column("height", sa.Integer, nullable=False),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_forum_attachments_uploader_day", "forum_attachments", ["uploader_id", "created_at"])


def downgrade() -> None:
    op.drop_table("forum_attachments")
