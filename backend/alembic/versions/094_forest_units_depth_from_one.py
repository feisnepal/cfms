"""Move the depth model to one-based levels (Forest Structure rule, D5).

Revision ID: 094_forest_units_depth_from_one
Revises: 093_drop_deleted_calculations
Create Date: 2026-09-22

Before this migration ``division_level`` used 0 = block, 1 = compartment,
2+ = sub-compartment. The structure plan's depth model (D5, FS-1c.2/1c.3)
makes every *top-level* unit live at depth 1 -- block or compartment -- and
any child at 2+. ``forest_units`` never hands out 0 (``DEPTH_TOP_BLOCK`` /
``DEPTH_TOP_COMPARTMENT`` are both 1, sub-units >= 2; the boundary itself is
depth 0 but is never a unit row).

What this migration does
------------------------
1. Top-level blocks (``NOT is_compartment``, no parent) at 0/NULL -> 1.
2. Compartments whose parent is a block (top compartments) at 0/NULL -> 1,
   and any compartment whose level is not ``parent + 1`` is normalised to
   ``parent + 1`` (migration-026 rule), so a sub-compartment of a top unit
   lands at 2. NULLs are normalised the same way.
3. Server default 0 -> 1, so a column omitted on insert gets a valid depth.
4. A CHECK (``division_level >= 1``) makes depth-0 constructors impossible
   (no upper bound -- deeper nesting than one sub-level stays allowed, A1).

``downgrade`` reverses all four: the CHECK is dropped, the default returns to
0, and top-level units go back to 0. Compartments / sub-compartments keep the
1 / 2 values they held before this migration (their pre-094 0s -- the values
migration 026 itself normalized -- are not reintroduced).
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '094_forest_units_depth_from_one'
down_revision = '093_drop_deleted_calculations'
branch_labels = None
depends_on = None

CHECK_NAME = 'forest_blocks_division_level_check'


def _guard_no_violations(bind) -> None:
    """Refuse to add a CHECK that existing rows would violate."""
    offending = bind.execute(sa.text(
        "SELECT count(*)::int FROM public.forest_blocks "
        "WHERE division_level IS NULL OR division_level < 1"
    )).scalar()
    if offending:
        raise RuntimeError(
            f"{offending} forest_blocks rows still hold a sub-1/NULL division_level; "
            f"the migration's normalisation did not cover them."
        )


def upgrade() -> None:
    bind = op.get_bind()

    # 1. Top-level blocks -> 1.
    bind.execute(sa.text(
        "UPDATE public.forest_blocks SET division_level = 1 "
        "WHERE NOT is_compartment "
        "  AND parent_block_id IS NULL "
        "  AND (division_level = 0 OR division_level IS NULL)"
    ))

    # 2. Top compartments (parent is a block) -> 1.
    bind.execute(sa.text(
        "UPDATE public.forest_blocks fb "
        "SET division_level = 1 "
        "FROM public.forest_blocks fb_parent "
        "WHERE fb.parent_block_id = fb_parent.id "
        "  AND fb.is_compartment = TRUE "
        "  AND NOT fb_parent.is_compartment "
        "  AND (fb.division_level = 0 OR fb.division_level IS NULL)"
    ))

    # 3. Sub-units: normalise every compartment to parent level + 1, walking up
    #    so chains deeper than one sub-level converge (migration-026 rule).
    op.execute("""
        DO $$
        DECLARE
            changed int;
        BEGIN
            LOOP
                UPDATE public.forest_blocks fb_child
                SET division_level = fb_parent.division_level + 1
                FROM public.forest_blocks fb_parent
                WHERE fb_child.parent_block_id = fb_parent.id
                  AND fb_child.is_compartment = TRUE
                  AND fb_parent.is_compartment = TRUE
                  AND fb_parent.division_level IS NOT NULL
                  AND (fb_child.division_level IS NULL
                       OR fb_child.division_level <> fb_parent.division_level + 1);
                GET DIAGNOSTICS changed = ROW_COUNT;
                EXIT WHEN changed = 0;
            END LOOP;
        END $$;
    """)

    _guard_no_violations(bind)

    # 3. Server default 0 -> 1.
    op.execute(
        "ALTER TABLE public.forest_blocks ALTER COLUMN division_level SET DEFAULT 1"
    )

    # 4. Depth-0 constructors impossible.
    op.execute(
        f"ALTER TABLE public.forest_blocks ADD CONSTRAINT {CHECK_NAME} "
        "CHECK (division_level >= 1)"
    )


def downgrade() -> None:
    # 4. Drop the CHECK.
    op.execute(
        f"ALTER TABLE public.forest_blocks DROP CONSTRAINT IF EXISTS {CHECK_NAME}"
    )

    # 3. Server default back to 0.
    op.execute(
        "ALTER TABLE public.forest_blocks ALTER COLUMN division_level SET DEFAULT 0"
    )

    # 1. Top-level units back to 0 (compartments / sub-compartments keep the
    #    levels they had before 094 -- 1 / 2 -- which are valid pre-094 values).
    op.execute(
        "UPDATE public.forest_blocks SET division_level = 0 "
        "WHERE NOT is_compartment AND parent_block_id IS NULL"
    )