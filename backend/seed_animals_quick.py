#!/usr/bin/env python
"""Quick script to seed animal species"""
import os
os.environ['PYTHONIOENCODING'] = 'utf-8'

import logging
logging.disable(logging.CRITICAL)

import csv
from pathlib import Path
from app.core.database import SessionLocal
from app.models.biodiversity import BiodiversitySpecies

def main():
    db = SessionLocal()

    try:
        existing = db.query(BiodiversitySpecies).filter_by(category='animal').count()

        if existing > 0:
            print(f'Animals already seeded: {existing}')
        else:
            csv_path = Path('../testData/nepal_animal_species.csv')

            with open(csv_path, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                count = 0

                for row in reader:
                    is_protected = (
                        row['iucn_status'] in ['CR', 'EN', 'VU'] or
                        (row['cites_appendix'] and row['cites_appendix'] != 'Not listed')
                    )

                    species = BiodiversitySpecies(
                        category='animal',
                        sub_category=row['taxonomic_group'],
                        nepali_name=row['nepali_name'],
                        english_name=row['english_name'],
                        scientific_name=row['scientific_name'],
                        primary_use='Wildlife',
                        iucn_status=row['iucn_status'] if row['iucn_status'] else None,
                        cites_appendix=row['cites_appendix'] if row['cites_appendix'] else None,
                        notes=row['notes'] if row['notes'] else None,
                        is_invasive=False,
                        is_protected=is_protected
                    )

                    db.add(species)
                    count += 1

            db.commit()
            print(f'SUCCESS: Added {count} animal species!')

        veg = db.query(BiodiversitySpecies).filter_by(category='vegetation').count()
        animal = db.query(BiodiversitySpecies).filter_by(category='animal').count()
        total = db.query(BiodiversitySpecies).count()

        print('')
        print('Final Database Counts:')
        print(f'  Vegetation: {veg}')
        print(f'  Animals: {animal}')
        print(f'  Total Species: {total}')

    except Exception as e:
        print(f'ERROR: {e}')
        db.rollback()
        raise
    finally:
        db.close()

if __name__ == '__main__':
    main()
