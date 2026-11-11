"""
Script to import caste classification data from CSV file
Run this after migration: python scripts/import_caste_classification.py
"""
import sys
import os
import csv
from pathlib import Path

# Add parent directory to path to import app modules
sys.path.append(str(Path(__file__).parent.parent))

from app.core.database import SessionLocal
from app.models.caste_classification import CasteClassification


def import_caste_data():
    """Import caste classification data from CSV"""

    csv_file = Path(__file__).parent.parent.parent / "testData" / "households_information" / "caste_classification.csv"

    if not csv_file.exists():
        print(f"ERROR: CSV file not found at {csv_file}")
        return

    db = SessionLocal()

    try:
        # Clear existing data
        print("Clearing existing caste classification data...")
        db.query(CasteClassification).delete()
        db.commit()

        # Read and import CSV
        print(f"Reading CSV file: {csv_file}")
        with open(csv_file, 'r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            records = []

            for row in reader:
                record = CasteClassification(
                    classification_ne=row.get('classification_ne', '').strip(),
                    caste_ne=row.get('caste_ne', '').strip(),
                    surname_ne=row.get('surname_ne', '').strip(),
                    classification_en=row.get('classification_en', '').strip() or None,
                    caste_en=row.get('caste_en', '').strip() or None,
                    surname_en=row.get('surname_en', '').strip() or None
                )
                records.append(record)

            # Bulk insert
            print(f"Importing {len(records)} records...")
            db.bulk_save_objects(records)
            db.commit()

            print(f"Successfully imported {len(records)} caste classification records")

            # Show count
            print(f"\nTotal records in database: {db.query(CasteClassification).count()}")

    except Exception as e:
        print(f"ERROR: {e}")
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    print("=" * 60)
    print("Caste Classification Data Import")
    print("=" * 60)
    import_caste_data()
    print("=" * 60)
    print("Import complete!")
