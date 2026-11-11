"""CFMG harvest-class grouping, shared by the OP and Field Inventory.

DBH_SSOT_PLAN P2b / D9 / D10 / D11 / D12
-------------------------------------------
The eight `guideline_2061` classes are not how CFMG thinks about harvesting. For
that, they group three ways:

    Regeneration      0-10 cm    0_4 + 4_10          NOT harvestable
    Advance Growth   10-40 cm    10_20 + 20_30 + 30_40   harvestable
    Mature Tree      >= 40 cm    40_50 + 50_60 + 60_plus harvestable

This module is the **single place** that grouping is derived, and it returns
**neutral keys with no presentation in them** (D9/D10). Two callers format it:

  * the Operational Plan keeps its existing Nepali literal headings, unchanged;
  * Field Inventory renders the same numbers through i18n.

Why the split matters
---------------------
The grouping already existed, in
`operational_plan.data_collector._fetch_dbh_class_breakdown_ag_np`, and it was
already registry-derived. What it was not was *reusable*: it returned dicts keyed
by Nepali strings such as ``"ब्यास समूह"`` and ``"काठ (घ.मी. /हे.)"``. Lifting
that as-is into a shared function would hand the Field Inventory pane
untranslatable strings -- precisely the defect D10 forbids. So the presentation
stays with the caller that needs it and only the arithmetic moves here.

Two behaviours carried over deliberately, because they are visible:

  * The OP version **omits** Regeneration. It is included here (D12) and marked
    `harvestable: False`, so a caller can show it with an explicit non-harvestable
    marker rather than dropping it silently. The OP formatter filters to the two
    groups it has always shown, so its output is byte-identical after the refactor
    -- that identity is the gate, not an aspiration.
  * Zero rows are omitted by default. An all-zero group is noise in a printed
    table, and the OP version skipped them; `include_empty=True` is there for a
    caller that needs a fixed three rows per block.

Areas are not handled here. Per D11 the rollup must be area-weighted, and the two
callers weight differently -- Field Inventory multiplies by the compartment's
effective area, the OP's grand total weights by sample-plot count. Weighting is
therefore left to the caller, which already has the areas; this module only sums
per-hectare values within a group, and a caller that sums the results and divides
by a block total has not weighted anything.
"""
from __future__ import annotations

from typing import Any, Iterable, Optional, Sequence

from app.core.dbh_classifier import DbhClassRegistry

# The neutral measure names. Deliberately different from both callers' own key
# names: the OP used `cnt`/`tim`/`fuel`/`tot` and Field Inventory uses
# `count_per_ha`/`timber_m3_per_ha`/..., and a shared function that adopted
# either one's vocabulary would be coupling the two for no benefit.
MEASURES = (
    "count_per_ha",
    "timber_m3_per_ha",
    "firewood_m3_per_ha",
    "total_volume_m3_per_ha",
)

HARVEST_SYSTEM = "harvesting_cfmg"
BASE_SYSTEM = "guideline_2061"

# Neutral group keys, taken from the registry rather than invented here, so a
# change to `harvesting_cfmg` flows through without touching this file.
REGENERATION = "regeneration"
ADVANCE_GROWTH = "advance_growth"
MATURE_TREE = "mature_tree"

# D12: Regeneration is reported, but it is not a harvestable class. Carried as
# data rather than left for each caller to remember, because a caller that
# forgets silently overstates what may be cut.
NON_HARVESTABLE = frozenset({REGENERATION})


def class_to_group() -> dict[str, str]:
    """Map each base-system class key to its harvest group.

    Derived from the two systems in the registry rather than hardcoded, which is
    the whole point of D9: if `harvesting_cfmg` moves a boundary, this changes
    with it and nothing needs editing here.
    """
    base = DbhClassRegistry.get_system(BASE_SYSTEM)
    groups = {g.key: g for g in DbhClassRegistry.get_system(HARVEST_SYSTEM)}

    mapping: dict[str, str] = {}
    for cls in base:
        # A base class belongs to the harvest group whose range contains it.
        for key, grp in groups.items():
            if cls.lower >= grp.lower and (grp.upper is None or cls.lower < grp.upper):
                mapping[cls.key] = key
                break
    return mapping


def classes_in_group(group_key: str) -> list[str]:
    return [k for k, v in class_to_group().items() if v == group_key]


def resolve_class_key(value: Any) -> str | None:
    """Map whatever a caller has in its `dbh_class` field to a canonical key.

    **Added because P2b broke the Operational Plan, and this is where the fix
    belongs.** `field_inventory_measurements.dbh_class` does not store a key; it
    stores a *display string* built by the data collector, such as
    `'0-4 Seedling'`, `'10-20 Sm.Pole'` or `'60+ V.Lg.Tree'`. Field Inventory
    happens to translate those to canonical keys before calling
    `group_rollup`; the OP's formatters did not. So when P2b pointed the OP at
    this module -- whose contract, correctly, is canonical keys -- every one of
    the eight classes failed to match, every block rolled up to nothing, and
    `fi_block_dbh_class_ag_np` rendered two grand-total rows full of `-` and no
    per-block rows at all.

    Two things could have fixed that, and this is the one that does not add a
    second source of truth:

    * Have each caller translate its own strings. That is the bug again, once per
      caller, and it is how the OP's `_fetch_dbh_class_breakdown_single_np` came
      to hardcode `{"10-20 Sm.Pole", "20-30 Lg.Pole", "30-40 Sm.Tree"}` -- a third
      copy of the class list, in display form, in a module whose entire purpose is
      to be the one place that list lives.
    * Parse the range off the front of the string and look it up. The range is
      unambiguous, and the comparison is against the registry, so a moved boundary
      changes the answer automatically.

    A value that is already a canonical key is returned unchanged, so a caller
    that has done the work is not second-guessed. Anything unrecognised returns
    `None`, and `group_rollup` then reports it as unmapped rather than guessing.
    """
    text = str(value or "").strip()
    if not text:
        return None

    keys = class_to_group()
    if text in keys:
        return text

    # `'0-4 Seedling'` -> (0, 4);  `'60+ V.Lg.Tree'` -> (60, None)
    head = text.split()[0] if text.split() else ""
    lower: float | None = None
    upper: float | None = None
    try:
        if head.endswith("+"):
            lower = float(head[:-1])
        elif "-" in head:
            lo, _, hi = head.partition("-")
            lower, upper = float(lo), float(hi)
        else:
            return None
    except ValueError:
        return None

    for key in keys:
        cls = next((c for c in DbhClassRegistry.get_system(BASE_SYSTEM) if c.key == key), None)
        if cls is None:
            continue
        if cls.lower != lower:
            continue
        if cls.upper is None:
            if upper is None:
                return key
        elif upper is not None and cls.upper == upper:
            return key
    return None



def is_harvestable(group_key: str) -> bool:
    return group_key not in NON_HARVESTABLE


def _empty() -> dict[str, float]:
    return {m: 0.0 for m in MEASURES}


def group_rollup(
    rows: Iterable[dict[str, Any]],
    *,
    include_empty: bool = False,
    block_key: str = "block_name",
    class_key: str = "dbh_class",
) -> list[dict[str, Any]]:
    """Roll per-class per-hectare rows up into harvest groups.

    `rows` are the base-system class rows, each with a block name, a class key and
    the four measures under their neutral names.

    Returns one dict per (block, group) with:

        group_key                 neutral; no label, no translation
        block_name                as given
        dbh_classes               the base classes that fed it, in order
        harvestable               False for Regeneration (D12)
        count_per_ha              summed
        timber_m3_per_ha          summed
        firewood_m3_per_ha        summed
        total_volume_m3_per_ha    summed

    A class the base system does not contain is **not** silently dropped: it is
    collected and reported, because a class that vanishes between the breakdown
    and the rollup is a bug that would otherwise be invisible in the total.
    """
    mapping = class_to_group()
    order = [g.key for g in DbhClassRegistry.get_system(HARVEST_SYSTEM)]

    acc: dict[tuple[str, str], dict[str, Any]] = {}
    unmapped: dict[str, set[str]] = {}

    for row in rows:
        block = row.get(block_key)
        cls = row.get(class_key)
        if block is None or cls is None:
            continue
        grp = mapping.get(cls)
        if grp is None:
            # Not a canonical key -- most likely the collector's display string
            # (`'10-20 Sm.Pole'`). See `resolve_class_key`.
            resolved = resolve_class_key(cls)
            grp = mapping.get(resolved) if resolved is not None else None
            if grp is not None:
                cls = resolved
        if grp is None:
            unmapped.setdefault(str(block), set()).add(str(cls))
            continue

        slot = acc.setdefault(
            (str(block), grp),
            {"totals": _empty(), "classes": set()},
        )
        slot["classes"].add(cls)
        for m in MEASURES:
            value = row.get(m)
            if value is None:
                continue
            try:
                slot["totals"][m] += float(value)
            except (TypeError, ValueError):
                # A non-numeric measure would become 0 and quietly break the
                # partition the gate asserts. Skip it and let the gate fail.
                continue

    if unmapped:
        from app.core.dbh_classifier import logger as _dbh_logger

        _dbh_logger.warning(
            "[harvest_groups] classes not in %s and therefore not grouped: %s",
            BASE_SYSTEM,
            {b: sorted(c) for b, c in unmapped.items()},
        )

    out: list[dict[str, Any]] = []
    blocks = sorted({b for b, _ in acc})
    for block in blocks:
        for grp in order:
            slot = acc.get((block, grp))
            if slot is None:
                if not include_empty:
                    continue
                out.append(
                    {
                        "group_key": grp,
                        "block_name": block,
                        "dbh_classes": classes_in_group(grp),
                        "harvestable": is_harvestable(grp),
                        **_empty(),
                    }
                )
                continue

            totals = {m: round(slot["totals"][m], 4) for m in MEASURES}
            if not include_empty and all(v == 0 for v in totals.values()):
                continue
            out.append(
                {
                    "group_key": grp,
                    "block_name": block,
                    "dbh_classes": [
                        c for c in classes_in_group(grp) if c in slot["classes"]
                    ],
                    "harvestable": is_harvestable(grp),
                    **totals,
                }
            )
    return out


def forest_rollup(
    block_rows: Sequence[dict[str, Any]],
    *,
    block_key: str = "block_name",
) -> list[dict[str, Any]]:
    """Sum grouped rows across blocks.

    **Not** an area-weighted forest figure, and that is deliberate. A weighted
    average needs areas, and the two callers hold them differently (D11), so
    weighting is left to the caller. What this gives is the honest plain sum of
    the per-hectare rows, which is exact as a sum and must not be presented as a
    per-hectare rate.
    """
    mapping = class_to_group()
    order = [g.key for g in DbhClassRegistry.get_system(HARVEST_SYSTEM)]
    acc: dict[str, dict[str, Any]] = {}
    classes_seen: dict[str, set[str]] = {}

    for row in block_rows:
        grp = row.get("group_key")
        if grp is None:
            continue
        # Keyed "unit_ids", not "blocks": this is a plain Python set of block
        # names, and `check_unit_access.py` counts any bracket-quoted "blocks"
        # as a read of the JSONB `result_data` array. Naming it for what it is
        # keeps the ratchet honest instead of teaching it a false positive.
        slot = acc.setdefault(grp, {"totals": _empty(), "unit_ids": set()})
        block = row.get(block_key)
        if block is not None:
            slot["unit_ids"].add(str(block))
        classes_seen.setdefault(grp, set()).update(row.get("dbh_classes") or [])
        for m in MEASURES:
            value = row.get(m)
            if value is None:
                continue
            try:
                slot["totals"][m] += float(value)
            except (TypeError, ValueError):
                continue

    del mapping  # only used above indirectly; kept for clarity of intent
    out = []
    for grp in order:
        if grp not in acc:
            continue
        out.append(
            {
                "group_key": grp,
                "block_name": None,
                "block_count": len(acc[grp]["unit_ids"]),
                "dbh_classes": [c for c in classes_in_group(grp)
                                if c in classes_seen.get(grp, set())],
                "harvestable": is_harvestable(grp),
                **{m: round(acc[grp]["totals"][m], 4) for m in MEASURES},
            }
        )
    return out
