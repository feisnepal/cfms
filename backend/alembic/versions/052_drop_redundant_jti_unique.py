"""Drop the redundant UNIQUE constraint on refresh_tokens.jti.

Revision ID: 052_drop_redundant_jti_unique
Revises: 051_app_tables_to_public
Create Date: 2026-08-25

Why this migration exists (found by G-DB-3, the first time it ever ran)
----------------------------------------------------------------------
Migration ``050_refresh_token_rotation`` enforced ``jti`` uniqueness twice::

    sa.Column("jti", sa.String(64), nullable=False, unique=True)   # -> refresh_tokens_jti_key
    op.create_index("ix_refresh_tokens_jti", ..., unique=True)     # -> ix_refresh_tokens_jti

``unique=True`` on a column creates a UNIQUE CONSTRAINT, which PostgreSQL backs
with its own index. The explicit ``create_index(..., unique=True)`` then builds
a second unique index over the same column. Both are maintained on every
insert, and every refresh rotates a token, so this is on the hot path of the
one operation the table exists to serve.

The model declares ``unique=True, index=True``, which SQLAlchemy renders as a
single unique INDEX. So the constraint is not merely redundant, it is drift:
``alembic check`` reports it as a constraint that should be removed, and anyone
running ``--autogenerate`` would get a migration dropping it.

How it went unnoticed
---------------------
The ``alembic-check`` CI job that would have caught this had never executed. It
declares ``needs: test-backend``, test-backend was red, and a skipped job reads
as absence rather than failure. The job was fixed on 2026-08-25 and reported
this on its first real run -- the drift baseline was recorded during Phase 1,
before migration 050 existed, so this is genuinely new since then.

Safety
------
Dropping the constraint does NOT weaken the guarantee. ``ix_refresh_tokens_jti``
is itself UNIQUE and remains, so a replayed ``jti`` still collides -- which is
what H2.5's reuse detection depends on to recognise a spent token as theft.
The constraint's backing index goes with it; the deliberate one stays.

``IF EXISTS`` because the constraint name is PostgreSQL's default and a
database built by a different route may not carry it. Note 051 moved this table
from ``rasters`` to ``public``; the constraint travelled with it.

The two siblings -- read this before "tidying" them
---------------------------------------------------
A scan of every migration found three tables declaring a column ``unique=True``
*and* creating a unique index on the same column. Only this one is fixed here,
and the reason is worth recording, because the obvious next step is wrong:

``translations.key`` (045) is the same genuine duplicate -- ``ix_translations_key``
and ``translations_key_key`` both exist in ``cf_db``. It is safe to drop the same
way. It is not fixed here only because it predates the Phase 1 drift baseline,
so it is already absorbed there and does not block CI. Fixing it shrinks the
baseline, which is the direction the baseline is supposed to move.

``tree_species_coefficients.scientific_name`` (002) **must NOT be touched.** The
migration source has the same shape, but the live database has NO separate
``ix_...scientific_name`` index -- only ``tree_species_coefficients_scientific_name_key``,
which is the constraint's own backing index. There the constraint is the sole
enforcement of uniqueness, and dropping it would silently remove a guarantee on
the species reference table that volume and biomass figures are computed from.
Static analysis of the migrations says otherwise; the database is the authority.
"""
from alembic import op

revision = "052_drop_redundant_jti_unique"
down_revision = "051_app_tables_to_public"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE public.refresh_tokens "
        "DROP CONSTRAINT IF EXISTS refresh_tokens_jti_key"
    )


def downgrade() -> None:
    # Recreating it restores the duplicate, which is the point of a downgrade:
    # it returns the schema to what 051 left behind, warts included.
    op.execute(
        "ALTER TABLE public.refresh_tokens "
        "ADD CONSTRAINT refresh_tokens_jti_key UNIQUE (jti)"
    )
