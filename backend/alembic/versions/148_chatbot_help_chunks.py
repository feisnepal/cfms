"""Chatbot C1.4: the help text the assistant answers from, searchable in Nepali and English.

Revision ID: 148_chatbot_help_chunks
Revises: 147_chatbot_access_usage_messages
Create Date: 2026-11-10

One row per passage: a fact card written from the project's own rules (``source = 'card'``), later accepted forum answers and guideline text
(C1.4a). The search column uses the ``simple`` text-search config, as the forum does, so Devanagari words are kept whole. No link to a
forest: help text is not forest data.
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "148_chatbot_help_chunks"
down_revision = "147_chatbot_access_usage_messages"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "chat_help_chunks",
        sa.Column("id", sa.String(80), primary_key=True),
        sa.Column("source", sa.String(12), nullable=False, server_default="card"),
        sa.Column("source_ref", sa.Text, nullable=True),
        sa.Column("title", sa.Text, nullable=False),
        sa.Column("title_ne", sa.Text, nullable=True),
        sa.Column("body", sa.Text, nullable=False),
        sa.Column("keywords", sa.Text, nullable=False, server_default=""),
        sa.Column("steps", postgresql.ARRAY(sa.String(40)), nullable=False, server_default="{}"),
        sa.Column("active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("source IN ('card','forum','guideline')", name="ck_chat_help_source"),
    )
    # title and keywords weigh more than the body (A over B), so a question that names the topic finds the card that is about it
    op.execute(
        "ALTER TABLE chat_help_chunks ADD COLUMN search_vector tsvector GENERATED ALWAYS AS ("
        "setweight(to_tsvector('simple', coalesce(title, '') || ' ' || coalesce(title_ne, '') || ' ' || keywords), 'A') || "
        "setweight(to_tsvector('simple', body), 'B')) STORED"
    )
    op.create_index("ix_chat_help_search", "chat_help_chunks", ["search_vector"], postgresql_using="gin")
    op.create_index("ix_chat_help_source_active", "chat_help_chunks", ["source", "active"])


def downgrade() -> None:
    op.drop_table("chat_help_chunks")
