"""Load the assistant's help cards (app/services/chatbot/help_corpus/cards.json) into chat_help_chunks.

  python scripts/chatbot_load_help.py            # insert or update every card, switch off cards no longer in the file

Safe to run again: cards are matched by id. Accepted forum answers are indexed too. Guideline passages come only from the owner-approved help_corpus/guideline_qa.json (C1.4a).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from app.core.database import SessionLocal  # noqa: E402
from app.services.chatbot import help_search  # noqa: E402

if __name__ == "__main__":
    db = SessionLocal()
    try:
        print(f"loaded {help_search.load_cards(db)} help cards")
        print(f"loaded {help_search.load_guideline(db)} guideline passages")
        print(f"indexed {help_search.sync_forum(db)} accepted forum answers")
    finally:
        db.close()
