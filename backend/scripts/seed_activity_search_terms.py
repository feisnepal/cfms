"""Fill `potential_activities.name_en` and `.search_terms` from `backend/data/activity_search_terms.json`.

These two columns only *widen* the search of the activity picker (a person can type English or romanised
Nepali); the Nepali name stays the primary label. See YEARLY_ACTIVITIES_WORKSPACE_PLAN.md §4.11.

    cd backend
    python -m scripts.seed_activity_search_terms              # seed (idempotent)
    python -m scripts.seed_activity_search_terms --rollback   # blank the two columns again
    python -m scripts.seed_activity_search_terms --deactivate-stray   # D30, see below

Safety rules
* A row is labelled only when its stored Nepali name equals the file's ``ne`` exactly, so a master list
  that was re-ordered or edited can never be mis-labelled; such a row is reported and skipped.
* Idempotent: a row that already holds the wanted values is not written again.
* Nothing is deleted. ``--rollback`` sets the two columns back to NULL for the rows in the file.

D30 — `--deactivate-stray` sets ``is_active = false`` on the unused English test row (id 136, "Plantation
Work" under "Program A"), after checking that no plan line uses it. With ``--rollback`` it is switched
back on.
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
from typing import Any, Dict, List

from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

DATA_FILE = (
    Path(__file__).resolve().parent.parent / "data" / "activity_search_terms.json"
)

STRAY_ID = 136
STRAY_ACTIVITY = "Plantation Work"


def load_rows(path: Path = DATA_FILE) -> List[Dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return data["activities"]


def seed(db: Session, rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Write name_en / search_terms. Returns a report; the caller commits."""
    report: Dict[str, Any] = {
        "updated": 0,
        "unchanged": 0,
        "missing": [],
        "name_differs": [],
    }
    for row in rows:
        current = db.execute(
            text(
                "SELECT activities, name_en, search_terms FROM potential_activities WHERE id = :id"
            ),
            {"id": row["id"]},
        ).first()
        if current is None:
            report["missing"].append(row["id"])
            continue
        if (current.activities or "") != row["ne"]:
            report["name_differs"].append(row["id"])
            continue
        if current.name_en == row["en"] and current.search_terms == row["terms"]:
            report["unchanged"] += 1
            continue
        db.execute(
            text(
                "UPDATE potential_activities SET name_en = :en, search_terms = :terms WHERE id = :id"
            ),
            {"id": row["id"], "en": row["en"], "terms": row["terms"]},
        )
        report["updated"] += 1
    return report


def rollback(db: Session, rows: List[Dict[str, Any]]) -> int:
    """Blank the two columns for the rows the file names (only where the name still matches)."""
    cleared = 0
    for row in rows:
        result = db.execute(
            text(
                "UPDATE potential_activities SET name_en = NULL, search_terms = NULL "
                "WHERE id = :id AND activities = :ne AND (name_en IS NOT NULL OR search_terms IS NOT NULL)"
            ),
            {"id": row["id"], "ne": row["ne"]},
        )
        cleared += result.rowcount or 0
    return cleared


def deactivate_stray(db: Session) -> str:
    """D30: switch off the stray English test row. Refuses when the row is not the stray one or a plan uses it."""
    row = db.execute(
        text("SELECT activities, is_active FROM potential_activities WHERE id = :id"),
        {"id": STRAY_ID},
    ).first()
    if row is None:
        return "not found - nothing to do"
    if (row.activities or "") != STRAY_ACTIVITY:
        return f"id {STRAY_ID} is '{row.activities}', not the stray row - left alone"
    used = db.execute(
        text(
            "SELECT count(*) FROM proposed_yearly_activities WHERE potential_activity_id = :id"
        ),
        {"id": STRAY_ID},
    ).scalar()
    if used:
        return f"used by {used} plan line(s) - left active"
    if not row.is_active:
        return "already inactive"
    db.execute(
        text("UPDATE potential_activities SET is_active = false WHERE id = :id"),
        {"id": STRAY_ID},
    )
    return "deactivated"


def reactivate_stray(db: Session) -> str:
    result = db.execute(
        text(
            "UPDATE potential_activities SET is_active = true "
            "WHERE id = :id AND activities = :name AND is_active = false"
        ),
        {"id": STRAY_ID, "name": STRAY_ACTIVITY},
    )
    return "reactivated" if result.rowcount else "nothing to reactivate"


def main() -> None:  # pragma: no cover - thin CLI over the functions above
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--rollback", action="store_true", help="undo instead of apply")
    parser.add_argument(
        "--deactivate-stray",
        action="store_true",
        help="D30: also deactivate the unused test row id 136 (with --rollback: switch it back on)",
    )
    args = parser.parse_args()

    from app.core.database import SessionLocal

    db = SessionLocal()
    try:
        rows = load_rows()
        if args.rollback:
            print(f"cleared name_en/search_terms on {rollback(db, rows)} row(s)")
            if args.deactivate_stray:
                print("stray row:", reactivate_stray(db))
        else:
            report = seed(db, rows)
            print(
                f"updated {report['updated']}, unchanged {report['unchanged']}, "
                f"not found {report['missing']}, name differs (skipped) {report['name_differs']}"
            )
            if args.deactivate_stray:
                print("stray row:", deactivate_stray(db))
        db.commit()
    finally:
        db.close()


if __name__ == "__main__":  # pragma: no cover
    main()
