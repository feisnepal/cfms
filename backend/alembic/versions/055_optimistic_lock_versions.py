"""Per-record optimistic-lock version on the field-data domains.

Revision ID: 055_optimistic_lock_versions
Revises: 054_natural_keys
Create Date: 2026-08-26

Why this migration exists (H8.2 / S2-63)
----------------------------------------
Two enumerators surveying overlapping households, or one enumerator syncing
from two devices, currently produce a **silent last-write-wins overwrite** --
no detection, no warning, no audit entry attributing the loss. Field work is
exactly the workload where this happens routinely: devices are offline for
hours, work is divided by area rather than by record, and overlaps are normal.

The report frames this task as extending the `geometry_version` pattern from
geometry to the other three domains, on the grounds that geometry is
"correct, well-implemented work, and the only concurrency control of its kind".

**It is not concurrency control.** `calculations.geometry_version` is
incremented in twelve places and compared in **none**. No request schema
carries a version; there is no `If-Match`, no `expected_version`, no
precondition anywhere in the backend. The client half is inert too:
`reconcileVersion()` is called only from its own unit tests, and the
`stale_server` conflict modal keys off a state nothing ever sets. What exists
is a change counter, used as a cache key in `tree_clusters.py` and as a React
re-render key.

So the true position was not "one domain of four is protected". It was **none
of four**. This migration and `services/optimistic_lock.py` build the mechanism
for the first time, and `calculations` is wired into it alongside the three new
columns rather than being assumed to already work.

Why a dedicated column and not `updated_at`
-------------------------------------------
`household_information` and `sampling_designs` both carry `updated_at`, and a
timestamp precondition looks equivalent. It is not, for two reasons that bite
precisely in this workload:

* Timestamp resolution is finite. Two writes inside the same microsecond tick
  compare equal and the second is accepted -- rare on a desktop, much less rare
  when a device flushes a queued batch as fast as the connection allows.
* A clock is not monotonic across hosts. A counter incremented by the database
  cannot disagree with itself; two application servers with drifting clocks can.

`inventory_calculations` has no `updated_at` at all, so it would have needed a
column regardless.

The counter starts at 0 for existing rows, which is correct: no client holds a
version for them yet, and the first read hands one out.
"""

import sqlalchemy as sa
from alembic import op

revision = "055_optimistic_lock_versions"
down_revision = "054_natural_keys"
branch_labels = None
depends_on = None

# The unit a client edits and re-uploads, per domain. Household and sampling
# each have a PUT endpoint; inventory has none -- its edits are batch
# operations (accept-corrections, update-block-subarea, process) against the
# calculation, so that is the row a conflicting sync collides on.
VERSIONED_TABLES = (
    "household_information",
    "sampling_designs",
    "inventory_calculations",
)


def upgrade() -> None:
    for table in VERSIONED_TABLES:
        op.add_column(
            table,
            sa.Column(
                "version",
                sa.BigInteger(),
                nullable=False,
                server_default=sa.text("0"),
                comment=(
                    "H8.2/S2-63 optimistic-lock counter. Bumped only by "
                    "services/optimistic_lock.py, in the same statement that "
                    "checks it."
                ),
            ),
            schema="public",
        )


def downgrade() -> None:
    for table in VERSIONED_TABLES:
        op.drop_column(table, "version", schema="public")
