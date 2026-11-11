"""
WorkspaceLayout model — per-user persistent workspace layout.

Stores the resizable-panel layout (sizes + collapsed state) for the map
design UI. One row per (user_id, layout_key); the payload is an opaque JSON
blob so the frontend can evolve the schema without backend migrations.
"""
from sqlalchemy import Index, Column, Integer, String, DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.sql import func

from ..core.database import Base


class WorkspaceLayout(Base):
    __tablename__ = "workspace_layouts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    layout_key = Column(String(64), nullable=False, default="workspace")
    layout_json = Column(JSONB, nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    __table_args__ = (
        Index('idx_workspace_layouts_user_id', 'user_id'),
        UniqueConstraint("user_id", "layout_key", name="uq_workspace_layouts_user_key"),
    )
