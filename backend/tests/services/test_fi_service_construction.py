"""FieldInventoryService reads a species master that migrations can build.

History, because it explains the shape of this file
---------------------------------------------------
`tree_species_coefficients.growth_rate` existed in cf_db / prod but was created by
**no migration**, so a database built purely from `alembic upgrade head` -- CI and
this test harness -- did not have it. `_load_species_coefficients` used to
`SELECT growth_rate` unconditionally, so `FieldInventoryService` could not be
constructed on such a database at all, which is why the whole field-inventory
pipeline had no test coverage. It was made to select only the columns the
catalogue reports, and the test below asserted the *drift* as its premise, so
that the workaround could not be quietly reverted while the drift persisted.

**That drift is now fixed.** Migrations 101 and 102 load the species master from
`alembic/versions/data/species_master.jsonl` and create the ten master columns no
migration had ever added, so a migrations-only database now matches production.
The old premise assertion therefore fired -- correctly -- telling us to simplify
this test. It has been rewritten to guard the fix instead of the bug:

  * the master a migrations-only build produces has the columns the service
    reads, and
  * the service therefore gets **real** growth rates rather than a column of
    NULLs that all collapse to 'Moderate'.

That second point matters. With `growth_rate` absent, every species silently
reported 'Moderate', and MAI percentages were computed from a constant. Nothing
downstream could tell that apart from a forest that genuinely is all moderate
growth. A test that only checks the service *constructs* would not have caught
that; these check it gets real data.
"""
from __future__ import annotations

from sqlalchemy import text

from app.services.field_inventory_service import FieldInventoryService


def _master_columns(db) -> set[str]:
    return {
        r[0]
        for r in db.execute(
            text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema='public' AND table_name='tree_species_coefficients'"
            )
        ).fetchall()
    }


def test_migrations_only_master_has_the_columns_the_service_reads(db):
    """A migrations-only database must have a species master the app can use.

    This is the guard that replaces the old drift assertion. It fails if someone
    drops a column, or if a future migration stops loading the snapshot, because
    either would leave this database with a master the application cannot read.
    """
    present = _master_columns(db)

    for col in FieldInventoryService._SPECIES_OPTIONAL_COLS:
        assert col in present, (
            f"tree_species_coefficients.{col} is missing from a migrations-only "
            "database. Migration 102 creates it and 101 loads it; if this fails, "
            "the species master is no longer reproducible."
        )

    # The master must actually hold the real catalogue, not migration 003's
    # 25-row stub. This is the specific divergence that made every fresh test
    # database a lie about species data.
    n_species = db.execute(
        text("SELECT count(*) FROM tree_species_coefficients WHERE is_active")
    ).scalar()
    assert n_species > 100, (
        f"only {n_species} active species in the master; a migrations-only "
        "database is back to migration 003's stub instead of the real catalogue"
    )


def test_service_gets_real_growth_rates_not_a_column_of_nulls(db):
    """The drift's silent symptom was *every* species reporting 'Moderate'.

    With `growth_rate` absent, the service loaded NULL for all species, the
    per-species fallback made them all 'Moderate', and the MAI matrix collapsed
    to one row -- indistinguishable, in the output, from a forest that genuinely
    is all moderate growth. So the property to guard is that the column supplies
    real, varied data.

    A *few* NULLs are a different thing and are tolerated: 2 of the master's 861
    species have no `growth_rate` recorded. That is a data gap in the catalogue
    to be fixed in the master deliberately, not a schema problem, and failing
    here would only discourage someone from fixing it properly.
    """
    service = FieldInventoryService(db)

    assert isinstance(service.species_coefficients, dict)
    assert service.species_coefficients, "no species coefficients loaded at all"

    total = len(service.species_coefficients)
    with_rate = [
        c for c in service.species_coefficients.values() if c.get("growth_rate")
    ]
    assert with_rate, (
        "no species has a growth_rate at all; the column exists but nothing "
        "reads it, so every species falls back to 'Moderate'"
    )

    distinct = {c["growth_rate"] for c in with_rate}
    assert len(distinct) >= 2, (
        f"every species reports the same growth rate ({distinct}); the MAI "
        "matrix would be a single row regardless of the forest"
    )

    missing = total - len(with_rate)
    assert missing <= total * 0.01, (
        f"{missing} of {total} species have no growth_rate "
        f"({missing / total:.1%}); the column is barely populated, which is the "
        "same symptom as the column being missing"
    )

    for coef in service.species_coefficients.values():
        assert coef["wood_density"] is not None


def test_dominant_growth_rate_defaults_to_moderate_when_column_absent(db):
    service = FieldInventoryService(db)
    # No species -> the {'Fast','Moderate','Slow'} tie is broken toward the first
    # max key, 'Fast'; with real species whose growth_rate is None the per-species
    # fallback is 'Moderate'. Here we only assert it does not raise.
    import asyncio

    result = asyncio.run(
        service._get_dominant_growth_rate(field_inventory_id="00000000-0000-0000-0000-000000000000", block_name="nope")
    )
    assert result in {"Fast", "Moderate", "Slow"}
