import logging
from typing import List, Optional

from fastapi import Response

logger = logging.getLogger(__name__)


def signal_cache_invalidated(response: Response, calc_id: str, categories: Optional[List[str]] = None) -> None:
    """Attach cache-invalidation headers to a response.

    Args:
        response: FastAPI/Starlette Response to attach headers to.
        calc_id: The calculation whose caches were invalidated.
        categories: Subset of {"maps", "charts", "analysis", "all"}.
    """
    if categories is None:
        categories = ["all"]
    response.headers["X-Cache-Invalidated"] = ",".join(categories)
    response.headers["X-Cache-Calc-Id"] = calc_id
    logger.info(
        "Cache invalidation signalled for calc=%s categories=%s",
        calc_id, ",".join(categories),
    )


def invalidate_calc_caches(calc_id: str, categories: Optional[List[str]] = None) -> None:
    """Signal that client-side IndexedDB caches for a calculation should be dropped.

    Args:
        calc_id: The calculation whose client caches should be cleared.
        categories: Subset of {"maps", "charts", "analysis", "all"}.
                    Defaults to ["all"] when not specified.
    """
    if categories is None:
        categories = ["all"]
    logger.info(
        "Cache invalidation requested for calc=%s categories=%s",
        calc_id, ",".join(categories),
    )
