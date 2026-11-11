"""Does the field inventory still match the forest's units?  (read-only)

The inventory is built per UNDIVIDED unit (the leaf view): sampling lays plots in them, the summary has one row each, and
every map and OP table reads those rows. Anything that changes the units afterwards - dividing one, deleting one, moving a
boundary - can leave the inventory describing units that are no longer there. बृन्दाबन ended up with 103 plots inside units
that lay outside its boundary and nothing said so; the only signal was a generic "re-run needed" banner.

``check`` names each such problem. It never changes anything and never computes the inventory: it compares what is stored.

  errors    the stored inventory cannot be trusted for this unit
    SUMMARY_UNIT_MISSING        a summary row names a unit the forest does not have
    SUMMARY_UNIT_DIVIDED        a summary row sits on a unit that has since been divided (its plots are now in the children)
    PLOT_UNIT_MISSING           a plot names a unit the forest does not have
    PLOT_IN_DIVIDED_UNIT        a plot is assigned to a unit that has since been divided
    PLOT_OUTSIDE_UNIT           a plot lies outside the unit it is assigned to
    PLOT_COUNT_MISMATCH         a summary's plot count differs from the number of plots stored for that unit
  warnings  the inventory is incomplete, not wrong
    UNIT_WITHOUT_PLOTS          an undivided unit has no plot (it will have no summary and shows as "no data" on the maps)

Plot position is compared with the unit's polygon with a small tolerance (``EDGE_TOL_DEG``, about 5 m): a plot laid on the
edge between two units belongs to both.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, List

from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

EDGE_TOL_DEG = 0.00005  # ~5 m

SUMMARY_UNIT_MISSING = "SUMMARY_UNIT_MISSING"
SUMMARY_UNIT_DIVIDED = "SUMMARY_UNIT_DIVIDED"
PLOT_UNIT_MISSING = "PLOT_UNIT_MISSING"
PLOT_IN_DIVIDED_UNIT = "PLOT_IN_DIVIDED_UNIT"
PLOT_OUTSIDE_UNIT = "PLOT_OUTSIDE_UNIT"
PLOT_COUNT_MISMATCH = "PLOT_COUNT_MISMATCH"
UNIT_WITHOUT_PLOTS = "UNIT_WITHOUT_PLOTS"

ERROR, WARNING = "error", "warning"


@dataclass(frozen=True)
class Finding:
    code: str
    severity: str
    unit: str
    message: str
    count: int = 0

    def as_dict(self) -> dict:
        return {"code": self.code, "severity": self.severity, "unit": self.unit, "message": self.message, "count": self.count}


_PLOTS_BY_UNIT = text(
    """
    SELECT p.block_name AS name, count(*) AS plots,
           count(*) FILTER (WHERE b.id IS NOT NULL AND b.geometry IS NOT NULL AND p.location IS NOT NULL
                            AND NOT ST_DWithin(p.location::geometry, b.geometry, :tol)) AS outside
    FROM field_inventory_sample_plots p
    JOIN field_inventory_calculations f ON f.id = p.field_inventory_calculation_id
    LEFT JOIN forest_blocks b ON b.calculation_id = f.calculation_id AND b.block_name = p.block_name
    WHERE f.calculation_id = :cid
    GROUP BY p.block_name
    """
)

_SUMMARIES = text(
    """
    SELECT s.block_name AS name, s.total_sample_plots AS plots, COALESCE(s.protected_sample_plots, 0) AS protected
    FROM field_inventory_block_summary s
    JOIN field_inventory_calculations f ON f.id = s.field_inventory_calculation_id
    WHERE f.calculation_id = :cid
    """
)


def check(db: Session, calculation_id: Any) -> List[Finding]:
    """Every inconsistency between the stored inventory and the forest's current units. Read-only; ``[]`` when there is no
    inventory at all (nothing to be inconsistent)."""
    cid = str(calculation_id)
    plots = {r.name: r for r in db.execute(_PLOTS_BY_UNIT, {"cid": cid, "tol": EDGE_TOL_DEG})}
    summaries = {r.name: r for r in db.execute(_SUMMARIES, {"cid": cid})}
    if not plots and not summaries:
        return []

    from app.services.forest_units.hierarchy import unit_hierarchy

    units = {u["name"]: u for u in unit_hierarchy(db, calculation_id) if u["name"]}
    out: List[Finding] = []

    for name, s in sorted(summaries.items()):
        u = units.get(name)
        if u is None:
            out.append(Finding(SUMMARY_UNIT_MISSING, ERROR, name, f"the inventory summary names {name}, which the forest does not have"))
        elif u["kids"]:
            out.append(Finding(SUMMARY_UNIT_DIVIDED, ERROR, name, f"{name} has been divided since its inventory was made; its plots now belong to its sub-units"))
        have = plots.get(name).plots if name in plots else 0
        # a summary counts its productive plots; the protection stratum is counted beside them, so either total is a match
        if u is not None and not u["kids"] and int(have) not in (int(s.plots or 0), int(s.plots or 0) + int(s.protected or 0)):
            out.append(Finding(PLOT_COUNT_MISMATCH, ERROR, name,
                               f"{name}: the summary counts {s.plots} plot(s) but {have} are stored", int(have)))

    for name, p in sorted(plots.items()):
        u = units.get(name)
        if u is None:
            out.append(Finding(PLOT_UNIT_MISSING, ERROR, name, f"{p.plots} plot(s) are assigned to {name}, which the forest does not have", int(p.plots)))
            continue
        if u["kids"]:
            out.append(Finding(PLOT_IN_DIVIDED_UNIT, ERROR, name, f"{p.plots} plot(s) are still assigned to {name}, which has been divided", int(p.plots)))
        if p.outside:
            out.append(Finding(PLOT_OUTSIDE_UNIT, ERROR, name, f"{p.outside} of {p.plots} plot(s) of {name} lie outside it", int(p.outside)))

    for name, u in sorted(units.items()):
        if not u["kids"] and name not in plots:
            out.append(Finding(UNIT_WITHOUT_PLOTS, WARNING, name, f"{name} has no sample plot"))
    return out


def has_errors(findings: List[Finding]) -> bool:
    return any(f.severity == ERROR for f in findings)
