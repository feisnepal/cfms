"""Remove the files that belong to a forest (work package FD, FD-3).

Owner's rule, 2026-09-21: deleting a forest deletes ALL of its data — rows *and* files.
The rows go with the forest through the database's ``ON DELETE CASCADE``; this module handles
what the database cannot see: export files and the per-forest cache folders.

The order matters, and it is the reason there are two functions rather than one:

1. :func:`collect_forest_files` runs **before** the delete, because the export file paths are
   stored in rows that are about to disappear.
2. :func:`remove_forest_files` runs **after** the delete has committed, so a delete that fails
   never loses a file (and a file that fails to delete never blocks a forest delete).

Per-forest cache folders are removed through the same helpers that write them
(``clear_map_cache`` / the soil-erosion and hazard ``clear_cache``), so this looks exactly where
the files were put — those cache roots are *relative* paths (``uploads/...``) and only resolve
correctly from the process's working directory.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, List
from uuid import UUID

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


def collect_forest_files(db: Session, calculation_id: Any) -> List[str]:
    """Paths of the export files belonging to a forest. Call BEFORE deleting its rows."""
    from .export_cleanup import cleanup_export_files_for_calculation

    return list(cleanup_export_files_for_calculation(db, calculation_id))


def remove_forest_files(calculation_id: Any, export_paths: List[str]) -> Dict[str, int]:
    """Remove the export files and every per-forest cache folder. Call AFTER the commit.

    Best-effort by design: a leftover file is logged, never raised, because the forest is
    already gone and the caller must still return success.
    """
    cid = (
        calculation_id
        if isinstance(calculation_id, UUID)
        else UUID(str(calculation_id))
    )
    removed = {"export_files": 0, "cache_folders": 0}

    from .export_cleanup import _remove_file

    for path in export_paths:
        if _remove_file(path):
            removed["export_files"] += 1

    def _clear(label: str, fn) -> None:
        try:
            fn(cid)
            removed["cache_folders"] += 1
        except Exception:  # noqa: BLE001 -- best-effort: a cache must not fail a delete
            logger.warning(
                "Could not clear the %s for forest %s", label, cid, exc_info=True
            )

    from .management_plan_docx.plan_map_service import clear_map_cache
    from .operational_plan.landslide_susceptibility import (
        clear_cache as clear_hazard_cache,
    )
    from .operational_plan.soil_erosion import clear_cache as clear_soil_cache

    _clear("rendered-map cache", lambda c: clear_map_cache(calculation_id=c))
    _clear("soil-erosion cache", clear_soil_cache)
    _clear("hazard cache", clear_hazard_cache)

    from .ntfp_plot_extras import remove_forest_photos

    _clear("NTFP plot photos", remove_forest_photos)

    logger.info(
        "Purged files of forest %s: %d export file(s), %d cache folder group(s)",
        cid,
        removed["export_files"],
        removed["cache_folders"],
    )
    return removed


def forest_folders_on_disk(calculation_id: Any) -> List[str]:
    """Per-forest folders that still exist — used by tests and the orphan report."""
    cid = str(calculation_id)
    from .management_plan_docx.plan_map_service import MAP_CACHE_DIR
    from .operational_plan.landslide_susceptibility import _CACHE_ROOT as HAZARD_ROOT
    from .operational_plan.soil_erosion import _CACHE_ROOT as SOIL_ROOT

    from .ntfp_plot_extras import forest_photo_dir

    candidates = [
        os.path.join(MAP_CACHE_DIR, cid),
        forest_photo_dir(cid),
        str(SOIL_ROOT / cid),
        str(HAZARD_ROOT / cid),
    ]
    return [p for p in candidates if os.path.exists(p)]
