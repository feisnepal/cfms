"""ntfp_source and ntfp_method_value: the source of every method-card value; provisional cards for the Schedule-7 species without a documented card.

Revision ID: 138_ntfp_method_sources
Revises: 137_ntfp_harvest_plan
Create Date: 2026-10-22

Owner requirement 2026-10-22: the source of a method card must be specified. Every value (plot size, maturity sign, annual allowable harvest, season, ...) is a row
with its source, the table or page, and a status (documented / derived / provisional / expert_confirmed); conflicting sources are kept and one is chosen.
Seeded from ``app.core.ntfp_sources`` (what was read: the Nepal guideline, the two ANSAB toolkits, India's Working Plan Code and national inventory) and
``app.core.ntfp_provisional`` (rule-derived cards for the 238 species without a documented card). From then on the tables are the source.
"""
import uuid

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "138_ntfp_method_sources"
down_revision = "137_ntfp_harvest_plan"
branch_labels = None
depends_on = None

PROFILE_COLS = [
    "species_key", "scientific_name", "regulation_name", "aliases", "nepali_name", "priority_serial", "altitude_min_m", "altitude_max_m", "parts_used_ne", "uses_ne",
    "has_method_card", "life_form_ne", "growth_class", "part_ne", "part_groups", "sampling_method", "plot_min_sqm", "plot_max_sqm", "maturity_ne", "n_individuals_min",
    "n_individuals_max", "harvest_fraction_pct", "conversion_factor", "procedure_en", "card_status",
]
UPDATE_COLS = ["growth_class", "part_groups", "part_ne", "sampling_method", "plot_min_sqm", "plot_max_sqm", "n_individuals_min", "n_individuals_max", "procedure_en",
               "has_method_card", "card_status", "regulation_name"]


def upgrade() -> None:
    op.create_table(
        "ntfp_source",
        sa.Column("key", sa.String(40), primary_key=True),
        sa.Column("title", sa.Text, nullable=False),
        sa.Column("publisher", sa.String(255), nullable=True),
        sa.Column("year", sa.String(40), nullable=True),
        sa.Column("url", sa.String(500), nullable=True),
        sa.Column("tier", sa.Integer, nullable=False, server_default="5"),
        sa.Column("read_status", sa.String(10), nullable=False, server_default="read"),
        sa.Column("licence", sa.String(255), nullable=True),
        sa.Column("note", sa.Text, nullable=True),
        sa.CheckConstraint("read_status IN ('read','lead')", name="ck_ntfp_source_read"),
    )
    op.create_table(
        "ntfp_method_value",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("species_key", sa.String(120), nullable=False),
        sa.Column("field", sa.String(30), nullable=False),
        sa.Column("part_group", sa.String(2), nullable=True),
        sa.Column("value_num", sa.Numeric(14, 4), nullable=True),
        sa.Column("value_num2", sa.Numeric(14, 4), nullable=True),
        sa.Column("value_text", sa.Text, nullable=True),
        sa.Column("unit", sa.String(12), nullable=True),
        sa.Column("calendar", sa.String(2), nullable=True),
        sa.Column("source_key", sa.String(40), sa.ForeignKey("ntfp_source.key"), nullable=False),
        sa.Column("locator", sa.String(200), nullable=True),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("chosen", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("note", sa.Text, nullable=True),
        sa.Column("reviewed_by", sa.String(120), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("status IN ('documented','derived','provisional','expert_confirmed')", name="ck_ntfp_value_status"),
        sa.CheckConstraint("calendar IS NULL OR calendar IN ('AD','BS')", name="ck_ntfp_value_calendar"),
    )
    op.create_index("ix_ntfp_method_value_species", "ntfp_method_value", ["species_key", "field"])
    # one chosen value per fact
    op.execute("CREATE UNIQUE INDEX uq_ntfp_value_chosen ON ntfp_method_value (species_key, field, COALESCE(part_group, '')) WHERE chosen")
    op.add_column("ntfp_method_profile", sa.Column("card_status", sa.String(20), nullable=True))
    op.create_check_constraint("ck_ntfp_profile_card_status", "ntfp_method_profile", "card_status IS NULL OR card_status IN ('documented','provisional','expert_confirmed')")

    from app.core import ntfp_provisional, ntfp_sources
    from app.core.ntfp_methods import profiles
    from app.core.species_synonyms import canonical_key

    bind = op.get_bind()
    # the species master's growth form, by canonical key (genus entries match any species of the genus)
    bio = {}
    for sci, sub in bind.execute(sa.text("SELECT scientific_name, sub_category FROM biodiversity_species WHERE category = 'vegetation' AND sub_category IS NOT NULL")).all():
        bio.setdefault(canonical_key(sci), sub)

    def master(key):
        if key in bio:
            return bio[key]
        return next((v for k, v in bio.items() if k.split()[0] == key), None) if " " not in key else None

    seed_profiles = {p["species_key"]: p for p in profiles()}
    prov_profiles, prov_values = ntfp_provisional.derive(master, seed_profiles)
    documented = ntfp_sources.all_documented_values(list(seed_profiles.values()))
    known = set(seed_profiles) | {p["species_key"] for p in prov_profiles}
    stubs = ntfp_provisional.stub_profiles(documented + prov_values, known)
    values = ntfp_sources.finalize_chosen(documented + prov_values)

    source_table = sa.table("ntfp_source", *[sa.column(c) for c in ("key", "title", "publisher", "year", "url", "tier", "read_status", "licence", "note")])
    op.bulk_insert(source_table, [{"key": k, **{c: s.get(c) for c in ("title", "publisher", "year", "url", "tier", "read_status", "licence", "note")}} for k, s in ntfp_sources.SOURCES.items()])

    # the profiles: new rows for species with no profile (every row carries every column: bulk_insert takes its columns from the first row)
    profile_table = sa.table("ntfp_method_profile", sa.column("id", postgresql.UUID(as_uuid=True)), *[sa.column(c) for c in PROFILE_COLS],
                             sa.column("part_groups", postgresql.JSONB), sa.column("aliases", postgresql.JSONB))
    new_rows = []
    for p in prov_profiles + stubs:
        if p["op"] != "insert":
            continue
        row = {c: p.get(c) for c in PROFILE_COLS}
        row["part_groups"] = p.get("part_groups") or []
        row["aliases"] = []
        row["has_method_card"] = bool(p.get("has_method_card"))
        new_rows.append({"id": uuid.uuid4(), **row})
    if new_rows:
        op.bulk_insert(profile_table, new_rows)
    for p in prov_profiles:  # an Annex-1 species without a card becomes a provisional card
        if p["op"] == "update":
            sets = ", ".join(f"{c} = :{c}" for c in UPDATE_COLS if c != "part_groups") + ", part_groups = CAST(:part_groups AS jsonb), updated_at = now()"
            params = {c: p.get(c) for c in UPDATE_COLS}
            params["part_groups"] = __import__("json").dumps(p["part_groups"])
            op.execute(sa.text(f"UPDATE ntfp_method_profile SET {sets} WHERE species_key = :key").bindparams(key=p["species_key"], **params))
    op.execute("UPDATE ntfp_method_profile SET card_status = 'documented' WHERE has_method_card AND card_status IS NULL")

    value_table = sa.table("ntfp_method_value", sa.column("id", postgresql.UUID(as_uuid=True)),
                           *[sa.column(c) for c in ("species_key", "field", "part_group", "value_num", "value_num2", "value_text", "unit", "calendar", "source_key", "locator", "status", "chosen", "note")])
    op.bulk_insert(value_table, [{"id": uuid.uuid4(), **{c: v.get(c) for c in ("species_key", "field", "part_group", "value_num", "value_num2", "value_text", "unit", "calendar", "source_key", "locator", "status", "chosen", "note")}} for v in values])


def downgrade() -> None:
    op.drop_constraint("ck_ntfp_profile_card_status", "ntfp_method_profile", type_="check")
    op.drop_column("ntfp_method_profile", "card_status")
    op.drop_table("ntfp_method_value")
    op.drop_table("ntfp_source")
    # the provisional profile rows stay: they are data a user may already have designed with
