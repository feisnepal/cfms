"""Regulation species grouping: codes 1-21 named, 22 Terai spp, 23 Hill spp.

The Forest Regulation lists 21 designated species (codes 1-21, SSOT
``prime_species.PRIME_SPECIES``). Every other recorded species is reported as
"Other species" under 22 (Terai spp) or 23 (Hill spp), by where the forest lies.

Region rule: the forest's dominant LRMP physiography zone. The lowland set is the
one ``zone_classifier`` already uses for LOWLAND_SAL, so there is one definition
of "Terai"; an unknown zone defaults to Hill (the same safe default the species
code validator uses).

Like ``species_policy`` nothing is stored: the group is computed on the way out
from rows that are already built, and the groups are summed from those very rows,
so the buckets add up to the total by construction.
"""
from __future__ import annotations

from typing import Any, Optional, Sequence

from app.core.prime_species import PRIME_SPECIES, prime_species_code
from app.core.species_policy import NAME_KEY, _sum_measure
from app.services.sustainable_fm.zone_classifier import _LOWLAND

TERAI_CODE = 22
HILL_CODE = 23
TERAI_NAME = "Terai spp"
HILL_NAME = "Hill spp"

TERAI = "terai"
HILL = "hill"


def region_for_zone(physiography_zone: Optional[str]) -> str:
    """'terai' for a lowland LRMP zone, else 'hill' (also when unknown)."""
    return TERAI if physiography_zone in _LOWLAND else HILL


def region_for_field_inventory(db: Any, field_inventory_id: Any) -> str:
    """The forest's region from its dominant physiography zone (largest overlap).

    Unknown (no boundary, no admin.physiography table) answers 'hill'.
    """
    from sqlalchemy import text

    try:
        with db.begin_nested():
            zone = db.execute(
                text(
                    'SELECT p."physiography Zone" '
                    "FROM admin.physiography p, public.calculations c, "
                    "     public.field_inventory_calculations f "
                    "WHERE f.id = :fid AND c.id = f.calculation_id "
                    "  AND ST_Intersects(p.geom, c.boundary_geom) "
                    "ORDER BY ST_Area(ST_Intersection(p.geom, c.boundary_geom)) DESC "
                    "LIMIT 1"
                ),
                {"fid": str(field_inventory_id)},
            ).scalar()
    except Exception:  # noqa: BLE001 -- table missing / DB hiccup: hill default
        zone = None
    return region_for_zone(zone)


def other_code(region: str) -> int:
    return TERAI_CODE if region == TERAI else HILL_CODE


def regulation_code(species: Optional[str], region: str) -> int:
    """1..21 for a designated species, else 22 (Terai) / 23 (Hill)."""
    return prime_species_code(species) or other_code(region)


def regulation_buckets(region: str) -> list[tuple[int, str]]:
    """The 22 reportable buckets for a forest: 1..21 plus its one 'other' bucket."""
    other = (other_code(region), TERAI_NAME if region == TERAI else HILL_NAME)
    return [(s.code, s.name) for s in PRIME_SPECIES] + [other]


def annotate_regulation_rows(
    rows: Sequence[dict], region: str, *, name_key: str = NAME_KEY
) -> list[dict]:
    """Stamp `regulation_code` / `regulation_name` onto each row, in place."""
    names = {s.code: s.name for s in PRIME_SPECIES}
    names[TERAI_CODE], names[HILL_CODE] = TERAI_NAME, HILL_NAME
    for row in rows:
        code = regulation_code(row.get(name_key), region)
        row["regulation_code"] = code
        row["regulation_name"] = names[code]
    return list(rows)


def build_regulation_groups(
    rows: Sequence[dict],
    measure_keys: Sequence[str],
    region: str,
    *,
    name_key: str = NAME_KEY,
    include_empty: bool = False,
    include_other: bool = True,
) -> dict[str, Any]:
    """Roll annotated rows up into one entry per regulation code.

    Rows are annotated here if they are not already. `species` lists the recorded
    species that fell into the bucket, so "Other species" stays auditable.
    `partition_holds` is reported, not assumed. `include_other=False` shows only the
    classified species (codes 1-21); `total` is then the classified total.
    """
    rows = annotate_regulation_rows(rows, region, name_key=name_key)
    if not include_other:
        rows = [r for r in rows if r["regulation_code"] not in (TERAI_CODE, HILL_CODE)]
    groups: list[dict[str, Any]] = []
    for code, name in regulation_buckets(region):
        subset = [r for r in rows if r["regulation_code"] == code]
        if not subset and not include_empty:
            continue
        seen: list[str] = []
        for r in subset:
            n = str(r.get(name_key) or "")
            if n not in seen:
                seen.append(n)
        entry: dict[str, Any] = {
            "code": code,
            "name": name,
            "is_other": code in (TERAI_CODE, HILL_CODE),
            "species_count": len(seen),
            "species": seen,
        }
        for key in measure_keys:
            entry[key] = round(_sum_measure(subset, key), 4)
        groups.append(entry)

    total = {k: _sum_measure(rows, k) for k in measure_keys}
    holds = all(
        abs(sum(g[k] for g in groups) - total[k]) <= 1e-6 * max(abs(total[k]), 1.0)
        for k in measure_keys
    )
    return {
        "region": region,
        "groups": groups,
        "total": {k: round(v, 4) for k, v in total.items()},
        "partition_holds": holds,
    }
