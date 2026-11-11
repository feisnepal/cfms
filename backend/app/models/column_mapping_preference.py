"""
SQLAlchemy model for column mapping user preferences
"""

from sqlalchemy import Column, String, Integer, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
from app.core.database import Base


class ColumnMappingPreference(Base):
    """
    Stores user's preferred column mappings for tree inventory CSV uploads.

    When a user uploads a CSV and confirms a column mapping, we can optionally
    save their preferences here. Next time they upload a CSV with similar column
    names, we can automatically suggest their previous mappings.
    """
    __tablename__ = "column_mapping_preferences"
    id = Column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    user_id = Column(UUID(as_uuid=True), ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    original_column = Column(String(255), nullable=False)
    mapped_to = Column(String(100), nullable=False)
    times_used = Column(Integer, nullable=False, default=1, server_default='1')
    last_used_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    def __repr__(self):
        return f"<ColumnMappingPreference(user={self.user_id}, '{self.original_column}' -> '{self.mapped_to}')>"
