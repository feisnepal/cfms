"""OP table definition model (op_table_definitions).

Stores metadata for each table (table_1 through table_32) used in the
Operational Plan document, including Nepali/English titles, column
configuration, and auto-population source. Each table can be manually
edited or auto-populated from collected data.

See also:
    app.api.op_table_catalog — endpoints for table CRUD
    app.services.operational_plan.op_docx_builder — renders tables in DOCX
"""

from sqlalchemy import Index, Column, String, Integer, ForeignKey, Text, Boolean
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from datetime import datetime, timezone
import uuid
from ..core.database import Base


class OPTableDefinition(Base):
    """Model for operational plan table definitions (table_1 through table_32).

    Stores metadata including Nepali/English titles, auto-population
    configuration, column definitions, and data source mappings.
    """
    __tablename__ = "op_table_definitions"
    id = Column(Integer, primary_key=True, autoincrement=True)
    table_id = Column(String(20), unique=True, nullable=False)  # "table_1" through "table_32"
    title_ne = Column(String(255), nullable=False)
    title_en = Column(String(255), nullable=False)
    auto_populatable = Column(Boolean, nullable=False, default=False)
    data_source = Column(String(100), nullable=True)
    column_config = Column(JSONB, nullable=True)

    def __repr__(self):
        return f"<OPTableDefinition(id={self.table_id}, title={self.title_en})>"


class OPTableData(Base):
    """Model for operational plan table instance data per calculation.

    Stores actual row data for a specific table within a calculation,
    tracking whether it was auto-populated or manually edited.
    """
    __tablename__ = "op_table_data"
    __table_args__ = (
        Index('idx_op_table_data_calc_table', 'calculation_id', 'table_id'),
    )
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    calculation_id = Column(UUID(as_uuid=True), ForeignKey("calculations.id", ondelete="CASCADE"), nullable=False)
    table_id = Column(String(20), nullable=False)
    rows = Column(JSONB, nullable=False, default=list)
    auto_populated = Column(Boolean, nullable=False, default=False)
    created_at = Column(String(30), default=lambda: datetime.now(timezone.utc).replace(microsecond=0).isoformat())

    def __repr__(self):
        return f"<OPTableData(calc={self.calculation_id}, table={self.table_id}, rows={len(self.rows or [])})>"
