"""Give the `validation` DBH system its Nepali labels.

Revision ID: 104_dbh_validation_np_labels
Revises: 103_policy_species_fk
Create Date: 2026-09-27

Why this migration exists
-------------------------
Phase P2 made `GET /dbh-classes/systems` return full class definitions so the UI
can render a system picker from the API instead of from its own hardcoded arrays.
A test asserting the response is "sufficient to render from alone" immediately
failed on this: `validation` is the only one of the five systems whose classes
carry **no `label_np` at all** - all four are empty strings.

    dfo_export          6/6 labelled
    guideline_2061      8/8
    harvesting_cfmg     3/3
    guideline_simple    4/4
    validation          0/4   <-- here

So a Nepali user opening a system picker would see four unlabelled rows, and the
UI would have to invent a word for each. That is not something to paper over in
the frontend.

The labels are looked up, not written
-------------------------------------
Every one of the four `validation` classes has an **identical `label_en`** to a
class in a system that is already translated:

    validation/regeneration  <- harvesting_cfmg/regeneration   "Regeneration"
    validation/sapling      <- guideline_simple/sapling       "Sapling"
    validation/pole          <- guideline_simple/pole           "Pole"
    validation/tree          <- guideline_simple/tree           "Tree"

So this migration copies `label_np` across on an exact `label_en` match, inside
SQL. Nothing is typed by hand: a Nepali string written into a migration file is a
Nepali string that can be mangled by an editor, a diff tool or a terminal
encoding, and this repository has already been bitten by exactly that. Copying
makes the translation a lookup that is correct by construction, and it stays
correct if either system is later re-translated.

Rows that match nothing are left empty and reported in the migration log, rather
than being given a guess. A blank label is a visible defect; a wrong label is a
silent one.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "104_dbh_validation_np_labels"
down_revision = "103_policy_species_fk"
branch_labels = None
depends_on = None

SYSTEM_WITH_GAPS = "validation"
DONOR_SYSTEMS = ("harvesting_cfmg", "guideline_simple", "guideline_2061", "dfo_export")


def upgrade() -> None:
    bind = op.get_bind()

    rows = bind.execute(
        sa.text(
            "SELECT system_name, class_defs FROM dbh_class_systems "
            "WHERE is_active = true"
        )
    ).fetchall()

    by_system = {r[0]: r[1] or [] for r in rows}
    target = by_system.get(SYSTEM_WITH_GAPS)
    if not target:
        print(
            f"[dbh_validation_np_labels] system '{SYSTEM_WITH_GAPS}' not present; "
            "nothing to do"
        )
        return

    # label_en -> label_np, taken from any system that already has both. Donors
    # are consulted in order, so a concept translated in more than one place takes
    # the first -- and the first is the most directly equivalent system.
    donor: dict[str, str] = {}
    for name in DONOR_SYSTEMS:
        for c in by_system.get(name, []):
            en = (c.get("label_en") or "").strip()
            np_ = (c.get("label_np") or "").strip()
            if en and np_ and en not in donor:
                donor[en] = np_

    filled, still_blank = [], []
    for c in target:
        en = (c.get("label_en") or "").strip()
        if (c.get("label_np") or "").strip():
            continue
        if en in donor:
            c["label_np"] = donor[en]
            filled.append(f"{c.get('key')}={en}")
        else:
            still_blank.append(f"{c.get('key')}={en!r}")

    if not filled and not still_blank:
        print("[dbh_validation_np_labels] every class already had a Nepali label")
        return

    if filled:
        bind.execute(
            sa.text(
                "UPDATE dbh_class_systems SET class_defs = CAST(:defs AS jsonb) "
                "WHERE system_name = :name"
            ),
            {"defs": json_dumps(target), "name": SYSTEM_WITH_GAPS},
        )

    print(
        f"[dbh_validation_np_labels] filled {len(filled)} label(s) on "
        f"{SYSTEM_WITH_GAPS}: {filled}"
    )
    if still_blank:
        print(
            f"[dbh_validation_np_labels] STILL BLANK, no donor found - these need "
            f"translating by hand: {still_blank}"
        )


def json_dumps(value) -> str:
    import json

    return json.dumps(value, ensure_ascii=False)


def downgrade() -> None:
    # The labels are additive and correcting a blank is not a regression worth
    # reversing: a system picker that cannot render Nepali is worse without them.
    print(
        "[dbh_validation_np_labels] labels left in place; blank Nepali labels are "
        "a defect rather than a state worth returning to"
    )
