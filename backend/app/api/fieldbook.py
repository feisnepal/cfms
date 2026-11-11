"""
Fieldbook API endpoints for boundary vertex extraction and 20m interpolation.
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import Optional
from uuid import UUID

from app.core.database import get_db
from app.core.idempotent_route import IdempotentRoute
from app.utils.auth import get_current_user
from app.models.user import User
from app.models.calculation import Calculation
from app.models.fieldbook import Fieldbook
from app.schemas.fieldbook import (
    FieldbookGenerateRequest,
    FieldbookGenerateResponse,
    FieldbookListResponse,
    FieldbookPoint,
    FieldbookPointUpdate,
    FieldbookExportFormat
)
from app.core.errors import CalculationErrors
from app.services.fieldbook import (
    generate_fieldbook_points,
    update_utm_and_elevation,
    get_elevation_stats
)
from app.services.fieldbook_record import merge_remark
from app.services.export import (
    export_fieldbook_csv,
    export_fieldbook_excel,
    export_fieldbook_gpx,
    export_fieldbook_geojson
)
from fastapi.responses import StreamingResponse, JSONResponse
import io

router = APIRouter(route_class=IdempotentRoute)


@router.post("/{calculation_id}/fieldbook/generate", response_model=FieldbookGenerateResponse)
def generate_fieldbook(
    calculation_id: UUID,
    request: FieldbookGenerateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Generate fieldbook from calculation boundary.

    Extracts vertices and creates interpolated points at specified intervals.
    Optionally extracts elevation from DEM raster.
    """
    # Verify calculation exists and belongs to user
    calculation = db.query(Calculation).filter(
        Calculation.id == calculation_id,
        Calculation.user_id == current_user.id
    ).first()

    if not calculation:
        raise HTTPException(status_code=404, detail=CalculationErrors.NOT_FOUND)

    if not calculation.boundary_geom:
        raise HTTPException(status_code=400, detail="Calculation has no boundary geometry")

    # Check if fieldbook already exists
    existing = db.query(Fieldbook).filter(
        Fieldbook.calculation_id == calculation_id
    ).first()

    if existing:
        raise HTTPException(
            status_code=400,
            detail="Fieldbook already exists for this calculation. Delete it first to regenerate."
        )

    try:
        # Generate fieldbook points (includes elevation extraction if requested)
        summary = generate_fieldbook_points(
            db=db,
            calculation_id=calculation_id,
            interpolation_distance=request.interpolation_distance_meters,
            extract_elevation=request.extract_elevation,
            calculate_reference=request.calculate_reference
        )

        db.commit()

        return summary

    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to generate fieldbook: {str(e)}")


@router.get("/{calculation_id}/fieldbook")
def list_fieldbook_points(
    calculation_id: UUID,
    format: Optional[str] = Query(None, description="Export format: csv, excel, gpx, geojson"),
    include_topographic: bool = Query(False, description="Include topographic features (ridge/river data)"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    List all fieldbook points for a calculation.

    Optionally export in CSV, Excel, GPX, or GeoJSON format.
    Can include topographic features (nearest ridge/river) in JSON response.
    """
    # Verify calculation exists and belongs to user
    calculation = db.query(Calculation).filter(
        Calculation.id == calculation_id,
        Calculation.user_id == current_user.id
    ).first()

    if not calculation:
        raise HTTPException(status_code=404, detail=CalculationErrors.NOT_FOUND)

    from app.utils.file_export import build_disposition

    # Handle export formats
    if format:
        try:
            forest_name = calculation.forest_name
            ext_map = {"csv": "csv", "excel": "xlsx", "gpx": "gpx", "geojson": "geojson"}
            ext = ext_map.get(format, format)

            if format == "csv":
                csv_data = export_fieldbook_csv(db, calculation_id)
                _, disposition = build_disposition(forest_name, "Fieldbook", "FieldData", "csv")
                return StreamingResponse(
                    io.BytesIO(csv_data),
                    media_type="text/csv",
                    headers={"Content-Disposition": disposition}
                )

            elif format == "excel":
                excel_data = export_fieldbook_excel(db, calculation_id)
                _, disposition = build_disposition(forest_name, "Fieldbook", "FieldData", "xlsx")
                return StreamingResponse(
                    io.BytesIO(excel_data),
                    media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": disposition}
                )

            elif format == "gpx":
                gpx_data = export_fieldbook_gpx(db, calculation_id)
                _, disposition = build_disposition(forest_name, "Fieldbook", "FieldData", "gpx")
                return StreamingResponse(
                    io.BytesIO(gpx_data),
                    media_type="application/gpx+xml",
                    headers={"Content-Disposition": disposition}
                )

            elif format == "geojson":
                geojson_data = export_fieldbook_geojson(db, calculation_id)
                return JSONResponse(content=geojson_data)

        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Export failed: {str(e)}")

    # Return JSON list
    points = db.query(Fieldbook).filter(
        Fieldbook.calculation_id == calculation_id
    ).order_by(Fieldbook.point_number).all()

    if not points:
        return FieldbookListResponse(points=[], total_count=0)

    # Enrich points with the nearest ridge/river if requested -- the SAME lookup (same buffer, same rounding) the
    # CSV / Excel / GeoJSON / GPX exports use, so the tab and the files cannot name different features.
    point_list = [FieldbookPoint.model_validate(p).model_dump() for p in points]
    if include_topographic and points:
        from app.services.fieldbook_record import topography_for

        topo = topography_for(db, calculation_id, points)
        for p, point_dict in zip(points, point_list):
            t_ = topo.get(p.id) or {}
            point_dict['nearest_feature'] = t_.get('nearest_feature')
            point_dict['feature_type'] = t_.get('nearest_feature_type')
            point_dict['distance_to_feature'] = t_.get('nearest_feature_distance_m')
            point_dict['direction_to_feature'] = t_.get('nearest_feature_direction')

    outer = [p for p in points if p.boundary_class == 'outer']
    from app.services.fieldbook_lines import lines_from_points
    return {
        "points": point_list,
        "total_count": len(points),
        # The grouping: outer rings are closed, internal edges are open (see services/fieldbook_lines.py)
        "lines": [
            {k: ln[k] for k in ("id", "kind", "closed", "labels", "length_m")} for ln in lines_from_points(points)
        ],
        # Summary the Field Book tab's cards read (they used to show "-": the list never carried them)
        "total_vertices": sum(1 for p in points if p.point_type == 'vertex'),
        "interpolated_points": sum(1 for p in points if p.point_type == 'interpolated'),
        "outer_points": len(outer),
        "internal_points": sum(1 for p in points if p.boundary_class == 'internal'),
        "junction_points": sum(1 for p in points if p.is_junction),
        # The forest's outer boundary length; a book made before outer/internal existed has no class,
        # so fall back to the whole-run sum it always showed.
        "total_perimeter_meters": round(
            sum(float(p.distance_to_next or 0) for p in (outer or points)), 2
        ),
    }


@router.get("/{calculation_id}/fieldbook/{point_number}", response_model=FieldbookPoint)
def get_fieldbook_point(
    calculation_id: UUID,
    point_number: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Get a specific fieldbook point by point number.
    """
    # Verify calculation belongs to user
    calculation = db.query(Calculation).filter(
        Calculation.id == calculation_id,
        Calculation.user_id == current_user.id
    ).first()

    if not calculation:
        raise HTTPException(status_code=404, detail=CalculationErrors.NOT_FOUND)

    point = db.query(Fieldbook).filter(
        Fieldbook.calculation_id == calculation_id,
        Fieldbook.point_number == point_number
    ).first()

    if not point:
        raise HTTPException(status_code=404, detail="Point not found")

    return FieldbookPoint.model_validate(point)


@router.patch("/{calculation_id}/fieldbook/{point_number}", response_model=FieldbookPoint)
def update_fieldbook_point(
    calculation_id: UUID,
    point_number: int,
    update_data: FieldbookPointUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Update fieldbook point (remarks, verification status).
    """
    # Verify calculation belongs to user
    calculation = db.query(Calculation).filter(
        Calculation.id == calculation_id,
        Calculation.user_id == current_user.id
    ).first()

    if not calculation:
        raise HTTPException(status_code=404, detail=CalculationErrors.NOT_FOUND)

    point = db.query(Fieldbook).filter(
        Fieldbook.calculation_id == calculation_id,
        Fieldbook.point_number == point_number
    ).first()

    if not point:
        raise HTTPException(status_code=404, detail="Point not found")

    # Update fields
    if update_data.remarks is not None:
        point.remarks = merge_remark(point, update_data.remarks)
    if update_data.is_verified is not None:
        point.is_verified = update_data.is_verified

    try:
        db.commit()
        db.refresh(point)
        return FieldbookPoint.model_validate(point)
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Update failed: {str(e)}")


@router.delete("/{calculation_id}/fieldbook")
def delete_fieldbook(
    calculation_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Delete all fieldbook points for a calculation.
    """
    # Verify calculation belongs to user
    calculation = db.query(Calculation).filter(
        Calculation.id == calculation_id,
        Calculation.user_id == current_user.id
    ).first()

    if not calculation:
        raise HTTPException(status_code=404, detail=CalculationErrors.NOT_FOUND)

    try:
        deleted_count = db.query(Fieldbook).filter(
            Fieldbook.calculation_id == calculation_id
        ).delete()

        db.commit()

        return {
            "success": True,
            "message": f"Deleted {deleted_count} fieldbook points",
            "deleted_count": deleted_count
        }
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Delete failed: {str(e)}")
