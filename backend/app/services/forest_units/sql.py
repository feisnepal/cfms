"""Raw-SQL predicates over ``forest_blocks``, so a ``text()`` query never hard-codes a depth (invariant I10).

Every function takes the table ALIAS used in the query and returns a fragment to drop into a WHERE clause.
"""

from __future__ import annotations

import re

from .model import DEPTH_SUB, Branch

_ALIAS = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _a(alias: str) -> str:
    if not _ALIAS.match(alias):
        raise ValueError(f"not a table alias: {alias!r}")
    return alias


def top_level(alias: str) -> str:
    """Units directly under the outer boundary (no parent unit)."""
    return f"{_a(alias)}.parent_block_id IS NULL"


def is_sub(alias: str) -> str:
    """Units that sit inside another unit."""
    return f"{_a(alias)}.parent_block_id IS NOT NULL"


def branch(alias: str, which: Branch) -> str:
    """Units of one branch (block / compartment)."""
    return f"{_a(alias)}.is_compartment IS {'TRUE' if which is Branch.COMPARTMENT else 'FALSE'}"


def depth_is(alias: str, depth: int) -> str:
    """Units at exactly ``depth`` (pass a constant from ``model``, never a literal)."""
    return f"{_a(alias)}.division_level = {int(depth)}"


def sub_depth(alias: str) -> str:
    """Units at the sub-unit depth."""
    return depth_is(alias, DEPTH_SUB)


def leaf(alias: str) -> str:
    """Units that are not divided further (no unit has this one as its parent)."""
    a = _a(alias)
    return (
        f"NOT EXISTS (SELECT 1 FROM forest_blocks _c WHERE _c.parent_block_id = {a}.id)"
    )


def deepest_first(alias: str) -> str:
    """ORDER BY fragment: among several units whose geometry contains a point,
    the one with the greatest depth is the innermost (leaf) match -- a
    sub-unit's geometry sits inside its parent's, so ordering deepest-first
    and taking the first row resolves "the leaf unit containing this point"
    without a branch/depth test in the caller (D10, FS-1d.3)."""
    return f"{_a(alias)}.division_level DESC"
