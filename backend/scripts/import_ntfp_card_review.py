"""Load a filled NTFP card review sheet: every confirmed or corrected value is stored as an expert-confirmed value with the reviewer's name.

    python scripts/import_ntfp_card_review.py REVIEWED.xlsx "Reviewer Name" [--dry-run]

All or nothing: any invalid row and nothing is written.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.core.database import SessionLocal  # noqa: E402
import app.models  # noqa: E402,F401
from app.services import ntfp_card_review as review  # noqa: E402
from app.services import ntfp_card_service as cards  # noqa: E402


def main(path: str, reviewer: str, dry: bool) -> int:
    with open(path, "rb") as f:
        rows = review.read_sheet(f.read())
    db = SessionLocal()
    try:
        out = cards.apply_review(db, rows, reviewer)
        if dry:
            db.rollback()
        else:
            db.commit()
    except (cards.ReviewError, ValueError) as exc:
        db.rollback()
        print(f"REFUSED, nothing written: {exc}")
        return 1
    finally:
        db.close()
    print(("dry run: " if dry else "") + f"{out['cards_confirmed']} cards confirmed, {out['values_written']} values written, {len(out['skipped'])} rows skipped")
    for s in out["skipped"][:20]:
        print("  skipped:", s)
    return 0


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if len(args) != 2:
        sys.exit(__doc__)
    sys.exit(main(args[0], args[1], "--dry-run" in sys.argv))
