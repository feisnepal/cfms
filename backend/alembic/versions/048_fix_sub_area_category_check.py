"""Align the forest_sub_areas category CHECK with the categories the app accepts.

Revision ID: 048_fix_sub_area_category
Revises: 047_backfill_hand_applied
Create Date: 2026-08-20

Why this migration exists (report S1-70, task H1.6 fallout)
-----------------------------------------------------------
``013_add_forest_blocks_and_sub_areas_tables`` created ``forest_sub_areas`` with

    CHECK (category IN ('protected', 'plantation', 'pro-poor', 'religious',
                        'biodiversity', 'tourist', 'office', 'private_land'))

while ``services/sub_area_service.py:172`` validates against an entirely
different 14-value set:

    road, stream, river, degraded, plantation, settlement, agriculture,
    water_body, cliff, wetland, grassland, shrubland, conservation, other

The two lists overlap on ``plantation`` and nothing else. Every other category
the application offers — thirteen of fourteen — passes application validation
and is then rejected by the database with a CheckViolation.

This had never surfaced because ``forest_sub_areas`` is empty in production and
the test harness built its schema from ``Base.metadata``, which declares no CHECK
constraint at all, so tests inserted freely. Pointing the harness at the real
migrations (task H1.6) exposed it immediately.

The service-layer list is authoritative: it is what the API validates against,
what the category picker offers, and what ``_category_colour`` styles. The
constraint is replaced to match it.

Safe on existing databases: the table is empty in production, so no row can
violate the new constraint. The guard below re-checks that at run time rather
than assuming it.
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '048_fix_sub_area_category'
down_revision = '047_backfill_hand_applied'
branch_labels = None
depends_on = None

CONSTRAINT = 'forest_sub_areas_category_check'

# Mirrors sub_area_service.VALID_CATEGORIES. Keep the two in step — a drift test
# asserting they match belongs with the service, not here.
APP_CATEGORIES = (
    'road', 'stream', 'river', 'degraded', 'plantation', 'settlement',
    'agriculture', 'water_body', 'cliff', 'wetland', 'grassland', 'shrubland',
    'conservation', 'other',
)

LEGACY_CATEGORIES = (
    'protected', 'plantation', 'pro-poor', 'religious', 'biodiversity',
    'tourist', 'office', 'private_land',
)


def _in_list(values: tuple[str, ...]) -> str:
    return ', '.join(f"'{v}'" for v in values)


def _swap(bind, allowed: tuple[str, ...]) -> None:
    if sa.inspect(bind).get_table_names(schema='public').count('forest_sub_areas') == 0:
        return

    offending = bind.execute(sa.text(
        f"SELECT count(*) FROM public.forest_sub_areas "
        f"WHERE category NOT IN ({_in_list(allowed)})"
    )).scalar()
    if offending:
        raise RuntimeError(
            f"{offending} forest_sub_areas rows carry a category outside the target "
            f"set; reclassify them before applying this migration."
        )

    op.execute(f'ALTER TABLE public.forest_sub_areas DROP CONSTRAINT IF EXISTS {CONSTRAINT}')
    op.execute(
        f'ALTER TABLE public.forest_sub_areas ADD CONSTRAINT {CONSTRAINT} '
        f'CHECK (category IN ({_in_list(allowed)}))'
    )


def upgrade() -> None:
    """Replace the legacy eight-value CHECK with the application's fourteen."""
    _swap(op.get_bind(), APP_CATEGORIES)


def downgrade() -> None:
    """Restore the legacy CHECK. Fails loudly if rows would violate it."""
    _swap(op.get_bind(), LEGACY_CATEGORIES)
