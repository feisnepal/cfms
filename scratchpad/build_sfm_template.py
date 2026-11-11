"""P12 / SFM P7 owed mutation — build the enhanced दिगो वन व्यवस्थापन OP template
and wire it as the ``sustainable_fmp`` default in cf_db.

The live ``is_system`` template already carries the Protection-Working-Circle /
Soil-Loss / Hazard-Vuln / Cost-Benefit subsections, and (after
``patch_system_template_sfm.py``) the दिगो वन व्यवस्थापन §३.१० subsection too —
so the "enhanced दिगो template" is simply a **published, non-system clone** of
that tree stamped ``plan_regime='sustainable_fmp'``, wired as the default for
both ``sustainable_fmp_new`` and ``sustainable_fmp_revision`` plan kinds.

Idempotent — the enhanced row is matched on
``(is_system=false, source_template_id=<is_system id>, name=<ENHANCED_NAME>)``:
  * first run: INSERT the row + an ``op_template_versions`` v1 snapshot + an
    ``op_template_audit`` (published) row, record the two kinds' current
    ``default_template_id`` to ``scratchpad/.sfm_template_prev_ids.json``, then
    repoint both kinds;
  * re-run: refresh the clone's tree/description, re-point the kinds, leave the
    recorded prev-ids untouched.

``--rollback`` restores the recorded ``default_template_id`` for each kind and
sets the enhanced row back to ``status='draft'`` (the row is kept for history).

Run from backend/:
    ../venv/Scripts/python.exe ../scratchpad/build_sfm_template.py [--rollback]
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone

_HERE = os.path.dirname(os.path.abspath(__file__))
_BACKEND = os.path.join(os.path.dirname(_HERE), "backend")
if os.path.isdir(_BACKEND) and _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)
try:
    sys.stdout.reconfigure(errors="replace")  # type: ignore[union-attr]
    sys.stderr.reconfigure(errors="replace")  # type: ignore[union-attr]
except Exception:  # noqa: BLE001
    pass

from sqlalchemy import text  # noqa: E402

from app.core.database import SessionLocal  # noqa: E402

IS_SYSTEM_ID = "5b85bbb7-1772-490d-97d8-162b40afb334"
ENHANCED_NAME = "दिगो वन व्यवस्थापन कार्ययोजना (उन्नत)"
KIND_KEYS = ("sustainable_fmp_new", "sustainable_fmp_revision")
PREV_IDS_FILE = os.path.join(_HERE, ".sfm_template_prev_ids.json")

# >= 120 chars (the T6 publish gate) + names the दिगो-specific content.
DESCRIPTION = (
    "दिगो वन व्यवस्थापन कार्यविधि, २०७९ (बागमती प्रदेश) अनुसारको उन्नत "
    "कार्ययोजना टेम्पलेट — अनुसूची-१ का १४ वन प्रकारमा वर्गीकरण, कटान "
    "श्रृंखला अनुसार ≥ ४० से.मि. व्यासको जम्मा मौज्दातमा आधारित वार्षिक कटान "
    "परिमाण (औसत वार्षिक वृद्धिमा होइन), माउ रुख संरक्षण, नमुना तीव्रता "
    "(दफा १६) र लागत-लाभ आर्थिक विश्लेषण खण्ड सहित। §३.१० दिगो वन व्यवस्थापन "
    "वर्गीकरण उपखण्ड MAI → वार्षिक अनुमत कटानको छेउमा राखिएको छ।"
)


def _load_system_tree(db) -> list | None:
    row = db.execute(
        text("SELECT tree FROM op_templates WHERE id = :id"), {"id": IS_SYSTEM_ID}
    ).first()
    if row is None:
        return None
    return row.tree if isinstance(row.tree, list) else json.loads(row.tree)


def _find_enhanced(db):
    return db.execute(
        text(
            "SELECT id, status, version FROM op_templates "
            "WHERE is_system = false AND source_template_id = :src AND name = :name"
        ),
        {"src": IS_SYSTEM_ID, "name": ENHANCED_NAME},
    ).first()


def _kind_defaults(db) -> dict:
    out = {}
    for k in KIND_KEYS:
        cur = db.execute(
            text("SELECT default_template_id FROM op_plan_kinds WHERE key = :k"),
            {"k": k},
        ).first()
        out[k] = (
            str(cur.default_template_id) if cur and cur.default_template_id else None
        )
    return out


def _point_kinds(db, template_id: str) -> None:
    for k in KIND_KEYS:
        db.execute(
            text(
                "UPDATE op_plan_kinds SET default_template_id = :tid, updated_at = now() "
                "WHERE key = :k"
            ),
            {"tid": template_id, "k": k},
        )


def main(rollback: bool = False) -> None:
    db = SessionLocal()
    try:
        if rollback:
            if os.path.isfile(PREV_IDS_FILE):
                prev = json.load(open(PREV_IDS_FILE, encoding="utf-8"))
            else:
                # The prev-ids file is *.json-gitignored, so a fresh checkout may
                # not have it. Before P12 all six kinds pointed at the is_system
                # row, so that is the safe fallback for these two.
                prev = {k: IS_SYSTEM_ID for k in KIND_KEYS}
                print("no prev-ids file — falling back to the is_system id")
            for k, tid in prev.items():
                db.execute(
                    text(
                        "UPDATE op_plan_kinds SET default_template_id = :tid, "
                        "updated_at = now() WHERE key = :k"
                    ),
                    {"tid": tid, "k": k},
                )
            row = _find_enhanced(db)
            if row is not None:
                db.execute(
                    text(
                        "UPDATE op_templates SET status = 'draft', updated_at = now() "
                        "WHERE id = :id"
                    ),
                    {"id": str(row.id)},
                )
            db.commit()
            print("rolled back plan-kind defaults to", prev, "; enhanced row -> draft")
            return

        tree = _load_system_tree(db)
        if tree is None:
            print("no is_system template — aborting")
            return
        tree = json.loads(json.dumps(tree))  # deep copy
        has_sfm = "{{sfm_yield_table}}" in json.dumps(tree, ensure_ascii=False)
        if not has_sfm:
            print(
                "WARNING: the is_system tree has no {{sfm_yield_table}} — run "
                "patch_system_template_sfm.py first. Proceeding with the clone anyway."
            )

        now = datetime.now(timezone.utc)
        tree_json = json.dumps(tree, ensure_ascii=False)
        row = _find_enhanced(db)

        if row is None:
            new_id = db.execute(
                text(
                    "INSERT INTO op_templates "
                    "(id, name, description, tree, is_system, status, plan_regime, "
                    " source_template_id, version, published_version, published_at, "
                    " created_at, updated_at) "
                    "VALUES (gen_random_uuid(), :name, :descr, CAST(:tree AS jsonb), "
                    " false, 'published', 'sustainable_fmp', :src, 1, 1, :now, "
                    " :now, :now) RETURNING id"
                ),
                {
                    "name": ENHANCED_NAME,
                    "descr": DESCRIPTION,
                    "tree": tree_json,
                    "src": IS_SYSTEM_ID,
                    "now": now,
                },
            ).scalar()
            new_id = str(new_id)
            db.execute(
                text(
                    "INSERT INTO op_template_versions "
                    "(id, template_id, version, tree, name, description, changelog, "
                    " is_published_snapshot, created_at) "
                    "VALUES (gen_random_uuid(), :tid, 1, CAST(:tree AS jsonb), :name, "
                    " :descr, 'SFM P12 — published clone of the is_system tree', "
                    " true, :now)"
                ),
                {
                    "tid": new_id,
                    "tree": tree_json,
                    "name": ENHANCED_NAME,
                    "descr": DESCRIPTION,
                    "now": now,
                },
            )
            db.execute(
                text(
                    "INSERT INTO op_template_audit "
                    "(id, template_id, actor_id, action, from_status, to_status, "
                    " note, version, created_at) "
                    "VALUES (gen_random_uuid(), :tid, NULL, 'published', NULL, "
                    " 'published', :note, 1, :now)"
                ),
                {
                    "tid": new_id,
                    "note": "SFM P12 — enhanced digo van vyavasthapan template",
                    "now": now,
                },
            )
            created = True
        else:
            new_id = str(row.id)
            db.execute(
                text(
                    "UPDATE op_templates SET tree = CAST(:tree AS jsonb), "
                    "description = :descr, status = 'published', "
                    "plan_regime = 'sustainable_fmp', version = version + 1, "
                    "updated_at = :now WHERE id = :id"
                ),
                {"tree": tree_json, "descr": DESCRIPTION, "now": now, "id": new_id},
            )
            created = False

        # Record the kinds' CURRENT defaults before repointing — but never
        # overwrite an existing record (so a re-run keeps the true originals).
        if not os.path.isfile(PREV_IDS_FILE):
            prev = _kind_defaults(db)
            with open(PREV_IDS_FILE, "w", encoding="utf-8") as f:
                json.dump(prev, f, ensure_ascii=False, indent=2)
        else:
            prev = json.load(open(PREV_IDS_FILE, encoding="utf-8"))

        _point_kinds(db, new_id)
        db.commit()
        print(
            "%s enhanced template id=%s ; pointed %s at it ; recorded prev-ids=%s"
            % ("created" if created else "refreshed", new_id, list(KIND_KEYS), prev)
        )
    finally:
        db.close()


if __name__ == "__main__":
    main(rollback="--rollback" in sys.argv)
