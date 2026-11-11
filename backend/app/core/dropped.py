"""Report a record the code decided to skip, without flooding the log (H3.4 · S2-37).

The dominant shape among the silent exception handlers the audit found is not a
crash being hidden. It is a loop:

    for river in rivers:
        try:
            geom = wkt.loads(river['geom_wkt'])
            ...
        except Exception:
            continue

One record leaves the union, the map, or the area sum, and nothing anywhere says
so. The result is not an error — it is **a plausible-looking wrong number**, or
a map missing a river nobody knows was there.

The obvious fix, a `logger.warning` in the handler, is wrong in exactly the
places it matters most. Several of these loops run over raster pixels, tens of
thousands per map. A log line each turns one bad geometry into a log nobody can
read, and the flood is itself a way of hiding.

So this module gives the handler one line that is safe at any loop size:

    except Exception:
        report_dropped(logger, "river", "it will be missing from the map")
        continue

The first few occurrences of each distinct drop are logged with a full
traceback, because the first one is what somebody debugging actually needs.
After that the same drop is logged only on a widening interval, carrying the
running count — so a systematic failure reads as *"river dropped (500 so far)"*
rather than five hundred identical lines.

Counts are per process and per (logger, what) pair, and `dropped_counts()`
exposes them so a caller that wants to surface "we skipped 12 features" in a
response or a report can, and so tests can assert on them without parsing logs.
"""
from __future__ import annotations

import logging
import threading
from collections import Counter

# First N occurrences of a given drop are logged in full, with the traceback.
_VERBOSE_LIMIT = 3
# After that, one line every Nth occurrence, carrying the running total.
_SUMMARY_INTERVAL = 100

_counts: Counter[tuple[str, str]] = Counter()
_lock = threading.Lock()


def report_dropped(
    logger: logging.Logger,
    what: str,
    consequence: str,
    *,
    context: object = None,
) -> int:
    """Record that one item was skipped, and log it at a bounded rate.

    Args:
        logger: the caller's module logger, so the log line names the real site.
        what: the kind of thing skipped, singular — ``"river"``, ``"block"``.
            This is the counter key, so keep it stable rather than
            interpolating an id into it.
        consequence: what is now wrong because of the skip, in plain words:
            ``"it will be missing from the map"``, ``"its area is not counted"``.
            This is the part somebody reading the log at 3am needs, and it is
            required rather than optional for that reason.
        context: an identifier for *this* item — a row id, an index, a name.
            Logged, never counted.

    Returns:
        How many of this kind have now been dropped in this process, so a caller
        can act on the total (surface it, fail past a threshold) if it wants to.
    """
    key = (logger.name, what)
    with _lock:
        _counts[key] += 1
        count = _counts[key]

    where = f" ({context})" if context is not None else ""
    if count <= _VERBOSE_LIMIT:
        logger.warning(
            "dropped %s%s - %s", what, where, consequence, exc_info=True,
        )
    elif count % _SUMMARY_INTERVAL == 0:
        # No traceback: by now the first three carry it, and this line exists to
        # report scale, not cause.
        logger.warning(
            "dropped %s%s - %s (%d so far in this process)",
            what, where, consequence, count,
        )
    return count


def dropped_counts() -> dict[tuple[str, str], int]:
    """A snapshot of every drop counted so far, keyed by (logger name, what)."""
    with _lock:
        return dict(_counts)


def reset_dropped_counts() -> None:
    """Clear the counters. For tests, and for a worker starting a fresh job."""
    with _lock:
        _counts.clear()
