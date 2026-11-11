"""
Workspace layout endpoints — save/restore per-user panel layout.

The map design UI persists panel sizes and collapsed state server-side so
the layout follows the user across sessions and devices.
"""
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..core.database import get_db
from ..models.user import User
from ..models.workspace_layout import WorkspaceLayout
from ..utils.auth import get_current_active_user

router = APIRouter(prefix="/workspace/layout", tags=["Workspace Layout"])

DEFAULT_LAYOUT_KEY = "workspace"


class LayoutPayload(BaseModel):
    layout_key: str = DEFAULT_LAYOUT_KEY
    layout_json: dict[str, Any]


@router.get("")
def get_workspace_layout(
    layout_key: str = DEFAULT_LAYOUT_KEY,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
) -> dict:
    """Return the user's saved layout (or null when none exists yet)."""
    row = (
        db.query(WorkspaceLayout)
        .filter(
            WorkspaceLayout.user_id == current_user.id,
            WorkspaceLayout.layout_key == layout_key,
        )
        .first()
    )
    return {"layout_key": layout_key, "layout_json": row.layout_json if row else None}


@router.put("")
def save_workspace_layout(
    payload: LayoutPayload,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
) -> dict:
    """Upsert the user's layout for the given key."""
    row = (
        db.query(WorkspaceLayout)
        .filter(
            WorkspaceLayout.user_id == current_user.id,
            WorkspaceLayout.layout_key == payload.layout_key,
        )
        .first()
    )
    if row is None:
        row = WorkspaceLayout(
            user_id=current_user.id,
            layout_key=payload.layout_key,
            layout_json=payload.layout_json,
        )
        db.add(row)
    else:
        # JSONB in-place mutation is a no-op — assign a fresh dict (see CLAUDE.md).
        row.layout_json = dict(payload.layout_json)
    db.commit()
    return {"layout_key": payload.layout_key, "layout_json": row.layout_json}
