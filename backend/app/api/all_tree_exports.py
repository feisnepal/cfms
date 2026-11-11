"""
All Tree Export API endpoints
"""
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from typing import List, Optional
from uuid import UUID
import os
import threading
import logging
from app.core.errors import CalculationErrors

logger = logging.getLogger(__name__)
from datetime import datetime, timezone

from ..core.database import get_db
from ..core.config import settings
from ..core.exceptions import i18n_success
from ..models.user import User
from ..models.calculation import Calculation
from ..models.all_tree_export import AllTreeExport
from ..schemas.all_tree_export import (
    GenerateAllTreesRequest,
    AllTreeExportResponse,
    AllTreeExportListResponse,
)
from ..utils.auth import get_current_active_user
from ..services.tree_distribution import EXCEL_MAX_TREE_ROWS, generate_full_extent_trees


router = APIRouter()


EXPIRED_DETAIL = (
    "This export has expired and was deleted (Total Tree Exports are kept for 1 hour "
    "after they finish). Generate it again."
)


def _purge_expired(db: Session) -> None:
    """Enforce the one-hour life before any export is read, so the rule holds
    even if the background sweep has not run. Never lets a purge failure break a read."""
    from ..services.export_cleanup import purge_expired_all_tree_exports

    try:
        purge_expired_all_tree_exports(db)
    except Exception:  # noqa: BLE001 -- housekeeping must not fail the request; logged below
        logger.exception("Expired-export purge failed")
        db.rollback()


def _unit_scope_config(db: Session, calculation_id: UUID, unit_ids: Optional[List[UUID]]) -> dict:
    """The `unit_ids` entry for the generator config, or {} for the whole boundary.

    Every id must be a unit of THIS calculation. An id that is not (stale selection,
    another forest's unit) is refused rather than dropped: silently exporting a
    different area than the one the user selected is worse than an error.
    """
    if not unit_ids:
        return {}
    from ..models.forest_block import ForestBlock

    wanted = set(unit_ids)
    found = {
        row[0]
        for row in db.query(ForestBlock.id)
        .filter(ForestBlock.calculation_id == calculation_id, ForestBlock.id.in_(wanted))
        .all()
    }
    if found != wanted:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The selected block(s) do not belong to this forest. Re-select and try again.",
        )
    return {"unit_ids": sorted(str(u) for u in wanted)}


def background_all_tree_generation(
    export_id: UUID,
    calculation_id: UUID,
    config: dict,
    db_url: str,
):
    """
    Background task for all-tree generation
    """
    import logging
    logger = logging.getLogger(__name__)
    
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    engine = create_engine(db_url)
    SessionLocal = sessionmaker(bind=engine)
    db = SessionLocal()

    try:
        logger.info(f"Background task started for export {export_id}")
        export = db.query(AllTreeExport).filter(AllTreeExport.id == export_id).first()
        if not export:
            logger.warning(f"Export {export_id} not found")
            return

        def update_progress(percent: int, step: str):
            export.progress_percent = percent
            export.current_step = step
            db.commit()

        update_progress(5, "Initializing")
        logger.info(f"Export {export_id}: Starting generation")
        result = generate_full_extent_trees(
            calculation_id=calculation_id,
            db=db,
            config=config,
            progress_callback=update_progress,
        )

        stats = result['statistics']

        export.status = "completed"
        export.total_trees = stats['total_trees']
        export.area_hectares = stats['area_hectares']
        export.trees_per_hectare = stats['trees_per_hectare']
        export.min_dbh_cm = stats['min_dbh_cm']
        export.max_dbh_cm = stats['max_dbh_cm']
        export.min_height_m = stats['min_height_m']
        export.max_height_m = stats['max_height_m']

        export.gpkg_filename = result.get('gpkg_filename')
        export.gpkg_size_mb = result.get('gpkg_size_mb')
        export.gpkg_path = result.get('gpkg_filepath')
        export.excel_filename = result.get('excel_filename')
        export.excel_size_mb = result.get('excel_size_mb')
        export.excel_path = result.get('excel_filepath')
        export.csv_filename = result.get('csv_filename')
        export.csv_size_mb = result.get('csv_size_mb')
        export.csv_path = result.get('csv_filepath')

        export.processing_time_seconds = result['processing_time_seconds']
        export.completed_at = datetime.now(timezone.utc)
        export.progress_percent = 100
        export.current_step = "Complete"

        # Store statistics in algorithm_config for frontend display
        config_with_stats = dict(export.algorithm_config or {})
        config_with_stats['statistics'] = stats
        export.algorithm_config = config_with_stats

        db.commit()

    except Exception as e:
        import traceback
        logger.error(f"Background task failed for export {export_id}: {e}\n{traceback.format_exc()}")
        export.status = "failed"
        export.error_message = str(e)
        export.progress_percent = 0
        export.current_step = "Failed"
        db.commit()

    finally:
        db.close()
        engine.dispose()
        logger.info(f"Background task finished for export {export_id}")


@router.post("/calculations/{calculation_id}/generate-all-trees-sync", response_model=AllTreeExportResponse)
def generate_all_trees_sync(
    calculation_id: UUID,
    request: GenerateAllTreesRequest,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """
    SYNCHRONOUS version for testing — blocks until generation completes.
    """
    calculation = db.query(Calculation).filter(Calculation.id == calculation_id).first()
    if not calculation:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=CalculationErrors.NOT_FOUND)

    if not calculation.boundary_geom:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Calculation has no boundary geometry")

    config = request.config.model_dump() if request.config else {}
    config.update(_unit_scope_config(db, calculation_id, request.unit_ids))

    export = AllTreeExport(
        calculation_id=calculation_id,
        user_id=current_user.id,
        model_type="full_extent",
        model_version="v1.0",
        algorithm_config=config,
        status="processing",
        progress_percent=0,
        current_step="Starting",
    )
    db.add(export)
    db.commit()
    db.refresh(export)

    def update_progress(pct, step):
        export.progress_percent = pct
        export.current_step = step
        db.commit()

    from ..services.tree_distribution import generate_full_extent_trees
    result = generate_full_extent_trees(
        calculation_id=calculation_id,
        db=db,
        config=config,
        progress_callback=update_progress,
    )

    stats = result['statistics']
    export.status = "completed"
    export.total_trees = stats['total_trees']
    export.area_hectares = stats['area_hectares']
    export.trees_per_hectare = stats['trees_per_hectare']
    export.min_dbh_cm = stats['min_dbh_cm']
    export.max_dbh_cm = stats['max_dbh_cm']
    export.min_height_m = stats['min_height_m']
    export.max_height_m = stats['max_height_m']
    export.gpkg_filename = result.get('gpkg_filename')
    export.gpkg_size_mb = result.get('gpkg_size_mb')
    export.gpkg_path = result.get('gpkg_filepath')
    export.excel_filename = result.get('excel_filename')
    export.excel_size_mb = result.get('excel_size_mb')
    export.excel_path = result.get('excel_filepath')
    export.csv_filename = result.get('csv_filename')
    export.csv_size_mb = result.get('csv_size_mb')
    export.csv_path = result.get('csv_filepath')
    export.processing_time_seconds = result['processing_time_seconds']
    export.completed_at = datetime.now(timezone.utc)
    export.progress_percent = 100
    export.current_step = "Complete"
    db.commit()

    return export


@router.post("/calculations/{calculation_id}/generate-all-trees", response_model=AllTreeExportResponse)
def generate_all_trees(
    calculation_id: UUID,
    request: GenerateAllTreesRequest,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """
    Generate ALL trees within the forest boundary from canopy height raster.

    Unlike the regular tree model (which only creates trees in sample plots),
    this processes every valid pixel in the forest boundary.

    **Output:** GPKG + Excel (flat format: 1 row = 1 tree) + CSV
    """
    calculation = db.query(Calculation).filter(Calculation.id == calculation_id).first()
    if not calculation:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=CalculationErrors.NOT_FOUND)

    if calculation.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Permission denied")

    if not calculation.boundary_geom:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Calculation has no boundary geometry")

    result_data = calculation.result_data or {}
    if not result_data.get('potential_species'):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Calculation has no species data. Run analysis first."
        )

    existing = db.query(AllTreeExport).filter(
        AllTreeExport.calculation_id == calculation_id,
        AllTreeExport.status == "processing",
    ).first()

    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"All-tree generation already in progress (ID: {existing.id})",
        )

    config = request.config.model_dump() if request.config else {}
    config.update(_unit_scope_config(db, calculation_id, request.unit_ids))

    export = AllTreeExport(
        calculation_id=calculation_id,
        user_id=current_user.id,
        model_type="full_extent",
        model_version="v1.0",
        algorithm_config=config,
        status="processing",
        progress_percent=0,
        current_step="Queued",
    )

    db.add(export)
    db.commit()
    db.refresh(export)

    thread = threading.Thread(
        target=background_all_tree_generation,
        args=(export.id, calculation_id, config, settings.DATABASE_URL),
        daemon=True,
    )
    thread.start()

    return export


@router.get("/all-tree-exports/{export_id}", response_model=AllTreeExportResponse)
def get_all_tree_export(
    export_id: UUID,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Get all-tree export status and statistics (polling)"""
    _purge_expired(db)
    export = db.query(AllTreeExport).filter(AllTreeExport.id == export_id).first()
    if not export:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=EXPIRED_DETAIL)

    if export.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Permission denied")

    return export


@router.get("/calculations/{calculation_id}/all-tree-exports", response_model=AllTreeExportListResponse)
def list_all_tree_exports(
    calculation_id: UUID,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """List all all-tree exports for a calculation"""
    _purge_expired(db)
    calculation = db.query(Calculation).filter(Calculation.id == calculation_id).first()
    if not calculation:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=CalculationErrors.NOT_FOUND)

    if calculation.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Permission denied")

    exports = (
        db.query(AllTreeExport)
        .filter(AllTreeExport.calculation_id == calculation_id)
        .order_by(AllTreeExport.created_at.desc())
        .all()
    )

    return {"exports": exports, "total_count": len(exports)}


# kind -> (record path attr, report-type label, file extension, media type)
_DOWNLOAD_KINDS = {
    "gpkg": ("gpkg_path", "GPKG", "gpkg", "application/geopackage+sqlite3"),
    "excel": ("excel_path", "Excel", "xlsx",
              "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
    "csv": ("csv_path", "CSV", "csv", "text/csv"),
}


def _serve_export_file(db: Session, export_id: UUID, user: User, kind: str) -> FileResponse:
    """Serve one format of a Total Tree Export.

    The files are NOT deleted on download: one export carries three formats, and
    removing everything after the first download would take the other two with it
    (and the derived sample-plot GPKG). They live for one hour after generation --
    see ``services/export_cleanup.purge_expired_all_tree_exports`` -- or until the
    user deletes the export.
    """
    path_attr, label, ext, media_type = _DOWNLOAD_KINDS[kind]

    _purge_expired(db)
    export = db.query(AllTreeExport).filter(AllTreeExport.id == export_id).first()
    if not export:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=EXPIRED_DETAIL)

    if export.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Permission denied")

    if export.status != "completed":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Export not completed. Status: {export.status}")

    filepath = getattr(export, path_attr, None)
    if not filepath or not os.path.exists(filepath):
        if kind == "excel" and (export.total_trees or 0) > EXCEL_MAX_TREE_ROWS:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"No Excel file: {export.total_trees:,} trees exceed Excel's "
                       f"{EXCEL_MAX_TREE_ROWS:,}-row limit. Download the CSV or GPKG instead.",
            )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"{label} file not found. Generate the export again.",
        )

    calc = db.query(Calculation).filter(Calculation.id == export.calculation_id).first()
    forest_name = calc.forest_name if calc and calc.forest_name else "forest"
    from app.utils.file_export import build_disposition
    _, disposition = build_disposition(forest_name, "AllTrees", label, ext)

    return FileResponse(
        path=filepath,
        filename=getattr(export, path_attr.replace("_path", "_filename"), None),
        media_type=media_type,
        headers={"Content-Disposition": disposition},
    )


@router.get("/all-tree-exports/{export_id}/download")
def download_all_tree_gpkg(
    export_id: UUID,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Download the all-tree export as GPKG (spatial points)."""
    return _serve_export_file(db, export_id, current_user, "gpkg")


@router.get("/all-tree-exports/{export_id}/download-excel")
def download_all_tree_excel(
    export_id: UUID,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Download the all-tree export as Excel: sheet "Tree Data" (1 row = 1 tree) + "Summary" per block."""
    return _serve_export_file(db, export_id, current_user, "excel")


@router.get("/all-tree-exports/{export_id}/download-csv")
def download_all_tree_csv(
    export_id: UUID,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Download the all-tree export as CSV (1 row = 1 tree)."""
    return _serve_export_file(db, export_id, current_user, "csv")


@router.delete("/all-tree-exports/{export_id}")
def delete_all_tree_export(
    export_id: UUID,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Delete all-tree export and associated files"""
    export = db.query(AllTreeExport).filter(AllTreeExport.id == export_id).first()
    if not export:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Export not found")

    if export.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Permission denied")

    for path_attr in ['gpkg_path', 'excel_path', 'csv_path']:
        filepath = getattr(export, path_attr, None)
        if filepath and os.path.exists(filepath):
            try:
                os.remove(filepath)
            except Exception as e:
                logger.warning(f"Could not delete {filepath}: {e}")

    db.delete(export)
    db.commit()

    return {"success": True, **i18n_success("success.tree_export_deleted")}


@router.post("/all-tree-exports/{export_id}/extract-sample-plots")
def extract_all_tree_sample_plots(
    export_id: UUID,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """
    Extract trees from the all-tree GPKG that fall within sample plot buffers.
    Returns a GPKG with only the trees inside sample plots, annotated with plot_number.
    """
    _purge_expired(db)
    export = db.query(AllTreeExport).filter(AllTreeExport.id == export_id).first()
    if not export:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Export not found")
    if export.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Permission denied")
    if export.status != "completed" or not export.gpkg_path:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Export not completed or GPKG missing")

    if not os.path.exists(export.gpkg_path):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="GPKG file not found on disk")

    from ..services.tree_distribution import extract_sample_plot_trees
    result = extract_sample_plot_trees(
        all_tree_gpkg_path=export.gpkg_path,
        calculation_id=export.calculation_id,
        db=db,
        output_dir=os.path.join(os.path.dirname(__file__), '..', '..', 'exports'),
        output_filename=f"sample_plots_{export_id}.gpkg",
    )

    return result


@router.get("/all-tree-exports/{export_id}/sample-plot-gpkg")
def download_all_tree_sample_plots(
    export_id: UUID,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """
    Download the sample-plot extracted GPKG derived from the all-tree export.
    """
    _purge_expired(db)
    export = db.query(AllTreeExport).filter(AllTreeExport.id == export_id).first()
    if not export:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Export not found")
    if export.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Permission denied")
    if export.status != "completed":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Export not completed")

    filename = f"sample_plots_{export_id}.gpkg"
    filepath = os.path.join(os.path.dirname(__file__), '..', '..', 'exports', filename)

    if not os.path.exists(filepath):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Sample plot GPKG not found. Run extract-sample-plots first.")

    calc = db.query(Calculation).filter(Calculation.id == export.calculation_id).first()
    forest_name = calc.forest_name if calc and calc.forest_name else "forest"
    from app.utils.file_export import build_disposition
    _, disposition = build_disposition(forest_name, "AllTrees_SamplePlots", "GPKG", "gpkg")
    download_name = f"{forest_name}_AllTrees_SamplePlots_{datetime.now(timezone.utc).strftime('%Y%m%d')}.gpkg"

    return FileResponse(
        path=filepath,
        filename=download_name,
        media_type="application/geopackage+sqlite3",
        headers={"Content-Disposition": disposition},
    )


@router.post("/exports/cleanup")
def cleanup_old_exports(
    retention_days: int = 7,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """
    Delete old export files (GPKG, Excel, CSV) older than retention_days.
    Also cleans up orphaned files with no matching DB record.
    Only super_admin users can trigger this.
    """
    if current_user.role != "super_admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only admin users can trigger export cleanup",
        )

    from ..services.export_cleanup import run_full_cleanup
    export_dir = os.path.join(os.path.dirname(__file__), '..', '..', 'exports')

    results = run_full_cleanup(db, export_dir, retention_days)

    total_cleaned = (
        results["old_tree_exports_deleted"]
        + results["old_tree_models_deleted"]
        + results["orphan_files_deleted"]
        + results["inventory_files_deleted"]
    )

    return {
        "success": True,
        "message": f"Cleanup complete: {total_cleaned} items removed",
        "details": results,
    }
