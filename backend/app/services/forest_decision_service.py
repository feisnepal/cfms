"""Read and write the plan decisions of one forest (registry in ``decision_registry``)."""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.models.calculation import Calculation
from app.models.forest_block import ForestBlock
from app.models.forest_decision import ForestDecision
from app.models.user import User, UserRole
from app.services import decision_registry as reg
from app.services.forest_units.write import set_management_orientation
from app.utils.authz import decisions_closed

logger = logging.getLogger(__name__)


def _decider(calc: Calculation, user: Optional[User]) -> Optional[Dict[str, Any]]:
    """Who answered, and in what capacity (owner / DFO / super admin), for the Decisions tab."""
    if user is None:
        return None
    if user.id == calc.user_id:
        kind = "owner"
    elif user.role == UserRole.SUPER_ADMIN:
        kind = "super_admin"
    elif user.role == UserRole.ORG_ADMIN:
        kind = "dfo"
    else:
        kind = "user"
    return {"id": str(user.id), "name": user.full_name, "kind": kind}


def _item(calc, definition, row, users, state, **extra) -> Dict[str, Any]:
    item = {
        "key": definition.key,
        "scope": extra.pop("scope", None),
        "who": definition.who,
        "step": definition.step,
        "choices": list(definition.choices),
        "state": state,
        "choice": row.choice if row is not None else None,
        "note": row.note if row is not None else None,
        "decided_at": row.decided_at.isoformat() if row is not None and row.decided_at else None,
        "decided_by": _decider(calc, users.get(row.decided_by)) if row is not None else None,
    }
    item.update(extra)
    return item


def list_decisions(db: Session, calc: Calculation) -> Dict[str, Any]:
    rows = db.query(ForestDecision).filter(ForestDecision.calculation_id == calc.id).all()
    by_key = {(r.key, r.scope): r for r in rows}
    user_ids = {r.decided_by for r in rows if r.decided_by}
    users = {u.id: u for u in db.query(User).filter(User.id.in_(user_ids)).all()} if user_ids else {}

    items: List[Dict[str, Any]] = []
    for key in (reg.LANDSLIDE_METHOD, reg.HOUSEHOLD_PLACEMENT):
        row = by_key.get((key, None))
        items.append(_item(calc, reg.REGISTRY[key], row, users, "answered" if row else "open"))

    definition = reg.REGISTRY[reg.ORIENTATION]
    blocks = (
        db.query(ForestBlock)
        .filter(ForestBlock.calculation_id == calc.id, ForestBlock.suggested_orientation.isnot(None))
        .order_by(ForestBlock.name)
        .all()
    )
    for block in blocks:
        row = by_key.get((reg.ORIENTATION, str(block.id)))
        current, suggested = block.management_orientation, block.suggested_orientation
        if current == suggested and row is None:
            continue  # nothing to decide
        # Open/answered comes from the columns: a later edit in the attribute table must not leave a stale answer.
        answered = current == suggested or (row is not None and row.choice == reg.CUSTOM and current is not None)
        items.append(
            _item(calc, definition, row, users, "answered" if answered else "open", scope=str(block.id),
                  block_name=block.name, current=current, suggested=suggested)
        )

    closed = decisions_closed(calc)
    return {
        "locked": closed,
        "locked_reason": calc.map_lifecycle_status if closed else None,
        "open_count": sum(1 for i in items if i["state"] == "open"),
        "items": items,
    }


def save_decision(
    db: Session,
    calc: Calculation,
    user: User,
    key: str,
    choice: str,
    scope: Optional[str],
    value: Optional[str],
    note: Optional[str],
) -> None:
    """Validate, apply the side effect, upsert the answer. The caller checks access and the lock; this commits."""
    definition = reg.validate(key, choice, scope, value)
    stored_note = note
    if key == reg.ORIENTATION:
        try:
            block_id = uuid.UUID(str(scope))
        except ValueError as exc:
            raise reg.DecisionError("scope must be a block id") from exc
        block = (
            db.query(ForestBlock)
            .filter(ForestBlock.id == block_id, ForestBlock.calculation_id == calc.id)
            .first()
        )
        if block is None:
            raise reg.DecisionError("That block does not belong to this forest")
        if choice == reg.ACCEPT_SUGGESTED:
            if not block.suggested_orientation:
                raise reg.DecisionError("This block has no suggested orientation to accept")
            set_management_orientation(calc, block, block.suggested_orientation)
        else:
            set_management_orientation(calc, block, value)
            stored_note = value
    row_scope = scope if definition.per_block else None
    row = (
        db.query(ForestDecision)
        .filter(ForestDecision.calculation_id == calc.id, ForestDecision.key == key, ForestDecision.scope == row_scope)
        .first()
    )
    if row is None:
        row = ForestDecision(calculation_id=calc.id, key=key, scope=row_scope)
        db.add(row)
    row.choice = choice
    row.note = stored_note
    row.decided_by = user.id
    row.decided_at = datetime.now(timezone.utc)
    db.commit()
