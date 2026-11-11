"""Add TEMPLATE_DESIGNER to the userrole enum.

Revision ID: 065_add_template_designer_role
Revises: 064_add_user_group_building_size_categories
Create Date: 2026-08-31

OP multi-template plan, Phase 0 (OP_MULTI_TEMPLATE_PLAN.md §3.1 / §7 D1).

A new global role: authors OP document templates, submits them for
publishing; cannot review/publish (that stays SUPER_ADMIN).

The DB enum label is the member NAME ("TEMPLATE_DESIGNER") to match the
existing uppercase labels (GUEST/USER/ORG_ADMIN/SUPER_ADMIN) — SQLAlchemy's
Enum(UserRole) stores names, not values.

Kept in its own migration with no dependent DDL: on PostgreSQL a new enum
value may be added inside a transaction (PG 12+), but it cannot be *used*
in the same transaction. Nothing here uses it.
"""

from alembic import op

revision = "065_add_template_designer_role"
down_revision = "064_add_user_group_building_size_categories"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TYPE userrole ADD VALUE IF NOT EXISTS 'TEMPLATE_DESIGNER'"
    )


def downgrade() -> None:
    # PostgreSQL cannot DROP a value from an enum. Removing it would require
    # recreating the type and rewriting every dependent column — unsafe and
    # unnecessary for a purely additive label. No-op on downgrade; the label
    # simply remains available.
    pass
