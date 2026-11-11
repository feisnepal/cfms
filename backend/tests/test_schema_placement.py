"""S1-74 — migrations create tables where the chain says, not where the
database's search_path happens to point.

`cf_db` carries a database-level `search_path = rasters, public, sde` for its
GIS layers, and an unqualified `op.create_table` lands in the first entry. Six
application tables were created inside the raster schema over several months —
including `refresh_tokens` from H2.5 and `dbh_classification_changes`, the
audit trail H2.3 added so DBH-class edits stop being untraceable.

Nothing broke at runtime, because `public` is second in the path and every read
resolves. That is the whole problem: a clean server builds the same revision
with all six in `public`, so two databases report identical versions from
`alembic current` while having structurally different schemas, and no drift
check can see it — the models are unqualified (H1.14) and match whichever
schema resolves first.
"""
import importlib.util
import pathlib

import pytest
import sqlalchemy as sa

BACKEND = pathlib.Path(__file__).resolve().parent.parent
VERSIONS = BACKEND / "alembic" / "versions"


def _load(name: str):
    """Import a migration module by filename (they are not a package)."""
    path = VERSIONS / name
    spec = importlib.util.spec_from_file_location(path.stem, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


mig051 = _load("051_move_app_tables_to_public.py")


class TestTheDecision:
    def test_a_table_only_in_rasters_is_moved(self):
        assert mig051.decide("translations", {"rasters"}) is True

    def test_a_table_already_in_public_is_left_alone(self):
        """The no-op case, which is what a clean build hits."""
        assert mig051.decide("translations", {"public"}) is False

    def test_a_table_in_neither_is_left_alone(self):
        assert mig051.decide("translations", set()) is False

    def test_two_copies_refuses_rather_than_guessing(self):
        """The case that must never pass silently.

        With a copy in each schema, which one is live depends on the
        search_path of whoever wrote last. Moving either way can discard real
        rows, so the migration stops and says what to compare.
        """
        with pytest.raises(RuntimeError) as exc:
            mig051.decide("translations", {"public", "rasters"})
        assert "BOTH" in str(exc.value)
        assert "will not guess" in str(exc.value)

    def test_every_known_misplaced_table_is_listed(self):
        """The six found in cf_db on 2026-08-21. A shorter list means one was
        dropped from the repair; a longer one means a new finding to record."""
        assert set(mig051.MISPLACED) == {
            "translations",
            "workspace_layers",
            "dbh_class_systems",
            "digitize_audit_logs",
            "dbh_classification_changes",
            "refresh_tokens",
        }

    def test_downgrade_is_deliberately_empty(self):
        """Reversing the move would recreate the defect on a clean database."""
        assert mig051.downgrade() is None


class TestTheEnvPin:
    def test_env_pins_the_search_path_for_migrations(self):
        """Without this line the whole repair is temporary — the next
        `create_table` on cf_db lands in `rasters` again."""
        env = (BACKEND / "alembic" / "env.py").read_text(encoding="utf-8")
        assert 'MIGRATION_SEARCH_PATH = "public"' in env
        assert "-csearch_path={MIGRATION_SEARCH_PATH}" in env
        # And NOT by executing SET on the connection: that opens an implicit
        # transaction Alembic does not own, so `command.upgrade` closes the
        # connection and rolls the whole run back — silently, exit code 0.
        assert 'execute(sa.text(f"SET search_path' not in env

    def test_alembic_version_lives_in_public(self, db):
        """The pin is only safe because of this.

        If `alembic_version` were in `rasters`, pinning the path to `public`
        would make Alembic read an empty version table, conclude the database
        is at base, and attempt to replay the entire chain over live data.
        """
        found = db.execute(sa.text(
            "SELECT n.nspname FROM pg_class c "
            "JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE c.relname = 'alembic_version'"
        )).scalars().all()
        assert found, "alembic_version not found at all"
        assert set(found) == {"public"}


class TestTheChain:
    def test_single_head(self):
        """Exactly one head -- the property, not today's revision id.

        This asserted `heads == ["051_app_tables_to_public"]`, which pins the
        name of whatever migration happened to be last when it was written. The
        thing worth protecting is that the chain does not FORK: multiple heads
        mean `alembic upgrade head` is ambiguous and two developers' migrations
        silently diverge, which this repository has already lived through --
        `4c5dc19e96e5` is a "Merge all migration heads" revision cleaning up six
        of them.

        Pinning the id caught nothing that this does not, and cost a red build
        on the next migration (052), whose only crime was existing.
        """
        from alembic.config import Config
        from alembic.script import ScriptDirectory

        script = ScriptDirectory.from_config(Config(str(BACKEND / "alembic.ini")))
        heads = list(script.get_heads())
        assert len(heads) == 1, (
            f"The migration chain has forked into {len(heads)} heads: {heads}. "
            "`alembic upgrade head` is ambiguous until they are merged."
        )


class TestTheTestDatabaseItself:
    def test_application_tables_are_in_public(self, db):
        """The test database is built by Alembic (H1.6), so it is the honest
        check that the chain now produces the intended layout."""
        misplaced = db.execute(sa.text(
            "SELECT n.nspname || '.' || c.relname "
            "FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE c.relkind = 'r' AND n.nspname <> 'public' "
            "  AND c.relname = ANY(:names)"
        ), {"names": list(mig051.MISPLACED)}).scalars().all()
        assert misplaced == [], f"built outside public: {misplaced}"
