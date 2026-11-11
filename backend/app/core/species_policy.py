"""Group recorded species by the policy list, at read time.

POLICY_SPECIES_PLAN P2 / D3
---------------------------
P1 built the list and the rule. This module is where the rule meets the numbers:
it stamps each already-computed species row with a classification and rolls the
rows up into the two reporting groups.

Nothing is stored (D3)
~~~~~~~~~~~~~~~~~~~~~~
Membership is a pure function of the list, so it is computed here, on the way
out. No measurement, tree or breakdown row gains an `is_reference` column, because
a stored boolean would have to be written by every ingestion path that can create
a measurement -- and it would freeze *today's* policy into historical rows, so a
list revised next year would leave last year's rows still reporting the old
answer.

The partition is exact by construction
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
The group totals are summed from the very rows that go into the response, not
from a second query. That is the whole design. If the rollup re-read the database
and re-derived the extrapolation, the two paths would round independently and the
groups would fail to add up to the grand total by a few hundredths -- and a
report whose parts do not sum to its whole is a report nobody can trust, in a
place (a farmer's allowable cut) where being slightly wrong is worse than being
honestly uncertain.

So: annotate the rows, sum the rows, and `reference + other == total` holds
identically for every measure. `partition_holds` is still reported, so a caller
can assert it rather than assume it -- an invariant that is only ever checked in
a test is an invariant that decays.

`matched_by` is carried alongside `classification`
--------------------------------------------------
A genus-level list entry captures several recorded species, and a reader looking
at *Albizia chinensis* in the in-list group deserves to know it got there via
"Albizia spp" rather than by being named outright. Without that column the
genus rule is invisible, and an invisible rule is one nobody can audit.
"""
from __future__ import annotations

import logging
from typing import Any, Iterable, Sequence

from app.core.policy_species_registry import OTHER, REFERENCE, PolicySpeciesRegistry

logger = logging.getLogger(__name__)

NAME_KEY = "species_scientific"


def annotate_species_rows(
    rows: Sequence[dict],
    *,
    name_key: str = NAME_KEY,
) -> list[dict]:
    """Stamp `classification` and `matched_by` onto each row, in place.

    In place because these rows are already built and are about to be serialised;
    copying them would double a list that can hold thousands of entries for no
    benefit. Returns the same list for chaining.

    An unrecognisable name (blank, or a free-text string) classifies as `other`
    rather than being dropped or guessed at. A species the list does not name is
    exactly what the Other group is for, and inventing a match would be worse
    than admitting the list does not cover it.
    """
    if not rows:
        return list(rows)

    names = [str(r.get(name_key) or "") for r in rows]
    groups = PolicySpeciesRegistry.classify_many(names)

    for row, raw in zip(rows, names):
        row["classification"] = groups.get(raw, OTHER)
        entry = PolicySpeciesRegistry.match_reason(raw) if raw else None
        row["matched_by"] = entry.scientific_name if entry else None
        # A genus-level hit is worth distinguishing from a named one, because
        # that is the part of the rule a reader is most likely to dispute.
        row["matched_by_level"] = entry.match_level if entry else None
    return list(rows)


def _sum_measure(rows: Iterable[dict], key: str) -> float:
    total = 0.0
    for r in rows:
        value = r.get(key)
        if value is None:
            continue
        try:
            total += float(value)
        except (TypeError, ValueError):
            # A non-numeric measure in a species row would silently become zero
            # and quietly break the partition. Say so instead.
            logger.warning(
                "[species_policy] non-numeric %s=%r on a species row; counted as 0",
                key,
                value,
            )
    return total


def _group_block(
    rows: Sequence[dict],
    measure_keys: Sequence[str],
    *,
    name_key: str = NAME_KEY,
) -> dict:
    ref_rows = [r for r in rows if r.get("classification") == REFERENCE]
    oth_rows = [r for r in rows if r.get("classification") == OTHER]

    def distinct_species(subset: Sequence[dict]) -> list[str]:
        """Distinct species names, in first-seen order.

        Distinct, because these breakdowns are keyed by species *and DBH class*:
        `species_dbh_forest_wide` has one row per species per class, so a naive
        row count reports 51 reference "species" for a forest with 7. That is the
        kind of wrong that reads as plausible -- a headline count nobody would
        think to check -- and it is the number a policy reader looks at first.
        Order is first-seen rather than sorted so the list follows the data.
        """
        seen: list[str] = []
        for r in subset:
            name = str(r.get(name_key) or "")
            if name not in seen:
                seen.append(name)
        return seen

    def summarise(subset: Sequence[dict]) -> dict:
        names = distinct_species(subset)
        out: dict[str, Any] = {
            "species_count": len(names),
            "species": names,
            # Rows are not species, and the two differ. Published so a reader of
            # the payload can see why the two numbers are not equal, rather than
            # assuming one of them is wrong.
            "row_count": len(subset),
        }
        for key in measure_keys:
            out[key] = round(_sum_measure(subset, key), 4)
        return out

    reference = summarise(ref_rows)
    other = summarise(oth_rows)
    total = summarise(list(rows))

    # The invariant. Compared with a tolerance because these are floats summed in
    # a different order in each bucket; exact equality would be a false promise.
    holds = True
    detail = {}
    for key in measure_keys:
        parts = reference.get(key, 0.0) + other.get(key, 0.0)
        whole = total.get(key, 0.0)
        gap = abs(parts - whole)
        scale = max(abs(whole), 1.0)
        detail[key] = {"reference": parts, "total": whole, "gap": round(gap, 9)}
        if gap / scale > 1e-6:
            holds = False

    # Every species must appear in exactly one group, and the two groups' species
    # must be the same set as the rows'. Compared as *sets* on distinct names,
    # because a species split across several DBH-class rows would otherwise look
    # like a duplicate and trip a row-count comparison.
    ref_names = set(reference["species"])
    oth_names = set(other["species"])
    if ref_names & oth_names:
        # A species cannot be in both groups; that would double-count it.
        holds = False
    if ref_names | oth_names != set(total["species"]):
        holds = False

    return {
        "reference": reference,
        "other": other,
        "total": total,
        "partition_holds": holds,
        "partition_detail": detail,
    }


def build_policy_groups(
    rows: Sequence[dict],
    measure_keys: Sequence[str],
    *,
    name_key: str = NAME_KEY,
    group_by: str | None = None,
    blocks: Sequence[str] | None = None,
) -> dict:
    """Roll annotated species rows up into the two reporting groups.

    `group_by` produces a rollup per distinct value of that column -- used with
    `"block_name"` for the per-compartment view the tracker requires. Every
    group seen in the rows gets an entry, including ones where every species
    happens to be in the same group, so a compartment with no "Other species" is
    visibly empty rather than missing.
    """
    if group_by is None:
        return _group_block(rows, measure_keys, name_key=name_key)

    keys: list[str] = []
    if blocks is not None:
        keys.extend(blocks)
    for r in rows:
        value = r.get(group_by)
        key = str(value) if value is not None else None
        if key is not None and key not in keys:
            keys.append(key)

    per_block: dict[str, Any] = {}
    for key in keys:
        subset = [r for r in rows if str(r.get(group_by)) == key]
        if not subset:
            # Keep the compartment visible with an honest zero rather than
            # omitting it: a reader comparing compartments needs them all there.
            empty = _group_block([], measure_keys, name_key=name_key)
            empty["present_in_response"] = False
            per_block[key] = empty
            continue
        result = _group_block(subset, measure_keys, name_key=name_key)
        result["present_in_response"] = True
        per_block[key] = result

    return {
        "per_block": per_block,
        "forest": _group_block(rows, measure_keys, name_key=name_key),
    }


# The measures each breakdown actually carries, named once so a rename cannot
# leave a rollup silently summing a key that no longer exists.
ABSOLUTE_MEASURES = ("count", "timber_m3", "fuelwood_m3", "volume_m3")
PER_HA_MEASURES = (
    "count_per_ha",
    "timber_m3_per_ha",
    "fuelwood_m3_per_ha",
    "volume_m3_per_ha",
)
