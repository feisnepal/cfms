"""
Export Cleanup Service

Handles automatic cleanup of old export files (GPKG, Excel, CSV) and
orphaned files from deleted Calculations.

Three cleanup strategies:
1. Age-based: Delete exports older than N days (startup + manual trigger)
2. Orphan cleanup: Delete files whose DB records were cascade-deleted
3. Inventory data entry: Delete orphaned inventory export files
"""

import os
import re
import logging
from datetime import datetime, timezone, timedelta
from typing import Tuple

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

EXPORT_RETENTION_DAYS = 7

# Total Tree Exports are large, regenerable, and meant to be downloaded straight
# away, so they live far shorter than the 7-day general retention above.
ALL_TREE_EXPORT_TTL = timedelta(hours=1)


def _remove_file(path: str) -> bool:
    """Safely remove a file. Returns True if deleted."""
    if not path:
        return False
    try:
        if os.path.exists(path):
            os.remove(path)
            logger.info(f"Deleted file: {path}")
            return True
    except Exception as e:
        logger.warning(f"Could not delete {path}: {e}")
    return False


def cleanup_old_tree_exports(
    db: Session, retention_days: int = EXPORT_RETENTION_DAYS
) -> Tuple[int, int]:
    """
    Delete AllTreeExport records older than retention_days,
    along with their files on disk.
    Returns (records_deleted, files_deleted).
    """
    from ..models.all_tree_export import AllTreeExport

    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
    old_exports = (
        db.query(AllTreeExport)
        .filter(
            AllTreeExport.created_at < cutoff,
            AllTreeExport.status.in_(["completed", "failed"]),
        )
        .all()
    )

    records_deleted = 0
    files_deleted = 0

    for export in old_exports:
        for path_attr in ["gpkg_path", "excel_path", "csv_path"]:
            filepath = getattr(export, path_attr, None)
            if _remove_file(filepath):
                files_deleted += 1
        db.delete(export)
        records_deleted += 1

    if records_deleted:
        db.commit()
        logger.info(
            f"Cleaned up {records_deleted} old AllTreeExport records, {files_deleted} files"
        )

    return records_deleted, files_deleted


def all_tree_export_expiry(export) -> "datetime | None":
    """When a finished Total Tree Export is deleted; None while it is still running.

    The clock starts when generation finishes (``completed_at``), not when it was
    queued, so a long run does not eat into the time the user has to download.
    A failed export has no ``completed_at`` and counts from ``created_at``.
    """
    if export.status not in ("completed", "failed"):
        return None
    started = export.completed_at or export.created_at
    if started is None:
        return None
    if started.tzinfo is None:
        started = started.replace(tzinfo=timezone.utc)
    return started + ALL_TREE_EXPORT_TTL


def purge_expired_all_tree_exports(db: Session) -> int:
    """Delete Total Tree Exports past their one-hour life: files, derived files, record.

    Safe to call often (it is a single indexed query when nothing has expired).
    Returns the number of records removed. A running export is never touched.
    """
    from ..models.all_tree_export import AllTreeExport

    now = datetime.now(timezone.utc)
    removed = 0
    candidates = (
        db.query(AllTreeExport)
        .filter(AllTreeExport.status.in_(["completed", "failed"]))
        .all()
    )
    for export in candidates:
        expires_at = all_tree_export_expiry(export)
        if expires_at is None or expires_at > now:
            continue
        for path_attr in ("gpkg_path", "excel_path", "csv_path"):
            _remove_file(getattr(export, path_attr, None))
        # The sample-plot subset derived from this export (see the
        # extract-sample-plots endpoint) has no record of its own.
        _remove_file(
            os.path.join(
                os.path.dirname(__file__), "..", "..", "exports",
                f"sample_plots_{export.id}.gpkg",
            )
        )
        db.delete(export)
        removed += 1
    if removed:
        db.commit()
        logger.info("Expired %d Total Tree Export(s) past %s", removed, ALL_TREE_EXPORT_TTL)
    return removed


def cleanup_old_tree_models(
    db: Session, retention_days: int = EXPORT_RETENTION_DAYS
) -> Tuple[int, int]:
    """
    Delete SyntheticTreeModel records older than retention_days,
    along with their files on disk.
    Returns (records_deleted, files_deleted).
    """
    from ..models.synthetic_tree_model import SyntheticTreeModel

    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
    old_models = (
        db.query(SyntheticTreeModel)
        .filter(
            SyntheticTreeModel.created_at < cutoff,
            SyntheticTreeModel.status.in_(["completed", "failed"]),
        )
        .all()
    )

    records_deleted = 0
    files_deleted = 0

    for model in old_models:
        for path_attr in ["file_path", "excel_path"]:
            filepath = getattr(model, path_attr, None)
            if _remove_file(filepath):
                files_deleted += 1
        db.delete(model)
        records_deleted += 1

    if records_deleted:
        db.commit()
        logger.info(
            f"Cleaned up {records_deleted} old SyntheticTreeModel records, {files_deleted} files"
        )

    return records_deleted, files_deleted


def cleanup_orphan_export_files(export_dir: str) -> int:
    """
    Scan the exports directory for GPKG/Excel/CSV files that have no
    matching DB record. This catches files orphaned by cascade deletes
    or failed cleanups.
    Returns number of orphan files deleted.
    """
    from ..core.database import SessionLocal
    from ..models.all_tree_export import AllTreeExport
    from ..models.synthetic_tree_model import SyntheticTreeModel

    if not os.path.isdir(export_dir):
        return 0

    db = SessionLocal()
    try:
        all_gpkg_paths = set()
        all_xlsx_paths = set()
        all_csv_paths = set()

        for rec in db.query(AllTreeExport).all():
            if rec.gpkg_path:
                all_gpkg_paths.add(os.path.normpath(rec.gpkg_path))
            if rec.excel_path:
                all_xlsx_paths.add(os.path.normpath(rec.excel_path))
            if rec.csv_path:
                all_csv_paths.add(os.path.normpath(rec.csv_path))

        for rec in db.query(SyntheticTreeModel).all():
            if rec.file_path:
                all_gpkg_paths.add(os.path.normpath(rec.file_path))
            if rec.excel_path:
                all_xlsx_paths.add(os.path.normpath(rec.excel_path))

        known_paths = all_gpkg_paths | all_xlsx_paths | all_csv_paths

        deleted = 0
        for fname in os.listdir(export_dir):
            fpath = os.path.normpath(os.path.join(export_dir, fname))
            if not os.path.isfile(fpath):
                continue
            ext = os.path.splitext(fname)[1].lower()
            if ext not in (".gpkg", ".xlsx", ".csv", ".xls"):
                continue
            if fname == ".gitkeep":
                continue
            if fpath not in known_paths:
                if _remove_file(fpath):
                    deleted += 1

        if deleted:
            logger.info(f"Cleaned up {deleted} orphan export files from {export_dir}")
        return deleted
    finally:
        db.close()


def cleanup_inventory_data_entry_files(export_dir: str) -> int:
    """
    Delete inventory_data_entry files from the exports directory.
    These are generated on-the-fly and not tracked by any DB model.
    Returns number of files deleted.
    """
    if not os.path.isdir(export_dir):
        return 0

    deleted = 0
    for fname in os.listdir(export_dir):
        if "inventory_data_entry" in fname and fname.endswith(
            (".xlsx", ".xls", ".csv")
        ):
            fpath = os.path.join(export_dir, fname)
            if _remove_file(fpath):
                deleted += 1

    if deleted:
        logger.info(
            f"Cleaned up {deleted} inventory_data_entry files from {export_dir}"
        )
    return deleted


def cleanup_export_files_for_calculation(db: Session, calculation_id) -> list:
    """
    Collect and return file paths for all exports belonging to a Calculation.
    Used BEFORE cascade delete so we can remove files from disk first.
    """
    from ..models.all_tree_export import AllTreeExport
    from ..models.synthetic_tree_model import SyntheticTreeModel

    paths = []

    for rec in (
        db.query(AllTreeExport)
        .filter(AllTreeExport.calculation_id == calculation_id)
        .all()
    ):
        for attr in ["gpkg_path", "excel_path", "csv_path"]:
            p = getattr(rec, attr, None)
            if p:
                paths.append(p)

    for rec in (
        db.query(SyntheticTreeModel)
        .filter(SyntheticTreeModel.calculation_id == calculation_id)
        .all()
    ):
        for attr in ["file_path", "excel_path"]:
            p = getattr(rec, attr, None)
            if p:
                paths.append(p)

    return paths


def run_full_cleanup(
    db: Session, export_dir: str, retention_days: int = EXPORT_RETENTION_DAYS
) -> dict:
    """
    Run all cleanup strategies. Returns summary dict.
    """
    results = {
        "old_tree_exports_deleted": 0,
        "old_tree_exports_files": 0,
        "old_tree_models_deleted": 0,
        "old_tree_models_files": 0,
        "orphan_files_deleted": 0,
        "inventory_files_deleted": 0,
        "retention_days": retention_days,
    }

    r1, f1 = cleanup_old_tree_exports(db, retention_days)
    results["old_tree_exports_deleted"] = r1
    results["old_tree_exports_files"] = f1

    r2, f2 = cleanup_old_tree_models(db, retention_days)
    results["old_tree_models_deleted"] = r2
    results["old_tree_models_files"] = f2

    results["orphan_files_deleted"] = cleanup_orphan_export_files(export_dir)
    results["inventory_files_deleted"] = cleanup_inventory_data_entry_files(export_dir)

    total = sum(v for k, v in results.items() if k != "retention_days")
    logger.info(
        f"Full cleanup complete: {total} items removed (retention={retention_days}d)"
    )

    return results
