"""Digitize audit service — forestry compliance trail (Gap 6.1 / Task 1.4.4).

Records "who mapped what boundary when" for on-screen digitizing: one row per
flush (add_feature), plus create_draft, finalize and discard. The geometry_hash
is a SHA-256 of the concatenated feature geometries so identical mappings are
stable (for dedup / forensic comparison).
"""
from sqlalchemy.orm import Session
from typing import Optional, List
import hashlib
import json
import logging

from ..models.digitize_audit_log import DigitizeAuditLog

logger = logging.getLogger(__name__)


def geometry_hash_of(features: List[dict]) -> str:
    """SHA-256 of the canonical JSON of each feature geometry (stable, ordered).

    Uses the geometry as the sole input — identical geometry maps to the same
    hash regardless of which properties/featureIds the client attached.
    """
    payload = []
    for f in features or []:
        geom = f.get("geometry") if isinstance(f, dict) else None
        if geom:
            payload.append(json.dumps(geom, sort_keys=True, separators=(",", ":")))
    if not payload:
        return ""
    return hashlib.sha256("|".join(payload).encode("utf-8")).hexdigest()


def record_digitize_audit(
    db: Session,
    *,
    calculation_id,
    layer_id: int,
    user_id,
    action: str,
    feature_count_delta: int = 0,
    geometry_hash: str = "",
    details: Optional[str] = None,
) -> DigitizeAuditLog:
    """Insert one audit row and flush it (no commit — caller owns the txn)."""
    row = DigitizeAuditLog(
        calculation_id=calculation_id,
        layer_id=layer_id,
        user_id=user_id,
        action=action,
        feature_count_delta=feature_count_delta,
        geometry_hash=geometry_hash or None,
        details=details,
    )
    db.add(row)
    db.flush()
    return row


def list_digitize_audit(
    db: Session,
    *,
    calculation_id,
    layer_id: int,
    limit: int = 200,
) -> List[dict]:
    """Return the audit trail for a digitize layer (newest first)."""
    rows = (
        db.query(DigitizeAuditLog)
        .filter(
            DigitizeAuditLog.calculation_id == calculation_id,
            DigitizeAuditLog.layer_id == layer_id,
        )
        .order_by(DigitizeAuditLog.created_at.desc(), DigitizeAuditLog.id.desc())
        .limit(max(1, min(limit, 1000)))
        .all()
    )
    return [
        {
            "id": r.id,
            "action": r.action,
            "user_id": str(r.user_id) if r.user_id else None,
            "feature_count_delta": r.feature_count_delta,
            "geometry_hash": r.geometry_hash,
            "details": r.details,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ]
