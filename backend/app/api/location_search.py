"""
Location search API for administrative boundaries.
Helps users find areas to digitize by searching district/municipality/ward.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import text
from typing import List, Optional
from pydantic import BaseModel

from app.core.database import get_db

router = APIRouter()


# Response models
class District(BaseModel):
    """District name response model."""
    name: str


class Municipality(BaseModel):
    """Municipality name with district response model."""
    name: str
    district: str


class Ward(BaseModel):
    """Ward detail response model."""
    id: int
    ward: int
    municipality: str
    district: str
    geometry: Optional[dict] = None
    bounds: Optional[List[float]] = None  # [minLon, minLat, maxLon, maxLat]


class LocationSearchResult(BaseModel):
    """Search result for text-based location search."""
    id: int
    display_name: str
    district: str
    municipality: str
    ward: int
    bounds: List[float]


@router.get("/districts", response_model=List[District])
def get_districts(db: Session = Depends(get_db)):
    """Get all distinct districts"""
    query = text("""
        SELECT DISTINCT district as name
        FROM admin.ward
        WHERE district IS NOT NULL
        ORDER BY district
    """)

    result = db.execute(query)
    districts = [
        District(name=row.name or "")
        for row in result
    ]

    return districts


@router.get("/municipalities", response_model=List[Municipality])
def get_municipalities(
    district: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """Get municipalities, optionally filtered by district"""
    query_text = """
        SELECT DISTINCT
            municipality as name,
            district
        FROM admin.ward
        WHERE municipality IS NOT NULL
    """

    params = {}
    if district:
        query_text += " AND district = :district"
        params["district"] = district

    query_text += " ORDER BY municipality"

    query = text(query_text)
    result = db.execute(query, params) if params else db.execute(query)

    municipalities = [
        Municipality(
            name=row.name or "",
            district=row.district or ""
        )
        for row in result
    ]

    return municipalities


@router.get("/wards", response_model=List[Ward])
def get_wards(
    municipality: Optional[str] = None,
    district: Optional[str] = None,
    include_geometry: bool = False,
    db: Session = Depends(get_db)
):
    """Get wards, optionally filtered by municipality/district"""

    # Build geometry selection
    geom_select = ""
    if include_geometry:
        geom_select = """
            , ST_AsGeoJSON(geom)::json as geometry
            , ARRAY[
                ST_XMin(geom), ST_YMin(geom),
                ST_XMax(geom), ST_YMax(geom)
              ] as bounds
        """

    query_text = f"""
        SELECT
            id,
            ward,
            municipality,
            district
            {geom_select}
        FROM admin.ward
        WHERE id IS NOT NULL
    """

    params = {}
    if district:
        query_text += " AND district = :district"
        params["district"] = district
    if municipality:
        query_text += " AND municipality = :municipality"
        params["municipality"] = municipality

    query_text += " ORDER BY municipality, ward"

    query = text(query_text)
    result = db.execute(query, params) if params else db.execute(query)

    wards = []
    for row in result:
        ward_data = {
            "id": row.id,
            "ward": row.ward,
            "municipality": row.municipality or "",
            "district": row.district or ""
        }

        if include_geometry:
            ward_data["geometry"] = row.geometry if hasattr(row, 'geometry') else None
            ward_data["bounds"] = list(row.bounds) if hasattr(row, 'bounds') and row.bounds else None

        wards.append(Ward(**ward_data))

    return wards


@router.get("/search", response_model=List[LocationSearchResult])
def search_location(
    q: str,
    limit: int = 10,
    db: Session = Depends(get_db)
):
    """
    Text search across all administrative levels.
    Searches district, municipality names.
    """
    search_term = f"%{q}%"

    query = text("""
        SELECT
            id,
            district || ', ' || municipality || ', Ward ' || ward as display_name,
            district,
            municipality,
            ward,
            ARRAY[
                ST_XMin(geom), ST_YMin(geom),
                ST_XMax(geom), ST_YMax(geom)
            ] as bounds
        FROM admin.ward
        WHERE
            LOWER(district) LIKE LOWER(:search)
            OR LOWER(municipality) LIKE LOWER(:search)
        ORDER BY
            CASE
                WHEN LOWER(municipality) LIKE LOWER(:search) THEN 1
                WHEN LOWER(district) LIKE LOWER(:search) THEN 2
                ELSE 3
            END,
            municipality, ward
        LIMIT :limit
    """)

    result = db.execute(query, {"search": search_term, "limit": limit})

    results = [
        LocationSearchResult(
            id=row.id,
            display_name=row.display_name,
            district=row.district or "",
            municipality=row.municipality or "",
            ward=row.ward,
            bounds=list(row.bounds) if row.bounds else [0, 0, 0, 0]
        )
        for row in result
    ]

    return results


@router.get("/ward/{ward_id}/geometry")
def get_ward_geometry(ward_id: int, db: Session = Depends(get_db)):
    """Get ward boundary geometry for display on map"""
    query = text("""
        SELECT
            ST_AsGeoJSON(geom)::json as geometry,
            ARRAY[ST_XMin(geom), ST_YMin(geom), ST_XMax(geom), ST_YMax(geom)] as bounds,
            district, municipality, ward
        FROM admin.ward
        WHERE id = :ward_id
    """)

    result = db.execute(query, {"ward_id": ward_id}).first()

    if not result:
        raise HTTPException(status_code=404, detail="Ward not found")

    return {
        "geometry": result.geometry,
        "bounds": list(result.bounds) if result.bounds else None,
        "district": result.district,
        "municipality": result.municipality,
        "ward": result.ward
    }
