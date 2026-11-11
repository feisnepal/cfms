#!/usr/bin/env python
"""Add the regulation-group species section (fi_reg_* / fi_regc_*) to the OP templates, in place.

    python -m scripts.add_regulation_species_section [--dry-run]

* System Template   - re-synced from seed_data.py (rebuild_system_template), which now carries the section.
* Rambhadevi SFM Renew - two subsections right after the species-wise tree stock node.
* sustanable forest plan - two subsections at the end of the section "वनको किसिम र मुख्य प्रजाती".

Idempotent (a template that already holds the section is skipped). Each changed template keeps a version snapshot, so it
can be rolled back from its version history. Section numbers are recomputed after the insert.
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text  # noqa: E402

TARGETS = [
    ("Rambhadevi SFM Renew", {"after_token": "{{fi_species_tree_per_ha_table}}"}),
    ("sustanable forest plan", {"into_section_title": "वनको किसिम र मुख्य प्रजाती"}),
]


def _flat(nodes):
    for n in nodes:
        yield n
        yield from _flat(n.get("children") or [])


def _patch(session, name, anchor, dry_run):
    from app.services.operational_plan.auto_numbering import recompute_numbers
    from app.services.operational_plan.regulation_species_section import insert_into_tree
    from app.services.operational_plan.template_utils import generate_template_summaries
    from app.services.operational_plan.tree_models import TreeNode

    row = session.execute(text("SELECT id, tree, version FROM public.op_templates WHERE name = :n"), {"n": name}).mappings().first()
    if row is None:
        return "missing"
    tree = json.loads(json.dumps(row["tree"]))
    if not insert_into_tree(tree, **anchor):
        return "skipped (already there, or anchor not found)"
    # renumber, but never give a number to a node that had none (unnumbered annex sections stay unnumbered)
    old = {n["id"]: n.get("number") for n in _flat(json.loads(json.dumps(row["tree"])))}
    nodes = [TreeNode.from_dict(n) for n in tree]
    recompute_numbers(nodes, "NP")
    tree = [n.model_dump() for n in nodes]
    for n in _flat(tree):
        if n["id"] in old and old[n["id"]] is None:
            n["number"] = None
    if dry_run:
        return "would add 2 subsections"
    summ = generate_template_summaries(tree)
    session.execute(text(
        "INSERT INTO public.op_template_versions (id, template_id, version, tree, name, description, changelog) "
        "SELECT gen_random_uuid(), id, COALESCE(version, 1), tree, name, COALESCE(description, ''), "
        "'Before adding the regulation species section' FROM public.op_templates WHERE id = :id"), {"id": row["id"]})
    session.execute(text(
        "UPDATE public.op_templates SET tree = CAST(:t AS jsonb), version = COALESCE(version, 1) + 1, "
        "sections_summary = CAST(:ss AS jsonb), variables_summary = CAST(:vs AS jsonb), updated_at = now() WHERE id = :id"),
        {"id": row["id"], "t": json.dumps(tree, ensure_ascii=False),
         "ss": json.dumps(summ["sections_summary"], ensure_ascii=False),
         "vs": json.dumps(summ["variables_summary"], ensure_ascii=False)})
    return "added 2 subsections"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    from app.core.database import SessionLocal
    from scripts.rebuild_system_template import rebuild_system_template

    session = SessionLocal()
    try:
        print("System Template:", rebuild_system_template(session, dry_run=args.dry_run)["action"])
        for name, anchor in TARGETS:
            print(f"{name}:", _patch(session, name, anchor, args.dry_run))
        session.rollback() if args.dry_run else session.commit()
    finally:
        session.close()


if __name__ == "__main__":
    main()
