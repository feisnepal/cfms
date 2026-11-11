"""Community Q&A forum: posts, revisions, tags, the action ledger, reputation, flags, subscriptions (F0).

Revision ID: 143_forum_core
Revises: 142_ntfp_plot_presence_photos
Create Date: 2026-10-27

See ``FORUM_SPEC.md``. No table links to ``calculations``: a question outlives a forest, so a post carries its workflow step and no forest id.
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "143_forum_core"
down_revision = "142_ntfp_plot_presence_photos"
branch_labels = None
depends_on = None

UUID = postgresql.UUID(as_uuid=True)


def _id():
    return sa.Column("id", UUID, primary_key=True, server_default=sa.text("gen_random_uuid()"))


def _user(name, *, nullable, ondelete, **kw):
    return sa.Column(name, UUID, sa.ForeignKey("users.id", ondelete=ondelete), nullable=nullable, **kw)


def _now(name):
    return sa.Column(name, sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now())


def upgrade() -> None:
    op.create_table(
        "forum_profiles",
        sa.Column("user_id", UUID, sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("reputation", sa.Integer, nullable=False, server_default="0"),
        sa.Column("about", sa.Text, nullable=True),
        sa.Column("is_moderator", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("last_seen", sa.DateTime(timezone=True), nullable=True),
        _now("created_at"),
    )
    op.create_table(
        "forum_posts",
        _id(),
        sa.Column("kind", sa.String(10), nullable=False),
        sa.Column("parent_id", UUID, sa.ForeignKey("forum_posts.id", ondelete="CASCADE"), nullable=True),
        sa.Column("root_id", UUID, sa.ForeignKey("forum_posts.id", ondelete="CASCADE"), nullable=True),
        _user("author_id", nullable=True, ondelete="SET NULL"),
        sa.Column("title", sa.String(300), nullable=True),
        sa.Column("body_md", sa.Text, nullable=False),
        sa.Column("workflow_step", sa.String(40), nullable=True),
        sa.Column("score", sa.Integer, nullable=False, server_default="0"),
        sa.Column("answer_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("comment_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("view_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("flag_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("active_revision", sa.Integer, nullable=False, server_default="1"),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closed_reason", sa.String(10), nullable=True),
        sa.Column("duplicate_of_id", UUID, sa.ForeignKey("forum_posts.id", ondelete="SET NULL"), nullable=True),
        sa.Column("pending_review", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        _user("deleted_by_id", nullable=True, ondelete="SET NULL"),
        _now("created_at"),
        _now("last_activity_at"),
        _user("last_activity_by_id", nullable=True, ondelete="SET NULL"),
        sa.CheckConstraint("kind IN ('question','answer','comment')", name="ck_forum_post_kind"),
        sa.CheckConstraint("closed_reason IS NULL OR closed_reason IN ('duplicate','off_topic','resolved')", name="ck_forum_post_closed_reason"),
    )
    op.create_index("ix_forum_posts_kind_activity", "forum_posts", ["kind", "last_activity_at"])
    op.create_index("ix_forum_posts_kind_created", "forum_posts", ["kind", "created_at"])
    op.create_index("ix_forum_posts_kind_score", "forum_posts", ["kind", "score"])
    op.create_index("ix_forum_posts_parent_kind", "forum_posts", ["parent_id", "kind"])
    op.create_index("ix_forum_posts_author_kind_created", "forum_posts", ["author_id", "kind", "created_at"])
    op.create_index("uq_forum_posts_one_accepted", "forum_posts", ["root_id"], unique=True, postgresql_where=sa.text("accepted_at IS NOT NULL"))

    op.create_table(
        "forum_post_revisions",
        _id(),
        sa.Column("post_id", UUID, sa.ForeignKey("forum_posts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("revision", sa.Integer, nullable=False),
        sa.Column("title", sa.String(300), nullable=True),
        sa.Column("body_md", sa.Text, nullable=False),
        sa.Column("tag_names", sa.String(200), nullable=True),
        sa.Column("summary", sa.String(300), nullable=True),
        _user("author_id", nullable=True, ondelete="SET NULL"),
        _now("revised_at"),
        sa.UniqueConstraint("post_id", "revision", name="uq_forum_post_revision"),
    )

    op.create_table(
        "forum_tags",
        _id(),
        sa.Column("name", sa.String(80), nullable=False, unique=True),
        sa.Column("description_md", sa.Text, nullable=True),
        sa.Column("used_count", sa.Integer, nullable=False, server_default="0"),
        _user("created_by_id", nullable=True, ondelete="SET NULL"),
        _now("created_at"),
    )
    op.create_table(
        "forum_post_tags",
        sa.Column("post_id", UUID, sa.ForeignKey("forum_posts.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("tag_id", UUID, sa.ForeignKey("forum_tags.id", ondelete="CASCADE"), primary_key=True),
    )
    op.create_table(
        "forum_tag_synonyms",
        sa.Column("source_name", sa.String(80), primary_key=True),
        sa.Column("tag_id", UUID, sa.ForeignKey("forum_tags.id", ondelete="CASCADE"), nullable=False),
        _user("created_by_id", nullable=True, ondelete="SET NULL"),
        _now("created_at"),
    )
    op.create_table(
        "forum_tag_marks",
        sa.Column("user_id", UUID, sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("tag_id", UUID, sa.ForeignKey("forum_tags.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("reason", sa.String(12), nullable=False),
        sa.CheckConstraint("reason IN ('interesting','ignored')", name="ck_forum_tag_mark_reason"),
    )

    op.create_table(
        "forum_actions",
        _id(),
        _user("user_id", nullable=False, ondelete="CASCADE"),
        sa.Column("post_id", UUID, sa.ForeignKey("forum_posts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("action_type", sa.String(12), nullable=False),
        _now("created_at"),
        sa.Column("canceled_at", sa.DateTime(timezone=True), nullable=True),
        _user("canceled_by_id", nullable=True, ondelete="SET NULL"),
        sa.CheckConstraint("action_type IN ('vote_up','vote_down','accept','flag','favorite','close','delete')", name="ck_forum_action_type"),
    )
    op.create_index("ix_forum_actions_post", "forum_actions", ["post_id", "action_type"])
    op.create_index("ix_forum_actions_user_date", "forum_actions", ["user_id", "created_at"])
    op.create_index(
        "uq_forum_actions_live_single", "forum_actions", ["user_id", "post_id", "action_type"], unique=True,
        postgresql_where=sa.text("canceled_at IS NULL AND action_type IN ('vote_up','vote_down','flag','favorite')"),
    )
    op.create_table(
        "forum_reputation_events",
        _id(),
        _user("user_id", nullable=False, ondelete="CASCADE"),
        sa.Column("action_id", UUID, sa.ForeignKey("forum_actions.id", ondelete="CASCADE"), nullable=True),
        sa.Column("value", sa.Integer, nullable=False),
        sa.Column("by_cancel", sa.Boolean, nullable=False, server_default="false"),
        _now("created_at"),
    )
    op.create_index("ix_forum_rep_user", "forum_reputation_events", ["user_id", "created_at"])

    op.create_table(
        "forum_flags",
        _id(),
        sa.Column("post_id", UUID, sa.ForeignKey("forum_posts.id", ondelete="CASCADE"), nullable=False),
        _user("user_id", nullable=True, ondelete="SET NULL"),
        sa.Column("reason", sa.String(300), nullable=True),
        sa.Column("confidence", sa.Float, nullable=True),
        sa.Column("source", sa.String(32), nullable=True),
        _now("created_at"),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        _user("resolved_by_id", nullable=True, ondelete="SET NULL"),
        sa.Column("resolution", sa.String(12), nullable=True),
        sa.CheckConstraint("resolution IS NULL OR resolution IN ('dismissed','hidden','deleted','user_warned')", name="ck_forum_flag_resolution"),
    )
    op.create_index("ix_forum_flags_open", "forum_flags", ["resolved_at", "created_at"])

    op.create_table(
        "forum_subscriptions",
        sa.Column("user_id", UUID, sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("post_id", UUID, sa.ForeignKey("forum_posts.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("auto", sa.Boolean, nullable=False, server_default="true"),
        _now("last_view"),
    )
    op.create_table(
        "forum_notification_prefs",
        sa.Column("user_id", UUID, sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("enabled", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("on_answer_to_mine", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("on_comment_reply", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("on_accepted", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("on_new_in_watched_tags", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("email_frequency", sa.String(10), nullable=False, server_default="immediate"),
        sa.CheckConstraint("email_frequency IN ('immediate','daily','weekly','never')", name="ck_forum_prefs_frequency"),
    )


def downgrade() -> None:
    for table in (
        "forum_notification_prefs", "forum_subscriptions", "forum_flags", "forum_reputation_events", "forum_actions",
        "forum_tag_marks", "forum_tag_synonyms", "forum_post_tags", "forum_tags", "forum_post_revisions", "forum_posts", "forum_profiles",
    ):
        op.drop_table(table)
