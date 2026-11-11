"""The one place that knows what the units of a forest are (FOREST_STRUCTURE_IMPLEMENTATION_PLAN.md, §3.1).

A forest is a boundary with, below it, EITHER blocks (with optional sub-blocks) OR compartments (with optional
sub-compartments) - never both (the structure rule). A forest may also be ONE block or ONE compartment that
covers the whole forest area; that is an ordinary unit, not a special case. Six subsystems used to decide "which
units does this forest have" six different ways; every reader now asks this package.

    from app.services.forest_units import queries, mode, sql
    queries.units(db, calc_id, queries.View.LEAF)   # the units that are not divided further
    mode.forest_stream(db, calc_id)                 # Stream.BLOCK / COMPARTMENT / UNDECIDED
    sql.top_level("b")                              # a raw-SQL predicate, so no caller hard-codes a depth

Only this package (and the ORM model that defines the columns) may test a unit's level, branch or parent;
``backend/scripts/check_unit_access.py`` enforces it.
"""
