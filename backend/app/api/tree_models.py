"""
Synthetic Tree Distribution Model API endpoints
"""
from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks, Request, Query
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from typing import List, Optional
from uuid import UUID
import os
import threading
import logging
from app.core.errors import CalculationErrors

logger = logging.getLogger(__name__)

from ..core.database import get_db
from ..core.rate_limit import limiter
from ..models.user import User
from ..models.calculation import Calculation
from ..models.synthetic_tree_model import SyntheticTreeModel
from ..schemas.tree_model import (
    GenerateTreeModelRequest,
    TreeModelResponse,
    TreeModelListResponse,
)
from ..utils.auth import get_current_active_user
from ..services.tree_distribution import generate_synthetic_trees
from ..services.tree_clusters import cluster_inventory_trees


router = APIRouter()


def background_tree_generation(
    model_id: UUID,
    calculation_id: UUID,
    config: dict,
    db_url: str
):
    """
    Background task for tree model generation

    Runs in separate thread to avoid blocking the API response
    """
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from datetime import datetime, timezone

    # Create new database session for this thread
    engine = create_engine(db_url)
    SessionLocal = sessionmaker(bind=engine)
    db = SessionLocal()

    try:
        # Get model record
        model = db.query(SyntheticTreeModel).filter(SyntheticTreeModel.id == model_id).first()
        if not model:
            return

        # Progress callback
        def update_progress(percent: int, step: str):
            model.progress_percent = percent
            model.current_step = step
            db.commit()

        # Generate trees
        update_progress(5, "Initializing")
        result = generate_synthetic_trees(
            calculation_id=calculation_id,
            db=db,
            config=config,
            progress_callback=update_progress
        )

        # Update model with results (both GPKG and Excel)
        model.status = "completed"
        model.total_trees = result['statistics']['total_trees']
        model.area_hectares = result['statistics']['area_hectares']
        model.trees_per_hectare = result['statistics']['trees_per_hectare']
        model.min_dbh_cm = result['statistics']['min_dbh_cm']
        model.max_dbh_cm = result['statistics']['max_dbh_cm']
        model.min_height_m = result['statistics']['min_height_m']
        model.max_height_m = result['statistics']['max_height_m']
        # GPKG file (primary)
        model.gpkg_filename = result.get('gpkg_filename', result.get('filename'))
        model.file_size_mb = result.get('gpkg_size_mb', result.get('file_size_mb'))
        model.file_path = result.get('gpkg_filepath', result.get('filepath'))
        # Excel file (additional)
        model.excel_filename = result.get('excel_filename')
        model.excel_size_mb = result.get('excel_size_mb')
        model.excel_path = result.get('excel_filepath')
        # General info
        model.processing_time_seconds = result['processing_time_seconds']
        model.completed_at = datetime.now(timezone.utc)
        model.progress_percent = 100
        model.current_step = "Complete"

        # Add statistics to algorithm_config for frontend display
        config_with_stats = dict(model.algorithm_config or {})
        stats = result['statistics']
        
        # Block-wise distribution
        config_with_stats['block_dbh_distribution'] = stats.get('block_dbh_distribution', {})
        
        # Overall DBH class density per hectare
        config_with_stats['dbh_per_ha'] = stats.get('dbh_per_ha', {})
        
        # Overall volume breakdown (matching field inventory method)
        config_with_stats['pole_timber_m3_per_ha'] = stats.get('pole_timber_m3_per_ha', 0)
        config_with_stats['pole_firewood_m3_per_ha'] = stats.get('pole_firewood_m3_per_ha', 0)
        config_with_stats['tree_timber_m3_per_ha'] = stats.get('tree_timber_m3_per_ha', 0)
        config_with_stats['tree_firewood_m3_per_ha'] = stats.get('tree_firewood_m3_per_ha', 0)
        config_with_stats['total_growing_stock_m3_per_ha'] = stats.get('total_growing_stock_m3_per_ha', 0)
        config_with_stats['volume_per_ha'] = stats.get('volume_per_ha', 0)
        config_with_stats['total_sample_plots'] = stats.get('total_sample_plots', 0)
        
        model.algorithm_config = config_with_stats

        db.commit()

    except Exception as e:
        logger.exception("synthetic tree model %s failed", model_id)
        # Mark as failed
        model.status = "failed"
        model.error_message = str(e)
        model.progress_percent = 0
        model.current_step = "Failed"
        db.commit()

    finally:
        db.close()


@router.post("/calculations/{calculation_id}/generate-tree-model", response_model=TreeModelResponse)
def generate_tree_model(
    calculation_id: UUID,
    request: GenerateTreeModelRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """
    Generate synthetic tree distribution model from canopy height data

    This endpoint starts a background job to generate individual tree points
    from 30m canopy height raster data combined with species proportions.

    **Processing Time:** 5-10 minutes for typical forests (100-500 ha)

    **Returns:**
    - Model ID for status tracking
    - Processing status (initially "processing")
    - Estimated tree count

    **Tree Criteria:**
    - Minimum DBH: 10cm (commercial inventory threshold)
    - Minimum Height: 5m
    - No regeneration/poles included

    **Output:** GPKG file with tree points and attributes
    """
    # Get calculation
    calculation = db.query(Calculation).filter(Calculation.id == calculation_id).first()
    if not calculation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=CalculationErrors.NOT_FOUND
        )

    # Check permissions
    if calculation.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have permission to access this calculation"
        )

    # Check if calculation has required data
    if not calculation.boundary_geom:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Calculation has no boundary geometry"
        )

    result_data = calculation.result_data or {}
    if not result_data.get('potential_species'):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Calculation has no species data. Run analysis first."
        )

    # Check if model already exists and is processing
    existing = db.query(SyntheticTreeModel).filter(
        SyntheticTreeModel.calculation_id == calculation_id,
        SyntheticTreeModel.status == "processing"
    ).first()

    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Tree model generation already in progress (ID: {existing.id})"
        )

    # Prepare configuration
    config = request.config.model_dump() if request.config else {}

    # Create model record
    model = SyntheticTreeModel(
        calculation_id=calculation_id,
        user_id=current_user.id,
        model_version="v1.0",
        algorithm_config=config,
        status="processing",
        progress_percent=0,
        current_step="Queued"
    )

    db.add(model)
    db.commit()
    db.refresh(model)

    # Start background generation
    from ..core.config import settings
    background_tasks.add_task(
        background_tree_generation,
        model_id=model.id,
        calculation_id=calculation_id,
        config=config,
        db_url=settings.DATABASE_URL
    )

    return model


@router.get("/tree-models/{model_id}", response_model=TreeModelResponse)
def get_tree_model(
    model_id: UUID,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """
    Get tree model status and statistics

    Use this endpoint to poll generation progress.

    **Status values:**
    - `processing`: Generation in progress (check progress_percent)
    - `completed`: Ready for download
    - `failed`: Generation failed (see error_message)
    """
    model = db.query(SyntheticTreeModel).filter(SyntheticTreeModel.id == model_id).first()

    if not model:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tree model not found"
        )

    # Check permissions
    if model.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have permission to access this model"
        )

    return model


@router.get("/calculations/{calculation_id}/tree-models", response_model=TreeModelListResponse)
def list_tree_models(
    calculation_id: UUID,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """
    List all tree models for a calculation

    Returns all generated models (processing, completed, and failed)
    """
    # Check calculation permissions
    calculation = db.query(Calculation).filter(Calculation.id == calculation_id).first()
    if not calculation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=CalculationErrors.NOT_FOUND
        )

    if calculation.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Permission denied"
        )

    # Get models
    models = db.query(SyntheticTreeModel).filter(
        SyntheticTreeModel.calculation_id == calculation_id
    ).order_by(SyntheticTreeModel.created_at.desc()).all()

    return {
        "models": models,
        "total_count": len(models)
    }


@router.get("/tree-models/{model_id}/download")
def download_tree_model(
    model_id: UUID,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """
    Download tree model GPKG file

    Returns the generated GPKG file containing synthetic tree points.

    **File Format:** GeoPackage (.gpkg)
    **Coordinate System:** EPSG:4326 (WGS84)
    **Geometry:** Point
    **Attributes:**
    - tree_id, species_code, species_scientific, species_local
    - species_role, height_m, dbh_cm, tree_class
    - canopy_height_source, forest_type, block_name
    - generated_date, model_version, notes

    **IMPORTANT DISCLAIMER:**
    This file contains SYNTHETIC/MODELED data, NOT ground survey results.
    For planning purposes only. Field verification required.
    """
    model = db.query(SyntheticTreeModel).filter(SyntheticTreeModel.id == model_id).first()

    if not model:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tree model not found"
        )

    # Check permissions
    if model.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Permission denied"
        )

    # Check status
    if model.status != "completed":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Model generation not completed. Status: {model.status}"
        )

    # Check file exists
    if not model.file_path or not os.path.exists(model.file_path):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="GPKG file not found"
        )

    # Get forest name from calculation for live filename generation
    calc = db.query(Calculation).filter(Calculation.id == model.calculation_id).first()
    forest_name = calc.forest_name if calc and calc.forest_name else "forest"

    from app.utils.file_export import build_disposition
    _, disposition = build_disposition(forest_name, "TreeModel", "SyntheticTrees", "gpkg")

    return FileResponse(
        path=model.file_path,
        filename=model.gpkg_filename,
        media_type="application/geopackage+sqlite3",
        headers={
            "Content-Disposition": disposition
        }
    )



@router.get("/tree-models/{model_id}/download-excel")
def download_tree_model_excel(
    model_id: UUID,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """
    Download tree model Excel file (regulation format)

    Returns the generated Excel file containing synthetic tree points
    in Forest Regulation 2079 standard format.

    **File Format:** Excel 2007+ (.xlsx)

    **Regulation Format Columns:**
    - fid, block_name, sample_plot_number
    - regen_species_scientific, regen_dbh, regen_count
    - sapling_species_scientific, sapling_dbh_cm, sapling_count
    - pole_species_scientific, pole_dbh_cm, pole_height_m, pole_class
    - tree_species_scientific, tree_dbh_cm, tree_height_m, tree_class
    - longitude, latitude
    """
    model = db.query(SyntheticTreeModel).filter(SyntheticTreeModel.id == model_id).first()

    if not model:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tree model not found"
        )

    # Check user authorization
    if model.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to download this tree model"
        )

    # Check status
    if model.status != "completed":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Tree model generation not completed"
        )

    # Check file exists
    if not model.excel_path or not os.path.exists(model.excel_path):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Excel file not found"
        )

    # Get forest name from calculation for live filename generation
    calc = db.query(Calculation).filter(Calculation.id == model.calculation_id).first()
    forest_name = calc.forest_name if calc and calc.forest_name else "forest"

    from app.utils.file_export import build_disposition
    _, disposition = build_disposition(forest_name, "TreeModel", "SyntheticTrees", "xlsx")

    return FileResponse(
        path=model.excel_path,
        filename=model.excel_filename,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": disposition
        }
    )


@router.delete("/tree-models/{model_id}")
def delete_tree_model(
    model_id: UUID,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """
    Delete tree model and associated GPKG file

    Removes the model record and deletes the generated file from disk.
    """
    model = db.query(SyntheticTreeModel).filter(SyntheticTreeModel.id == model_id).first()

    if not model:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tree model not found"
        )

    # Check permissions
    if model.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Permission denied"
        )

    # Delete files (GPKG + Excel) if they exist
    for path_attr in ['file_path', 'excel_path']:
        filepath = getattr(model, path_attr, None)
        if filepath and os.path.exists(filepath):
            try:
                os.remove(filepath)
            except Exception as e:
                logger.warning(f"Could not delete {filepath}: {e}")

    # Delete record
    db.delete(model)
    db.commit()

    return {
        "success": True,
        "message": f"Tree model {model_id} deleted successfully"
    }


@router.get(
    "/calculations/{calculation_id}/tree-model/clusters",
    summary="Tree cluster tile (U05)",
    description=(
        "Return tree clusters (z<18) or individual trees (z>=18) for ONE "
        "Web-Mercator tile (z,x,y). The bbox is ALWAYS derived server-side so "
        "the cache key (calc_id, geom_epoch, x, y, z) is unambiguous. "
        "Rate-limited at 30 req/min."
    ),
    responses={
        403: {"description": "Not authorized to access this calculation"},
        429: {"description": "Rate limit exceeded (30/min, burst 10)"},
    },
)
@limiter.limit("30/minute")
def get_tree_clusters(
    calculation_id: UUID,
    z: int = Query(..., ge=0, le=24),
    x: int = Query(...),
    y: int = Query(...),
    request: Request = None,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """U05 — server-side tile clustering for `inventory_trees`.

    NOTE: this is NOT part of the synthetic-tree-model feature; it serves the
    live inventory trees for the unified map shell (plan U05).
    """
    # Ownership gate (mirrors generate_tree_model / workspace._require_calculation_access).
    calculation = db.query(Calculation).filter(Calculation.id == calculation_id).first()
    if not calculation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=CalculationErrors.NOT_FOUND,
        )
    if calculation.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have permission to access this calculation",
        )

    # Out-of-range tiles (degenerate bbox) → empty, not 500.
    n = 2 ** z
    if not (0 <= x < n and 0 <= y < n):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Tile (x,y) out of range for zoom z",
        )

    return cluster_inventory_trees(db, str(calculation_id), z, x, y)
