"""P12 / SFM P6 owed mutation — add a terse दिगो वन व्यवस्थापन subsection to the
live cf_db ``op_templates`` is_system row (5b85bbb7-1772-490d-97d8-162b40afb334).

Same out-of-band procedure used for Protection-Working-Circle / RUSLE /
hazard-vuln / CBA: the seed tree (``seed_data.get_default_seed_tree``) already
carries §३.१०, but the live is_system row was last rebuilt (OP Template
Management T1, 2026-09-09) from a ``seed_data.py`` that predated it, so the
subsection is missing from the live row only.

Idempotent — matched on the ``{{sfm_yield_table}}`` marker token:
  * a fresh run snapshots the current tree into ``op_template_versions`` (at the
    current ``op_templates.version``), appends the subsection as the last child
    of Section ३, and bumps ``op_templates.version``;
  * a second run is a no-op.

``--rollback`` restores the most recent "Pre-SFM P12" snapshot.

Run from backend/:
    ../venv/Scripts/python.exe ../scratchpad/patch_system_template_sfm.py [--rollback]
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone

# Bootstrap: make `app` importable when run from anywhere, and keep a Windows
# cp1252 stdout from crashing on the Devanagari it echoes.
_HERE = os.path.dirname(os.path.abspath(__file__))
_BACKEND = os.path.join(os.path.dirname(_HERE), "backend")
if os.path.isdir(_BACKEND) and _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)
try:
    sys.stdout.reconfigure(errors="replace")  # type: ignore[union-attr]
    sys.stderr.reconfigure(errors="replace")  # type: ignore[union-attr]
except Exception:  # noqa: BLE001 -- older Python / non-reconfigurable stream
    pass

from sqlalchemy import text  # noqa: E402

from app.core.database import SessionLocal  # noqa: E402
from app.services.operational_plan.tree_models import TreeNode  # noqa: E402

IS_SYSTEM_ID = "5b85bbb7-1772-490d-97d8-162b40afb334"
MARKER_TOKEN = "{{sfm_yield_table}}"
SNAPSHOT_TAG = "Pre-SFM P12"
SFM_NODE_ID = "sys_026_sfm"

# Terse, matching the style of the sibling analysis subsections
# (Protection Working Circle / Soil Loss / Hazard-Vuln). Uses only registered
# sfm_* variables + the registered thematic spec sfm__forest_type. Renders as a
# heading + empty-state sentences when a forest has no SFM data / is not on the
# sustainable_fmp regime.
SFM_CONTENT = (
    "{{sfm_plan_regime_note}}\n\n"
    "{{sfm_methodology}}\n\n"
    "{{thememap:sfm__forest_type}}\n\n"
    "प्रमुख वन प्रकार: {{sfm_dominant_type_ne}}। उत्पादनशील क्षेत्रफल "
    "{{sfm_production_area_ha}} हेक्टर, संरक्षण क्षेत्रफल "
    "{{sfm_protection_area_ha}} हेक्टर। उत्पादन नियमन अनुसारको वार्षिक कटान "
    "परिमाण {{sfm_total_annual_harvest_m3}} घन.मी. — यो औसत वार्षिक वृद्धि "
    "(MAI) मा आधारित होइन, ≥ ४० से.मि. व्यासका रुखको जम्मा मौज्दातमा कटान "
    "श्रृंखला अनुसार निर्धारण गरिएको हो, र माथिको MAI → वार्षिक अनुमत कटानको "
    "छेउमा राखिएको छ।\n\n"
    "{{unit_label_np}} अनुसार वर्गीकरण र सिफारिस:\n\n"
    "{{sfm_block_prescription_table}}\n\n"
    "वन प्रकार अनुसार क्षेत्रफल:\n\n"
    "{{sfm_type_area_table}}\n\n"
    "{{sfm_felling_series_note}}\n\n"
    "कटान श्रृंखला अनुसार उत्पादन नियमन:\n\n"
    "{{sfm_yield_table}}\n\n"
    "{{sfm_sampling_intensity_note}}\n\n"
    "{{sfm_sampling_plan_table}}\n\n"
    "{{sfm_findings}}\n\n"
    "{{sfm_prescription}}"
)


def _sfm_node() -> dict:
    n = TreeNode(
        id=SFM_NODE_ID,
        type="subsection",
        title_ne="दिगो वन व्यवस्थापन कार्यविधि, २०७९ अनुसारको वर्गीकरण",
        title_en="Sustainable Forest Management (Procedure, 2079) Classification",
        content_type="richtext",
        content=SFM_CONTENT,
        section_key="sfm_classification",
    )
    return n.model_dump()


def _has_marker(nodes) -> bool:
    for n in nodes:
        if MARKER_TOKEN in (n.get("content") or ""):
            return True
        if _has_marker(n.get("children") or []):
            return True
    return False


def _find_section_3(tree: list) -> dict | None:
    for n in tree:
        t = (n.get("title_en") or "") + " " + (n.get("title_ne") or "")
        if n.get("type") == "section" and (
            "Forest Type" in t or "किसिम" in t or "वन प्रकार" in t
        ):
            return n
    return None


def _load(db):
    row = db.execute(
        text("SELECT tree, version FROM op_templates WHERE id = :id"),
        {"id": IS_SYSTEM_ID},
    ).first()
    if row is None:
        return None, None
    tree = row.tree if isinstance(row.tree, list) else json.loads(row.tree)
    return tree, int(row.version)


def _snapshot(db, tree: list, version: int, note: str) -> None:
    db.execute(
        text(
            "INSERT INTO op_template_versions "
            "(id, template_id, version, tree, name, description, changelog, "
            " is_published_snapshot, created_at) "
            "SELECT gen_random_uuid(), :tid, :ver, CAST(:tree AS jsonb), "
            "       t.name, t.description, :note, false, now() "
            "FROM op_templates t WHERE t.id = :tid"
        ),
        {
            "tid": IS_SYSTEM_ID,
            "ver": version,
            "tree": json.dumps(tree, ensure_ascii=False),
            "note": note,
        },
    )


def main(rollback: bool = False) -> None:
    db = SessionLocal()
    try:
        tree, version = _load(db)
        if tree is None:
            print("is_system row not found — nothing to do")
            return

        if rollback:
            snap = db.execute(
                text(
                    "SELECT tree, version FROM op_template_versions "
                    "WHERE template_id = :tid AND changelog LIKE :like "
                    "ORDER BY version DESC, created_at DESC LIMIT 1"
                ),
                {"tid": IS_SYSTEM_ID, "like": SNAPSHOT_TAG + "%"},
            ).first()
            if snap is None:
                print("no '%s' snapshot to roll back to" % SNAPSHOT_TAG)
                return
            snap_tree = (
                snap.tree if isinstance(snap.tree, list) else json.loads(snap.tree)
            )
            db.execute(
                text(
                    "UPDATE op_templates SET tree = CAST(:tree AS jsonb), "
                    "version = version + 1, updated_at = now() WHERE id = :id"
                ),
                {"tree": json.dumps(snap_tree, ensure_ascii=False), "id": IS_SYSTEM_ID},
            )
            db.commit()
            print("rolled back is_system tree to snapshot version", snap.version)
            return

        if _has_marker(tree):
            print(
                "SFM subsection already present (marker %s) — no change" % MARKER_TOKEN
            )
            return

        sec3 = _find_section_3(tree)
        if sec3 is None:
            print("could not locate Section ३ (Forest Types and Species) — aborting")
            return

        _snapshot(
            db,
            tree,
            version,
            f"{SNAPSHOT_TAG} {datetime.now(timezone.utc).isoformat()}",
        )
        sec3.setdefault("children", []).append(_sfm_node())
        db.execute(
            text(
                "UPDATE op_templates SET tree = CAST(:tree AS jsonb), "
                "version = version + 1, updated_at = now() WHERE id = :id"
            ),
            {"tree": json.dumps(tree, ensure_ascii=False), "id": IS_SYSTEM_ID},
        )
        db.commit()
        print(
            "added the SFM (digo van vyavasthapan) subsection %s as the last "
            "child of '%s'; snapshot saved at version %d, live row now version %d"
            % (SFM_NODE_ID, sec3.get("title_en") or "Section 3", version, version + 1)
        )
    finally:
        db.close()


if __name__ == "__main__":
    main(rollback="--rollback" in sys.argv)
