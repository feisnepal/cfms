"""What deleting a forest must leave behind — the rule and its documented exceptions.

Owner's rule, 2026-09-21 (replaces the 2026-08-27 "archive, never destroy" rule):

    If a forest is deleted, ALL data associated with it is deleted.

That means every table that links to a forest must ``ON DELETE CASCADE`` (directly, or
through a parent that does), every per-forest file and cache folder is removed, and there
is no archive. Migration 092 brought the last four tables in line
(`inventory_calculations`, `field_inventory_calculations`, `transactions`, `op_data_cache`).

The two tables below carry a forest id **on purpose** and are the only exceptions. They are
listed with their reason so that ``tests/test_forest_delete_schema_rule.py`` and
``scripts/report_orphans.py`` can tell a documented exception from a leak. Do not add a table
here to make a test pass — a new exception is an owner decision.
"""

from __future__ import annotations

# table -> why its rows are allowed to outlive the forest
FOREST_DELETE_EXCEPTIONS: dict[str, str] = {
    "document_issuances": (
        "Append-only provenance record of every issued document (SHA-256 + verification "
        "endpoint, migration 059). A database RULE blocks UPDATE; deleting the row would make "
        "an already-issued document unverifiable."
    ),
    "household_access_log": (
        "Audit log of who read household (personal) data. An audit trail that vanishes with "
        "the thing it audits is not an audit trail."
    ),
    "document_submissions": (
        "Append-only record that a statutory document was submitted to a receiving office, "
        "including that office's own file reference (migration 097). Same posture as "
        "document_issuances: a RULE blocks UPDATE and DELETE, and deleting the row would "
        "destroy the only evidence that the plan was ever handed over."
    ),
}
