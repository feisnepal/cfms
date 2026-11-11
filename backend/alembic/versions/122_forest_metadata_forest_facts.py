"""Forest metadata: the forest / group facts the plan's Metadata form used to hold.

Revision ID: 122_forest_metadata_forest_facts
Revises: 121_drop_forest_metadata_chairperson
Create Date: 2026-10-14

Registration and identity numbers, the four boundaries of the forest and of the user group, the group's own location, the
physiography / protection status and the forest's character (type, abundance, age, non-timber products, crown density).
All nullable and optional (never part of the mandatory form). Existing rows are filled from the forest's latest
operational plan, so nothing a plan already typed is lost.
"""

import sqlalchemy as sa
from alembic import op

revision = "122_forest_metadata_forest_facts"
down_revision = "121_drop_forest_metadata_chairperson"
branch_labels = None
depends_on = None

COLUMNS = [
    ("cf_registration_number", sa.String(64)),
    ("constitution_approved_year", sa.String(32)),
    ("user_group_reg_no", sa.String(32)),
    ("cf_sn_number", sa.String(32)),
    ("cf_boundary_east", sa.Text()),
    ("cf_boundary_south", sa.Text()),
    ("cf_boundary_west", sa.Text()),
    ("cf_boundary_north", sa.Text()),
    ("physiography_zone", sa.String(255)),
    ("protected_area_status", sa.String(255)),
    ("forest_type", sa.String(64)),
    ("forest_abundance", sa.String(64)),
    ("forest_avg_age", sa.String(32)),
    ("main_non_timber_fp", sa.Text()),
    ("avg_crown_density_pct", sa.String(32)),
    ("ug_province", sa.String(255)),
    ("ug_district", sa.String(255)),
    ("ug_municipality", sa.String(255)),
    ("ug_municipality_type", sa.String(64)),
    ("ug_ward", sa.String(64)),
    ("ug_division", sa.String(255)),
    ("ug_sub_division", sa.String(255)),
    ("ug_settlement", sa.String(255)),
    ("ug_boundary_east", sa.Text()),
    ("ug_boundary_south", sa.Text()),
    ("ug_boundary_west", sa.Text()),
    ("ug_boundary_north", sa.Text()),
]
BACKFILL = ['sub_division_chief', 'forest_management_section_chief', 'division_forest_officer', 'technical_assistance_org', 'cf_handover_date', 'cf_first_renewal_date', 'cf_history_note', 'cf_registration_number', 'constitution_approved_year', 'user_group_reg_no', 'cf_sn_number', 'cf_boundary_east', 'cf_boundary_south', 'cf_boundary_west', 'cf_boundary_north', 'physiography_zone', 'protected_area_status', 'forest_type', 'forest_abundance', 'forest_avg_age', 'main_non_timber_fp', 'avg_crown_density_pct', 'ug_province', 'ug_district', 'ug_municipality', 'ug_municipality_type', 'ug_ward', 'ug_division', 'ug_sub_division', 'ug_settlement', 'ug_boundary_east', 'ug_boundary_south', 'ug_boundary_west', 'ug_boundary_north']

_SQL = """
UPDATE forest_metadata fm
   SET @@COL@@ = p.value
  FROM (
        SELECT DISTINCT ON (calculation_id) calculation_id,
               plan_metadata -> 'user_inputs' ->> :k AS value
          FROM operational_plans
         ORDER BY calculation_id, updated_at DESC
       ) p
 WHERE p.calculation_id = fm.calculation_id
   AND fm.@@COL@@ IS NULL
   AND COALESCE(p.value, '') <> ''
"""


def upgrade() -> None:
    for name, type_ in COLUMNS:
        op.add_column("forest_metadata", sa.Column(name, type_, nullable=True))
    bind = op.get_bind()
    for key in BACKFILL:   # keys are the fixed list above, never user input
        bind.execute(sa.text(_SQL.replace("@@COL@@", key)), {"k": key})


def downgrade() -> None:
    for name, _ in reversed(COLUMNS):
        op.drop_column("forest_metadata", name)
