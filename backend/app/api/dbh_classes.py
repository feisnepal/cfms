"""
DBH Classification Systems API endpoints
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import text
from typing import Any, Optional

from ..core.database import get_db
from ..core.dbh_classifier import (
    DbhClassDriftError,
    DbhClassRegistry,
    DbhClassDef,
)
from ..core.config import settings
from ..models.user import User
from ..utils.auth import get_current_active_user, require_org_admin

router = APIRouter()


def _record_change(db: Session, *, system_name: str, change_type: str,
                   old_defs, new_defs, changed_by: str) -> None:
    """H2.3 / S1-03: write the audit row these endpoints never wrote.

    `dbh_classification_changes` has existed since migration 034 and the history
    endpoint reads it, but nothing ever inserted into it — the table is empty by
    construction, so the trail showed nothing no matter what was changed. The
    caller is recorded because these definitions decide every tree's DBH class,
    and through it the stand type that feeds harvest calculations.
    """
    import json
    db.execute(
        text("""INSERT INTO dbh_classification_changes
                    (system_name, change_type, old_defs, new_defs, changed_by)
                VALUES (:sn, :ct, CAST(:old AS jsonb), CAST(:new AS jsonb), :by)"""),
        {
            "sn": system_name,
            "ct": change_type,
            "old": json.dumps(old_defs, ensure_ascii=False) if old_defs is not None else None,
            "new": json.dumps(new_defs, ensure_ascii=False) if new_defs is not None else None,
            "by": changed_by,
        },
    )


@router.get("/dbh-classes/systems")
def list_systems(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """Every classification system, with its full class definitions.

    Reloads from `dbh_class_systems` first, so what is served is the table rather
    than the constants in `dbh_classifier.py`. That matters more than it looks:
    this endpoint previously took no session and read the hardcoded fallback, so
    the "database-backed" API was in fact serving code -- and the frontend, unable
    to render anything from a name-and-count list, ended up carrying its own
    duplicated class arrays. Serving the table is the precondition for P3 removing
    them.

    Drift surfaces as a 500 with the detail, for the same reason as the
    single-system route: a class boundary that differs from the code would change
    which class a stem falls into, and the response would look entirely normal.
    """
    try:
        DbhClassRegistry.reload_from_db(db)
    except DbhClassDriftError as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    return DbhClassRegistry.list_systems()


@router.get("/dbh-classes/systems/{system_name}")
def get_system(
    system_name: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """Get a classification system definition with full class details."""
    try:
        DbhClassRegistry.reload_from_db(db)
    except DbhClassDriftError as exc:
        # Surfaced as a 500 with the drift detail, not swallowed. The registry
        # used to catch every failure here and fall back to the code defaults,
        # which meant a drifted `dbh_class_systems` produced confident,
        # correct-looking class boundaries and nobody was told. Failing is the
        # point of D2: the alternative is a report whose per-hectare figures are
        # wrong with no visible cause.
        raise HTTPException(status_code=500, detail=str(exc))
    try:
        classes = DbhClassRegistry.get_system(system_name)
    except ValueError:
        raise HTTPException(status_code=404, detail=f"Unknown system: {system_name}")

    return {
        "system_name": system_name,
        "classes": [
            {
                "key": c.key,
                "lower": c.lower,
                "upper": c.upper,
                "label_en": c.label_en,
                "label_np": c.label_np,
                "stand_type": c.stand_type,
            }
            for c in classes
        ],
    }


@router.post("/dbh-classes/classify")
def classify_dbh(
    dbh: float = Query(..., description="Diameter at breast height in cm"),
    system: str = Query("guideline_2061", description="Classification system name"),
    current_user: User = Depends(get_current_active_user),
):
    """Classify a DBH value using the named system."""
    cls = DbhClassRegistry.classify(dbh, system)
    if cls is None:
        raise HTTPException(status_code=422, detail=f"DBH value {dbh} could not be classified in system '{system}'")
    return {
        "key": cls.key,
        "lower": cls.lower,
        "upper": cls.upper,
        "label_en": cls.label_en,
        "label_np": cls.label_np,
        "stand_type": cls.stand_type,
    }


@router.put("/dbh-classes/systems/{system_name}")
def update_system(
    system_name: str,
    body: dict,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_org_admin),
):
    """Update a classification system definition.

    Systems with `is_system_default=true` block DELETE and system_name changes.
    """
    row = db.execute(
        text("SELECT is_system_default, class_defs FROM dbh_class_systems WHERE system_name = :sn"),
        {"sn": system_name},
    ).fetchone()

    if row is None:
        raise HTTPException(status_code=404, detail=f"System '{system_name}' not found")

    if row[0] and "system_name" in body and body["system_name"] != system_name:
        raise HTTPException(status_code=403, detail="Cannot rename a system-default classification")

    allowed_fields = {"version", "description", "effective_date", "class_defs", "is_active"}
    updates = {k: v for k, v in body.items() if k in allowed_fields}
    if not updates:
        raise HTTPException(status_code=422, detail="No updatable fields provided")

    set_clauses = ", ".join(f"{k} = :{k}" for k in updates)
    params = {"sn": system_name, **updates}
    if "class_defs" in updates:
        params["class_defs"] = __import__("json").dumps(updates["class_defs"], ensure_ascii=False)

    db.execute(
        text(f"UPDATE dbh_class_systems SET {set_clauses}, updated_at = NOW() WHERE system_name = :sn"),
        params,
    )
    _record_change(
        db,
        system_name=system_name,
        change_type="update",
        old_defs=row[1],
        new_defs=updates.get("class_defs"),
        changed_by=str(current_user.id),
    )
    db.commit()
    DbhClassRegistry.invalidate_cache()

    return {"status": "updated", "system_name": system_name, "updated_fields": list(updates.keys())}


@router.delete("/dbh-classes/systems/{system_name}")
def delete_system(
    system_name: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_org_admin),
):
    """Delete a classification system.

    System-default classifications cannot be deleted.
    """
    row = db.execute(
        text("SELECT is_system_default, class_defs FROM dbh_class_systems WHERE system_name = :sn"),
        {"sn": system_name},
    ).fetchone()

    if row is None:
        raise HTTPException(status_code=404, detail=f"System '{system_name}' not found")
    if row[0]:
        raise HTTPException(status_code=403, detail="Cannot delete a system-default classification")

    # The history is deliberately NOT deleted with the system. Wiping the trail
    # as part of the act it records is the one moment it matters most; the
    # deletion itself is recorded as the final entry.
    db.execute(text("DELETE FROM dbh_class_systems WHERE system_name = :sn"), {"sn": system_name})
    _record_change(
        db,
        system_name=system_name,
        change_type="delete",
        old_defs=row[1],
        new_defs=None,
        changed_by=str(current_user.id),
    )
    db.commit()
    DbhClassRegistry.invalidate_cache()

    return {"status": "deleted", "system_name": system_name}


@router.get("/dbh-classes/systems/{system_name}/history")
def get_system_history(
    system_name: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_org_admin),
):
    """Get change history for a classification system."""
    rows = db.execute(
        text("""SELECT id, change_type, old_defs, new_defs, changed_by, changed_at
                 FROM dbh_classification_changes
                 WHERE system_name = :sn
                 ORDER BY changed_at DESC"""),
        {"sn": system_name},
    ).fetchall()

    return [
        {
            "id": r[0],
            "change_type": r[1],
            "old_defs": r[2],
            "new_defs": r[3],
            "changed_by": r[4],
            "changed_at": r[5].isoformat() if r[5] else None,
        }
        for r in rows
    ]
