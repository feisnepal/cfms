"""
Seed biodiversity_species table from CSV files
Run this script once to populate the species master data
"""
import csv
import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent))

from app.core.database import SessionLocal
from app.models.biodiversity import BiodiversitySpecies


def seed_vegetation_species(db, csv_path):
    """Seed vegetation species from CSV"""
    print(f"Loading vegetation species from {csv_path}...")

    category_mapping = {
        'Tree': 'vegetation',
        'Shrub/Bamboo': 'vegetation',
        'Fern': 'vegetation',
        'Orchid': 'vegetation',
        'Grass': 'vegetation',
        'Sedge': 'vegetation',
        'Medicinal Herb': 'vegetation',
        'Climber': 'vegetation',
        'Aquatic': 'vegetation',
        'Invasive Plant': 'vegetation'
    }

    sub_category_mapping = {
        'Tree': 'Tree',
        'Shrub/Bamboo': 'Shrub/Bamboo',
        'Fern': 'Fern',
        'Orchid': 'Orchid',
        'Grass': 'Grass',
        'Sedge': 'Sedge',
        'Medicinal Herb': 'Medicinal Herb',
        'Climber': 'Climber',
        'Aquatic': 'Aquatic',
        'Invasive Plant': 'Invasive Plant'
    }

    count = 0
    with open(csv_path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            plant_cat = row['plant_category']

            # Determine if protected based on IUCN status
            is_protected = row['iucn_status'] in ['CR', 'EN', 'VU'] or \
                          (row['cites_appendix'] and row['cites_appendix'] != 'Not listed')

            # Determine if invasive
            is_invasive = plant_cat == 'Invasive Plant' or 'invasive' in row.get('notes', '').lower()

            species = BiodiversitySpecies(
                category=category_mapping.get(plant_cat, 'vegetation'),
                sub_category=sub_category_mapping.get(plant_cat),
                nepali_name=row['nepali_name'],
                english_name=row['english_name'],
                scientific_name=row['scientific_name'],
                primary_use=row['primary_use'] if row['primary_use'] else None,
                secondary_uses=row['secondary_uses'] if row['secondary_uses'] else None,
                iucn_status=row['iucn_status'] if row['iucn_status'] and row['iucn_status'] != 'LC' else 'LC',
                cites_appendix=row['cites_appendix'] if row['cites_appendix'] else None,
                distribution=row['distribution'] if row['distribution'] else None,
                notes=row['notes'] if row['notes'] else None,
                is_invasive=is_invasive,
                is_protected=is_protected
            )

            db.add(species)
            count += 1

            if count % 50 == 0:
                print(f"  Loaded {count} vegetation species...")

    db.commit()
    print(f"✓ Loaded {count} vegetation species")
    return count


def seed_animal_species(db, csv_path):
    """Seed animal species from CSV"""
    print(f"Loading animal species from {csv_path}...")

    count = 0
    with open(csv_path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            taxonomic_group = row['taxonomic_group']

            # Map taxonomic groups to categories
            category = 'animal'
            sub_category = taxonomic_group  # Mammals, Birds, Reptiles, etc.

            # Determine if protected
            is_protected = row['iucn_status'] in ['CR', 'EN', 'VU'] or \
                          (row['cites_appendix'] and row['cites_appendix'] != 'Not listed')

            species = BiodiversitySpecies(
                category=category,
                sub_category=sub_category,
                nepali_name=row['nepali_name'],
                english_name=row['english_name'],
                scientific_name=row['scientific_name'],
                primary_use='Wildlife',  # Animals aren't "used" in CFOP context
                secondary_uses=None,
                iucn_status=row['iucn_status'] if row['iucn_status'] else None,
                cites_appendix=row['cites_appendix'] if row['cites_appendix'] else None,
                distribution=None,  # Not in animal CSV
                notes=row['notes'] if row['notes'] else None,
                is_invasive=False,  # No invasive animals in Nepal context
                is_protected=is_protected
            )

            db.add(species)
            count += 1

            if count % 50 == 0:
                print(f"  Loaded {count} animal species...")

    db.commit()
    print(f"✓ Loaded {count} animal species")
    return count


def main():
    """Main seeding function"""
    print("=" * 60)
    print("BIODIVERSITY SPECIES DATABASE SEEDING")
    print("=" * 60)

    # File paths
    vegetation_csv = Path(__file__).parent.parent / 'testData' / 'nepal_vegetation_species.csv'
    animal_csv = Path(__file__).parent.parent / 'testData' / 'nepal_animal_species.csv'

    # Check files exist
    if not vegetation_csv.exists():
        print(f"ERROR: Vegetation CSV not found at {vegetation_csv}")
        return

    if not animal_csv.exists():
        print(f"ERROR: Animal CSV not found at {animal_csv}")
        return

    # Create database session
    db = SessionLocal()

    try:
        # Check if data already exists
        existing_count = db.query(BiodiversitySpecies).count()
        if existing_count > 0:
            print(f"\n⚠️  WARNING: Database already contains {existing_count} species")
            response = input("Do you want to delete existing data and re-seed? (yes/no): ")
            if response.lower() == 'yes':
                print("Deleting existing species...")
                db.query(BiodiversitySpecies).delete()
                db.commit()
                print("✓ Existing data deleted")
            else:
                print("Seeding cancelled")
                return

        # Seed data
        print("\nSeeding database...\n")
        vegetation_count = seed_vegetation_species(db, vegetation_csv)
        animal_count = seed_animal_species(db, animal_csv)

        total = vegetation_count + animal_count

        print("\n" + "=" * 60)
        print("SEEDING COMPLETE!")
        print("=" * 60)
        print(f"Vegetation species: {vegetation_count}")
        print(f"Animal species: {animal_count}")
        print(f"Total species: {total}")
        print("=" * 60)

    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        db.rollback()
        raise

    finally:
        db.close()


if __name__ == "__main__":
    main()
