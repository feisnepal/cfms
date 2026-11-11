"""
Data migration: detect forests with compartments but wrong dimension mode.

Run manually after deployment:
    python -m backend.scripts.migrate_existing_dimension

What it fixes:
    - Forests that have compartments (forest_blocks.is_compartment=true)
      but result_data has no 'compartments' key or sampling_unit != 'compartment'
      -> sets dimension to compartment mode

    - Forests that have NO compartments
      but result_data has sampling_unit = 'compartment'
      -> sets dimension back to block mode

What it does NOT do:
    - Re-run analysis (must be triggered manually via reanalysis endpoint)
    - Delete or modify any sampling designs
"""
import argparse
import json
import logging
import os
import re
import sys
from typing import Tuple

from sqlalchemy import create_engine, text

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

MIGRATION_VERSION = "2026-07-25-001"


def detect_misconfigured_forests(db_url: str) -> Tuple[list, list]:
    """
    Detect forests with dimension mismatch.
    Returns (needs_compartment, needs_block).
    """
    engine = create_engine(db_url)

    with engine.connect() as conn:
        needs_compartment = conn.execute(text("""
            SELECT DISTINCT c.id, c.forest_name,
                   c.result_data->>'sampling_unit' as current_unit
            FROM public.calculations c
            WHERE EXISTS (
                SELECT 1 FROM public.forest_blocks fb
                WHERE fb.calculation_id = c.id
                  AND fb.is_compartment = true
            )
            AND (
                c.result_data->>'sampling_unit' IS NULL
                OR c.result_data->>'sampling_unit' NOT IN ('compartment', 'sub_compartment')
            )
            AND c.status = 'COMPLETED'
            ORDER BY c.forest_name
        """)).fetchall()

        needs_block = conn.execute(text("""
            SELECT DISTINCT c.id, c.forest_name,
                   c.result_data->>'sampling_unit' as current_unit
            FROM public.calculations c
            WHERE NOT EXISTS (
                SELECT 1 FROM public.forest_blocks fb
                WHERE fb.calculation_id = c.id
                  AND fb.is_compartment = true
            )
            AND c.result_data->>'sampling_unit' IN ('compartment', 'sub_compartment')
            AND c.status = 'COMPLETED'
            ORDER BY c.forest_name
        """)).fetchall()

    return needs_compartment, needs_block


def fix_sampling_unit(
    db_url: str, calculation_id: str, target_unit: str, dry_run: bool = True
) -> bool:
    """Fix the sampling_unit for a single calculation."""
    if dry_run:
        logger.info(
            f"  [DRY-RUN] Would update {calculation_id}: sampling_unit -> '{target_unit}'"
        )
        return True

    engine = create_engine(db_url)
    with engine.connect() as conn:
        conn.execute(
            text("""
                UPDATE public.calculations
                SET result_data = jsonb_set(
                    COALESCE(result_data, '{}'::jsonb),
                    '{sampling_unit}',
                    CAST(:unit AS jsonb)
                )
                WHERE id = CAST(:cid AS uuid)
            """),
            {"cid": str(calculation_id), "unit": json.dumps(target_unit)},
        )
        conn.commit()

    logger.info(f"  [FIXED] {calculation_id}: sampling_unit -> '{target_unit}'")
    return True


def run_migration(db_url: str, dry_run: bool = True) -> int:
    """Run the dimension migration."""
    logger.info(f"=== Dimension Migration v{MIGRATION_VERSION} ===")
    # H1.13 / S2-69: log the target without its credentials.
    logger.info("DB: %s", re.sub(r"//[^@]*@", "//***@", db_url))
    logger.info(f"Mode: {'DRY RUN' if dry_run else 'APPLY'}")
    logger.info("")

    needs_compartment, needs_block = detect_misconfigured_forests(db_url)

    logger.info(f"Found {len(needs_compartment)} forests needing 'compartment' mode")
    for calc in needs_compartment:
        logger.info(f"  - {calc.forest_name} ({calc.id}) [current: {calc.current_unit}]")

    logger.info("")
    logger.info(f"Found {len(needs_block)} forests needing 'block' mode")
    for calc in needs_block:
        logger.info(f"  - {calc.forest_name} ({calc.id}) [current: {calc.current_unit}]")

    logger.info("")
    fixed = 0

    for calc in needs_compartment:
        if fix_sampling_unit(db_url, calc.id, "compartment", dry_run):
            fixed += 1

    for calc in needs_block:
        if fix_sampling_unit(db_url, calc.id, "block", dry_run):
            fixed += 1

    logger.info("")
    logger.info(
        f"Migration complete: {fixed} calculations affected (dry_run={dry_run})"
    )
    return fixed


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Migrate existing forests to correct dimension mode"
    )
    parser.add_argument(
        "--db-url",
        # H1.13 / S2-69: the live database password used to sit here as a
        # default, in a git-tracked file. Falls back to DATABASE_URL; with
        # neither set, the script exits rather than guessing a target.
        default=os.environ.get("DATABASE_URL"),
        help="Target database. Defaults to $DATABASE_URL. Required.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=True,
        help="Preview changes without applying (default: True)",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually apply changes (overrides dry-run)",
    )

    args = parser.parse_args()

    if not args.db_url:
        sys.exit(
            "No database specified. Pass --db-url or set DATABASE_URL. "
            "This script used to default to a hardcoded production URL (S2-69); "
            "it now refuses to guess."
        )
    dry_run = not args.apply
    run_migration(args.db_url, dry_run=dry_run)
