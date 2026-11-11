"""NTFP method cards: the Indian harvest rules of ICFRE 2020 and the Madhya Pradesh protocol 2022, read from their PDFs.

Revision ID: 140_ntfp_india_sources
Revises: 139_ntfp_value_locator_dedupe
Create Date: 2026-10-22

The two sources become 'read' (tier 4, below every Nepal source) and their quantitative figures are added as documented values; the chosen value of every fact
they touch is worked out again with the same rule as the seed (status, then source tier, then the newer year).
"""
import uuid

import sqlalchemy as sa
from alembic import op

from app.core import ntfp_sources as src

revision = "140_ntfp_india_sources"
down_revision = "139_ntfp_value_locator_dedupe"
branch_labels = None
depends_on = None

SOURCE_KEYS = ("ICFRE-2020", "MP-ESIP-2022")
COLS = ("species_key", "field", "part_group", "value_num", "value_num2", "value_text", "unit", "calendar", "source_key", "locator", "status", "chosen", "note")


def upgrade() -> None:
    bind = op.get_bind()
    for k in SOURCE_KEYS:
        s = src.SOURCES[k]
        bind.execute(sa.text("UPDATE ntfp_source SET tier = :t, read_status = :r, note = :n, title = :ti, year = :y WHERE key = :k"),
                     {"t": s["tier"], "r": s["read_status"], "n": s["note"], "ti": s["title"], "y": s["year"], "k": k})
    bind.execute(sa.text("DELETE FROM ntfp_method_value WHERE source_key IN ('ICFRE-2020', 'MP-ESIP-2022')"))
    new = src.india_values()
    # the profiles the values hang on need not exist (a species may have no card); the value table keys on species_key only
    existing = bind.execute(sa.text("SELECT species_key, field, part_group, value_num, value_num2, value_text, unit, calendar, source_key, locator, status, chosen, note "
                                    "FROM ntfp_method_value WHERE (species_key, field, COALESCE(part_group, '')) IN "
                                    + "(" + ",".join(f"(:s{i}, :f{i}, :p{i})" for i in range(len(new))) + ")"),
                            {**{f"s{i}": v["species_key"] for i, v in enumerate(new)}, **{f"f{i}": v["field"] for i, v in enumerate(new)}, **{f"p{i}": v["part_group"] or "" for i, v in enumerate(new)}}).mappings().all()
    rows = [dict(r) for r in existing] + new
    src.finalize_chosen(rows)
    bind.execute(sa.text("UPDATE ntfp_method_value SET chosen = false WHERE (species_key, field, COALESCE(part_group, '')) IN "
                         + "(" + ",".join(f"(:s{i}, :f{i}, :p{i})" for i in range(len(new))) + ")"),
                 {**{f"s{i}": v["species_key"] for i, v in enumerate(new)}, **{f"f{i}": v["field"] for i, v in enumerate(new)}, **{f"p{i}": v["part_group"] or "" for i, v in enumerate(new)}})
    for r in rows:
        if r["source_key"] in SOURCE_KEYS:
            bind.execute(sa.text("INSERT INTO ntfp_method_value (id, " + ", ".join(COLS) + ") VALUES (:id, " + ", ".join(":" + c for c in COLS) + ")"),
                         {"id": uuid.uuid4(), **{c: r.get(c) for c in COLS}})
        elif r["chosen"]:
            bind.execute(sa.text("UPDATE ntfp_method_value SET chosen = true WHERE species_key = :s AND field = :f AND COALESCE(part_group, '') = :p AND source_key = :k AND locator = :l"),
                         {"s": r["species_key"], "f": r["field"], "p": r["part_group"] or "", "k": r["source_key"], "l": r["locator"]})


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(sa.text("DELETE FROM ntfp_method_value WHERE source_key IN ('ICFRE-2020', 'MP-ESIP-2022')"))
    bind.execute(sa.text("UPDATE ntfp_source SET tier = 2, read_status = 'lead' WHERE key IN ('ICFRE-2020', 'MP-ESIP-2022')"))
    # the chosen value of a fact whose only chosen value was deleted: pick the best remaining
    bind.execute(sa.text("""
        UPDATE ntfp_method_value v SET chosen = true FROM (
          SELECT DISTINCT ON (species_key, field, COALESCE(part_group, '')) id FROM ntfp_method_value m JOIN ntfp_source s ON s.key = m.source_key
          WHERE NOT EXISTS (SELECT 1 FROM ntfp_method_value c WHERE c.chosen AND c.species_key = m.species_key AND c.field = m.field AND COALESCE(c.part_group, '') = COALESCE(m.part_group, ''))
          ORDER BY species_key, field, COALESCE(part_group, ''), CASE m.status WHEN 'expert_confirmed' THEN 0 WHEN 'documented' THEN 1 WHEN 'derived' THEN 2 ELSE 3 END, s.tier
        ) b WHERE v.id = b.id"""))
