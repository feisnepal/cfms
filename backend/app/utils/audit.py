"""Audit trail utilities for dimension changes."""
import logging
from datetime import datetime, timezone
from typing import Optional, Dict, Any
from uuid import UUID

logger = logging.getLogger(__name__)


def append_audit_entry(
    result_data: dict,
    user_id: UUID,
    user_name: str,
    action: str,
    from_value: Optional[str],
    to_value: Optional[str],
    trigger: str,
    calculation_id: UUID,
    metadata: Optional[Dict[str, Any]] = None
) -> dict:
    """
    Append an audit entry to result_data['audit_trail'].

    Uses the JSONB in-place mutation workaround (SQLAlchemy JSONB trap fix):
    always returns a NEW dict. Caller must assign it back.

    Example:
        new_data = append_audit_entry(calc.result_data, ...)
        calc.result_data = new_data
        flag_modified(calc, 'result_data')
    """
    result_data = dict(result_data or {})
    audit_trail = list(result_data.get('audit_trail', []))
    audit_trail.append({
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'user_id': str(user_id),
        'user_name': user_name,
        'action': action,
        'from': from_value,
        'to': to_value,
        'trigger': trigger,
        'calculation_id': str(calculation_id),
        'metadata': metadata or {},
    })
    # Keep last 100 entries to prevent unbounded growth
    if len(audit_trail) > 100:
        audit_trail = audit_trail[-100:]
    result_data['audit_trail'] = audit_trail
    return result_data
