"""Pydantic schemas for OP table catalog endpoints.

Request/response models for managing OP table definitions and their
data rows. Includes table metadata (title, column config, data source)
and row-level data updates for auto-populated tables.

See also:
    app.models.op_table.OPTableDefinition — database model
    app.api.op_table_catalog — table CRUD endpoints
"""

from pydantic import BaseModel, Field, UUID4
from typing import Optional, Dict, Any, List


class OPTableDefinitionResponse(BaseModel):
    """Response schema for OP table definition metadata."""
    table_id: str
    title_ne: str
    title_en: str
    auto_populatable: bool
    data_source: Optional[str] = None
    column_config: Optional[Dict[str, Any]] = None


class OPTableDataUpdate(BaseModel):
    """Request schema for updating OP table row data."""
    rows: List[Dict[str, Any]]
    auto_populated: Optional[bool] = False


class OPTableDataResponse(BaseModel):
    """Response schema for OP table data with rows."""
    table_id: str
    rows: List[Dict[str, Any]] = []
    auto_populated: bool = False


class OPTableCatalogResponse(BaseModel):
    """Response schema for OP table catalog listing."""
    tables: List[OPTableDefinitionResponse]
