"""Give each mappable activity a default map symbol ("kind").

Revision ID: 090_activity_map_kind
Revises: 089_drawn_feature_calc_id
Create Date: 2026-09-20

Drawn activity features have always been able to carry `properties.kind` (the vocabulary and
symbols live in `services/operational_plan/feature_kinds.py`), but nothing ever set it, so every
feature drew as an anonymous default pin / line / polygon. The activity a feature belongs to
already says what it is, so the master list now carries the default: `potential_activities.map_kind`.

A feature's own `properties.kind` still wins; an activity with no kind (a plan-preparation item,
a land-use survey...) falls back to the generic symbol for its geometry.

Only the activities flagged `requires_map` are seeded. The mapping is a first classification of
the master list by activity name; correct any of them with a plain UPDATE (there is no admin
screen for this table). Idempotent: rows that already have a kind are left alone.
"""
import sqlalchemy as sa
from alembic import op

revision = "090_activity_map_kind"
down_revision = "089_drawn_feature_calc_id"
branch_labels = None
depends_on = None

# potential_activities.id -> kind (keys of feature_kinds.KINDS)
SEED = {
    # वन विकासका कार्यहरु
    1: "nursery", 2: "nursery", 4: "plantation", 5: "plantation", 6: "plantation",
    7: "biodiversity_block", 9: "seed_stand",
    # वन संरक्षण कार्यहरु
    10: "signboard", 11: "grazing_closure", 12: "fire_line", 15: "encroachment", 18: "grazing_closure",
    # वन सम्बर्दन कार्यहरु
    20: "anr_area", 21: "signboard", 22: "road",
    23: "silviculture_area", 24: "silviculture_area", 25: "silviculture_area", 26: "silviculture_area",
    27: "permanent_sample_plot",
    # बन सदुपयोग कार्यकमहरु
    28: "monitoring_point", 30: "coupe", 31: "coupe",
    32: "ntfp_zone", 33: "ntfp_zone", 34: "ntfp_zone", 35: "ntfp_zone", 36: "ntfp_zone",
    # गरिवी न्यूनीकरण
    52: "propoor_plot", 54: "agroforestry_area", 58: "agroforestry_area", 59: "agroforestry_area",
    60: "plantation", 61: "agroforestry_area", 62: "nursery",
    # उद्यम विकास / पर्यापर्यटन
    82: "ecotourism_site", 83: "religious_cultural", 84: "fire_tower", 85: "ecotourism_site",
    86: "biodiversity_block", 87: "biodiversity_block", 88: "ecotourism_site", 89: "ecotourism_site",
    90: "trail", 91: "ecotourism_site", 92: "grazing_closure",
    # जलबायु परिबर्तन अनुकूलन
    94: "water_source_protection", 95: "water_source_protection", 98: "fire_line",
    99: "silviculture_area", 100: "water_hole", 101: "plantation",
    # सामुदायिक विकास
    125: "agroforestry_area", 126: "trail",
    127: "community_infrastructure", 128: "community_infrastructure", 131: "community_infrastructure",
}


def upgrade() -> None:
    op.add_column("potential_activities", sa.Column("map_kind", sa.String(length=40), nullable=True))
    conn = op.get_bind()
    for activity_id, kind in SEED.items():
        conn.execute(
            sa.text("UPDATE potential_activities SET map_kind = :k WHERE id = :i AND map_kind IS NULL"),
            {"k": kind, "i": activity_id},
        )


def downgrade() -> None:
    op.drop_column("potential_activities", "map_kind")
