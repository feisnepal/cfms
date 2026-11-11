#!/usr/bin/env python
"""Email the forum's digests (FORUM_SPEC.md, F5): one message per member with everything unsent since the last run.

Members who chose "daily" or "weekly" in their forum notification settings get their mail only from this script, so it must be scheduled:

    python scripts/forum_send_digests.py --frequency daily     # run once a day
    python scripts/forum_send_digests.py --frequency weekly    # run once a week
    python scripts/forum_send_digests.py --frequency immediate # retry "at once" mails that failed earlier

A notification whose post was deleted or held in the meantime is dropped, not sent. With no mail server configured the message is logged.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.database import SessionLocal  # noqa: E402
from app.services.forum import notifications  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--frequency", choices=("daily", "weekly", "immediate"), required=True)
    args = parser.parse_args()
    db = SessionLocal()
    try:
        sent = notifications.send_pending(db, args.frequency)
    finally:
        db.close()
    print(f"{sent} {args.frequency} message(s) sent")
    return 0


if __name__ == "__main__":
    sys.exit(main())
