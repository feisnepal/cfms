"""Refuse to call a partial calculation `completed` (H3.5 · S2-37).

The report names this the most insidious defect category in the codebase, and
the reason is worth restating: in a geospatial pipeline a swallowed exception
does not produce an error, it produces **a plausible-looking wrong number**. A
failed CRS transform, a failed area computation or a failed species match that
is caught and ignored yields an operational plan with incorrect figures and
nothing anywhere saying so. That document has regulatory standing.

`analysis.py:313` catches a per-block failure, logs it, and continues to the
next block with `{**block, "analysis_error": ...}`. **That resilience is
deliberate and stays** — its comment says so, and one bad block should not
discard the other forty-nine. The defect is not that analysis continues; it is
that the pipeline afterwards reports `completed` regardless, so the partial
result is indistinguishable from a whole one.

So this module does not change how analysis handles failure. It asks a single
question at the end — *did anything fail?* — and the runner refuses to write
`completed` when the answer is yes.

**Partial results are still saved.** The status becomes `failed` with a reason
naming what broke, and `result_data` keeps everything that did work, because
somebody has to be able to see which blocks failed and why. What they must not
be able to do is mistake it for a finished calculation.
"""
from __future__ import annotations

from typing import Any

# Where analysis stores its per-unit results. `analysis_polygon_source` returns
# one of these from `get_metadata_key()` depending on the forest's dimension
# mode, so both are checked rather than guessed at.
RESULT_COLLECTIONS = ("blocks", "compartments", "sub_compartments")
# The marker `analysis.py` attaches to a unit whose analysis raised.
ERROR_MARKER = "analysis_error"


def failed_units(result_data: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Every analysed unit carrying an error marker, across every collection."""
    if not result_data:
        return []
    out: list[dict[str, Any]] = []
    for key in RESULT_COLLECTIONS:
        units = result_data.get(key)
        if not isinstance(units, list):
            continue
        for index, unit in enumerate(units):
            if isinstance(unit, dict) and unit.get(ERROR_MARKER):
                out.append({
                    "collection": key,
                    "index": index,
                    "name": unit.get("name") or unit.get("block_name") or f"#{index + 1}",
                    "error": str(unit[ERROR_MARKER])[:200],
                })
    return out


def partial_failure_reason(result_data: dict[str, Any] | None) -> str | None:
    """A sentence explaining why this calculation is not `completed`, or None.

    Returned rather than raised so the caller decides what to do with it, and so
    the detection can be tested without constructing a pipeline. The message is
    written to be read by whoever opens the calculation and finds it failed —
    it names the units, not just the count, because "3 blocks failed" sends
    somebody hunting through logs that "Block 4, Block 7, Block 9 failed" does
    not.
    """
    failures = failed_units(result_data)
    if not failures:
        return None

    total = _total_units(result_data)
    names = ", ".join(f["name"] for f in failures[:5])
    if len(failures) > 5:
        names += f", and {len(failures) - 5} more"

    scope = f"{len(failures)} of {total}" if total else str(len(failures))
    first = failures[0]["error"]
    return (
        f"Analysis failed for {scope} units ({names}). The calculation is marked "
        f"failed rather than completed because its totals would otherwise be "
        f"wrong with nothing to indicate it. First error: {first}"
    )


def _total_units(result_data: dict[str, Any] | None) -> int:
    if not result_data:
        return 0
    return sum(
        len(result_data[key])
        for key in RESULT_COLLECTIONS
        if isinstance(result_data.get(key), list)
    )
