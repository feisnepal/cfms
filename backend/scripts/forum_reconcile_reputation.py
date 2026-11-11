#!/usr/bin/env python
"""Check that every forum member's cached reputation is the sum of their reputation events (FORUM_SPEC.md, F2).

The ledger writes both together, so a difference means something wrote the balance directly (a hand edit, a restore from a partial backup).
Report only by default; ``--fix`` sets each balance to what the events add up to.

    python scripts/forum_reconcile_reputation.py          # report, exit 1 when any member disagrees
    python scripts/forum_reconcile_reputation.py --fix    # repair and commit
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.database import SessionLocal  # noqa: E402
from app.services.forum import reputation  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--fix", action="store_true", help="set each balance to the sum of its events")
    args = parser.parse_args()
    db = SessionLocal()
    try:
        bad = reputation.reconcile(db, fix=args.fix)
        for m in bad:
            print(f"  {m['user_id']}: cached {m['cached']}, ledger {m['ledger']}")
        if args.fix:
            db.commit()
            print(f"repaired {len(bad)} member(s)")
            return 0
        print("every balance matches its ledger" if not bad else f"{len(bad)} member(s) disagree with the ledger")
        return 1 if bad else 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
