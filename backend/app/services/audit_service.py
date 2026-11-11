"""
audit_service.py — Geometry mutation audit logging.

Provides:
  - log_geometry_audit(): Core logging function
  - audit_mutation(): Decorator for automatic audit logging on endpoints
  - get_audit_trail(): Query helper for fetching audit entries

# business: all geometry changes must be traceable per QA.12
# constraint: JSONB columns store serialized GeoJSON for exact before/after comparison
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from functools import wraps
from typing import Any, Callable, Dict, List, Optional, TypeVar

from fastapi import HTTPException, Request
from sqlalchemy.orm import Session
from sqlalchemy import text

logger = logging.getLogger(__name__)

ALLOWED_OPERATIONS = frozenset({
    "CREATE", "UPDATE", "DELETE", "SPLIT", "MERGE", "VERTEX_EDIT",
    "RENAME", "DUPLICATE", "RESHAPE", "BUFFER", "CLIP",
})

# The vocabulary the WRITE PATH actually uses, not a parallel one.
#
# This set and `editing.py::_write_geometry` disagreed on three of five names.
# `_write_geometry` branches on "boundary", "blocks", "compartments",
# "sub_compartments" and "sub_areas"; this set listed "forest_boundary" and
# "activity_features", which it never sees, and omitted "boundary",
# "compartments" and "sub_compartments", which it handles.
#
# That mattered more than a naming quibble: `log_geometry_audit` RAISES on an
# unknown layer type, so wiring the audit into the live write path without
# fixing this would have taken down the first boundary or compartment edit a
# user attempted. An audit trail must never be able to destroy the write it is
# recording.
#
# "forest_boundary" and "activity_features" are kept: the three existing calls
# in geometry.py pass "blocks"/"sub_areas", other callers may use the older
# names, and rejecting a value that used to be accepted would be the same
# defect pointing the other way.
ALLOWED_LAYER_TYPES = frozenset({
    # used by editing.py::_write_geometry
    "boundary", "blocks", "compartments", "sub_compartments", "sub_areas",
    # the single user-group extent row, also written through _write_geometry
    "user_group",
    # older / other callers
    "forest_boundary", "activity_features",
})


def log_geometry_audit(
    db: Session,
    calculation_id: str,
    layer_type: str,
    operation: str,
    feature_id: Optional[str],
    previous_geometry: Optional[dict],
    new_geometry: Optional[dict],
    user_id: Optional[str] = None,
    metadata: Optional[dict] = None,
) -> int:
    if layer_type not in ALLOWED_LAYER_TYPES:
        raise ValueError(f"Invalid layer_type: {layer_type}. Allowed: {ALLOWED_LAYER_TYPES}")

    if operation not in ALLOWED_OPERATIONS:
        raise ValueError(f"Invalid operation: {operation}. Allowed: {ALLOWED_OPERATIONS}")

    prev_json = json.dumps(previous_geometry) if previous_geometry else None
    new_json = json.dumps(new_geometry) if new_geometry else None
    meta_json = json.dumps(metadata or {})

    # CAST(...) rather than `::jsonb`.
    #
    # This function had NEVER successfully inserted a row. `:prev_geom::jsonb`
    # makes SQLAlchemy's bind-parameter parser stop at the first colon pair, so
    # the statement reached PostgreSQL with `:prev_geom` unsubstituted and it
    # answered `syntax error at or near ":"` -- every call, since the function
    # was written. `geometry_audits` holding 0 rows after five months was read
    # as "never wired"; it was wired, to a dead endpoint, and broken as well.
    #
    # `metadata` is also gone from the column list: the table has no such
    # column. Even with the casts fixed, every insert would have failed on it.
    # What the caller passes as `metadata` now goes to `new_properties`, which
    # exists and is the closest thing the schema has.
    sql = text("""
        INSERT INTO geometry_audits
            (calculation_id, layer_type, operation, feature_id,
             previous_geometry, new_geometry, user_id, new_properties,
             client_type, ip_address, correlation_id, user_agent, created_at)
        VALUES
            (CAST(:calc_id AS uuid), :layer_type, :operation, :feature_id,
             CAST(:prev_geom AS json), CAST(:new_geom AS json),
             CAST(:user_id AS uuid), CAST(:meta AS json),
             :client_type, :ip_address, :correlation_id, :user_agent, NOW())
        RETURNING id
    """)

    # Provenance as first-class columns (H8.7 / migration 058), not only inside
    # the JSON. "Every write from a mobile client since March" is the question
    # this table exists to answer, and it should be an indexed predicate rather
    # than a scan. It is still mirrored into the JSON so an older reader, and
    # any caller passing its own metadata, keeps working.
    meta = metadata or {}
    result = db.execute(sql, {
        "calc_id": str(calculation_id),
        "layer_type": layer_type,
        "operation": operation,
        "feature_id": feature_id,
        "prev_geom": prev_json or "null",
        "new_geom": new_json or "null",
        "user_id": str(user_id) if user_id else None,
        "meta": meta_json,
        "client_type": meta.get("client_type"),
        "ip_address": meta.get("ip_address"),
        "correlation_id": meta.get("correlation_id"),
        "user_agent": meta.get("user_agent"),
    })

    audit_id = result.scalar_one()
    logger.debug(
        "Audit logged: calc=%s op=%s layer=%s feature=%s audit_id=%s",
        calculation_id, operation, layer_type, feature_id, audit_id,
    )

    return audit_id


F = TypeVar('F', bound=Callable[..., Any])


def audit_mutation(layer_type: str, operation: str):
    def decorator(func: F) -> F:
        @wraps(func)
        async def wrapper(*args, **kwargs):
            db: Session = kwargs.get("db")
            current_user = kwargs.get("current_user")
            calculation_id = kwargs.get("calculation_id") or kwargs.get("id")

            result = await func(*args, **kwargs) if hasattr(func, '__call__') else func(*args, **kwargs)

            if isinstance(result, dict) and result.get("success"):
                log_geometry_audit(
                    db=db,
                    calculation_id=calculation_id or result.get("calculation_id"),
                    layer_type=layer_type,
                    operation=operation,
                    feature_id=result.get("feature_id"),
                    previous_geometry=result.get("previous_geometry"),
                    new_geometry=result.get("new_geometry"),
                    user_id=str(current_user.id) if current_user else None,
                    metadata=result.get("audit_metadata"),
                )

            return result
        return wrapper
    return decorator


def get_audit_trail(
    db: Session,
    calculation_id: str,
    layer_type: Optional[str] = None,
    operation: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
) -> Dict:
    conditions = ["calculation_id = :calc_id"]
    params: Dict = {"calc_id": str(calculation_id)}

    if layer_type:
        conditions.append("layer_type = :layer_type")
        params["layer_type"] = layer_type

    if operation:
        conditions.append("operation = :operation")
        params["operation"] = operation

    where_clause = " AND ".join(conditions)

    count_sql = text(f"SELECT COUNT(*) FROM geometry_audits WHERE {where_clause}")
    total = db.execute(count_sql, params).scalar()

    query_sql = text(f"""
        SELECT id, calculation_id, layer_type, operation, feature_id,
               previous_geometry, new_geometry, user_id, metadata, created_at
        FROM geometry_audits
        WHERE {where_clause}
        ORDER BY created_at DESC
        LIMIT :limit OFFSET :offset
    """)
    params["limit"] = limit
    params["offset"] = offset

    rows = db.execute(query_sql, params).mappings().all()

    entries = []
    for row in rows:
        entries.append({
            "id": row["id"],
            "calculation_id": str(row["calculation_id"]),
            "layer_type": row["layer_type"],
            "operation": row["operation"],
            "feature_id": row["feature_id"],
            "previous_geometry": row["previous_geometry"],
            "new_geometry": row["new_geometry"],
            "user_id": str(row["user_id"]) if row["user_id"] else None,
            "metadata": row["metadata"],
            "created_at": row["created_at"].isoformat() if row["created_at"] else None,
        })

    return {"entries": entries, "total": total, "limit": limit, "offset": offset}


def get_recent_audits_for_user(
    db: Session,
    user_id: str,
    limit: int = 20,
) -> List[Dict]:
    sql = text("""
        SELECT ga.id, ga.calculation_id, c.forest_name, ga.layer_type,
               ga.operation, ga.feature_id, ga.created_at
        FROM geometry_audits ga
        JOIN calculations c ON c.id = ga.calculation_id
        WHERE ga.user_id = :user_id
        ORDER BY ga.created_at DESC
        LIMIT :limit
    """)
    rows = db.execute(sql, {"user_id": str(user_id), "limit": limit}).mappings().all()
    return [dict(row) for row in rows]
