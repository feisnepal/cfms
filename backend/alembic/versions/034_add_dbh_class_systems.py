"""Add dbh_class_systems and dbh_classification_changes tables.

Revision ID: 034_add_dbh_class_systems
Revises: 033_add_dimension_exclusivity_trigger
Create Date: 2026-07-25
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "034_add_dbh_class_systems"
down_revision = "033_add_dimension_exclusivity_trigger"


GUIDELINE_2061_CLASSES = [
    {"key": "0_4",    "lower": 0,   "upper": 4,   "label_en": "Seedling",       "label_np": "बिरुवा",       "stand_type": "Regeneration"},
    {"key": "4_10",   "lower": 4,   "upper": 10,  "label_en": "Sapling",        "label_np": "लाथ्रा",       "stand_type": "Sapling"},
    {"key": "10_20",  "lower": 10,  "upper": 20,  "label_en": "Small Pole",     "label_np": "सानो खाँवा",   "stand_type": "Pole"},
    {"key": "20_30",  "lower": 20,  "upper": 30,  "label_en": "Large Pole",     "label_np": "ठुलो खाँवा",   "stand_type": "Pole"},
    {"key": "30_40",  "lower": 30,  "upper": 40,  "label_en": "Small Tree",     "label_np": "सानो रुख",     "stand_type": "Tree"},
    {"key": "40_50",  "lower": 40,  "upper": 50,  "label_en": "Medium Tree",    "label_np": "मझौला रुख",    "stand_type": "Tree"},
    {"key": "50_60",  "lower": 50,  "upper": 60,  "label_en": "Large Tree",     "label_np": "ठुलो रुख",     "stand_type": "Tree"},
    {"key": "60_plus","lower": 60,  "upper": None,"label_en": "Very Large Tree","label_np": "अति ठुलो रुख","stand_type": "Tree"},
]

GUIDELINE_SIMPLE_CLASSES = [
    {"key": "seedling",  "lower": 0,   "upper": 4,   "label_en": "Seedling",  "label_np": "बिरुवा"},
    {"key": "sapling",   "lower": 4,   "upper": 10,  "label_en": "Sapling",   "label_np": "लाथ्रा"},
    {"key": "pole",      "lower": 10,  "upper": 30,  "label_en": "Pole",      "label_np": "खाँवा"},
    {"key": "tree",      "lower": 30,  "upper": None, "label_en": "Tree",     "label_np": "रुख"},
]

HARVESTING_CFMG_CLASSES = [
    {"key": "regeneration",   "lower": 0,   "upper": 10, "label_en": "Regeneration",  "label_np": "पुनरुत्पादन"},
    {"key": "advance_growth", "lower": 10,  "upper": 40, "label_en": "Advance Growth", "label_np": "अग्रिम वृद्धि"},
    {"key": "mature_tree",    "lower": 40,  "upper": None,"label_en": "Mature Tree",  "label_np": "पाको रुख"},
]

DFO_EXPORT_CLASSES = []
_guideline_2061_keys = {c["key"] for c in GUIDELINE_2061_CLASSES}
_pole_tree_keys = ["10_20", "20_30", "30_40", "40_50", "50_60", "60_plus"]
for c in GUIDELINE_2061_CLASSES:
    if c["key"] in _pole_tree_keys:
        DFO_EXPORT_CLASSES.append(c)

VALIDATION_CLASSES = [
    {"key": "regeneration", "lower": 1,   "upper": 4,   "label_en": "Regeneration", "strict": True},
    {"key": "sapling",      "lower": 4,   "upper": 10,  "label_en": "Sapling",      "strict": True},
    {"key": "pole",         "lower": 10,  "upper": 30,  "label_en": "Pole",         "strict": False},
    {"key": "tree",         "lower": 30,  "upper": 200, "label_en": "Tree",         "strict": False},
]

SEED_SYSTEMS = [
    {
        "system_name": "guideline_2061",
        "version": "1.0",
        "description": "Nepal Forest Regulation 2079 — Guideline 2061 detailed 8-class",
        "effective_date": "2079-01-01",
        "is_system_default": True,
        "class_defs": GUIDELINE_2061_CLASSES,
    },
    {
        "system_name": "guideline_simple",
        "version": "1.0",
        "description": "Nepal Forest Regulation 2079 — Guideline 2061 simplified 4-class",
        "effective_date": "2079-01-01",
        "is_system_default": True,
        "class_defs": GUIDELINE_SIMPLE_CLASSES,
    },
    {
        "system_name": "harvesting_cfmg",
        "version": "1.0",
        "description": "Community Forest Management Guideline — 3-group: Regeneration/Advance Growth/Mature Tree",
        "effective_date": "2080-01-01",
        "is_system_default": True,
        "class_defs": HARVESTING_CFMG_CLASSES,
    },
    {
        "system_name": "dfo_export",
        "version": "1.0",
        "description": "DFO reporting format — Pole+Tree classes only (6-class subset of guideline_2061)",
        "effective_date": "2079-01-01",
        "is_system_default": True,
        "class_defs": DFO_EXPORT_CLASSES,
    },
    {
        "system_name": "validation",
        "version": "1.0",
        "description": "Field inventory validation thresholds (stricter bounds for data quality)",
        "effective_date": "2079-01-01",
        "is_system_default": True,
        "class_defs": VALIDATION_CLASSES,
    },
]


def upgrade():
    op.create_table(
        "dbh_class_systems",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("system_name", sa.String(50), nullable=False, unique=True),
        sa.Column("version", sa.String(20), nullable=False, server_default="1.0"),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("effective_date", sa.Date(), nullable=True),
        sa.Column(
            "class_defs",
            postgresql.JSONB,
            nullable=False,
            comment="List of class dicts with key, lower, upper, label_en, label_np, stand_type, etc.",
        ),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column(
            "is_system_default",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
            comment="If true, API prevents deletion/renaming — protects core Nepal forestry regulation systems",
        ),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
    )

    op.create_table(
        "dbh_classification_changes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("system_name", sa.String(50), nullable=False),
        sa.Column("change_type", sa.String(20), nullable=False),
        sa.Column("old_defs", postgresql.JSONB, nullable=True),
        sa.Column("new_defs", postgresql.JSONB, nullable=True),
        sa.Column("changed_by", sa.String(100), nullable=True),
        sa.Column("changed_at", sa.DateTime(), server_default=sa.func.now()),
    )

    op.create_index("ix_dbh_class_systems_name", "dbh_class_systems", ["system_name"])
    op.create_index("ix_dbh_class_changes_system", "dbh_classification_changes", ["system_name"])

    # Seed the 5 core classification systems
    import json
    conn = op.get_bind()
    for system in SEED_SYSTEMS:
        cd_json = json.dumps(system["class_defs"], ensure_ascii=False)
        conn.execute(
            sa.text(
                """INSERT INTO dbh_class_systems
                   (system_name, version, description, effective_date, is_system_default, class_defs)
                   VALUES (:sn, :v, :d, :ed, :isd, CAST(:cd AS jsonb))"""
            ).params(
                sn=system["system_name"],
                v=system["version"],
                d=system["description"],
                ed=system["effective_date"],
                isd=system["is_system_default"],
                cd=cd_json,
            )
        )


def downgrade():
    op.drop_table("dbh_classification_changes")
    op.drop_table("dbh_class_systems")
