"""Write the expert review sheet of the provisional NTFP method cards (NTFP_card_review.xlsx).

    python scripts/export_ntfp_card_review.py [output.xlsx]

Rows with a guessed growth class come first. Return the filled sheet and load it with ``scripts/import_ntfp_card_review.py``.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.core.database import SessionLocal  # noqa: E402
import app.models  # noqa: E402,F401
from app.models.ntfp_method import NtfpMethodProfile, NtfpMethodValue  # noqa: E402
from app.services import ntfp_card_review as review  # noqa: E402
from app.services import ntfp_card_service as cards  # noqa: E402

DEFAULT_OUT = r"D:\forest_management\NTFP_card_review.xlsx"


def main(out: str) -> None:
    db = SessionLocal()
    try:
        profiles = db.query(NtfpMethodProfile).filter(NtfpMethodProfile.has_method_card.is_(True)).all()
        how = {}
        for v in db.query(NtfpMethodValue).filter(NtfpMethodValue.field == "growth_class", NtfpMethodValue.chosen.is_(True)).all():
            how[v.species_key] = {"growth_class": v.note or ""}
        rows = review.card_rows(profiles, how)
        data = review.build_sheet(rows, cards.sources(db))
    finally:
        db.close()
    with open(out, "wb") as f:
        f.write(data)
    print(f"wrote {out}: {len(rows)} cards to review ({sum('guessed' in r['growth_how'] for r in rows)} with a guessed growth class)")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else DEFAULT_OUT)
