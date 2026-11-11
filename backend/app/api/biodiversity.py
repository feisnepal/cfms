"""
Biodiversity species inventory API endpoints
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import or_, and_, func
from typing import List, Optional
from uuid import UUID

from ..core.database import get_db
from ..core.idempotent_route import IdempotentRoute
from ..core.exceptions import i18n_success
from ..models import BiodiversitySpecies, CalculationBiodiversity, Calculation, User
from ..schemas.biodiversity import (
    BiodiversitySpeciesResponse,
    BiodiversitySpeciesListResponse,
    CalculationBiodiversityCreate,
    CalculationBiodiversityBulkCreate,
    CalculationBiodiversityResponse,
    CalculationBiodiversitySummary,
    CalculationBiodiversityUpdate,
)
from app.core.errors import CalculationErrors
from ..utils.auth import get_current_user
from ..utils.authz import is_owner_or_admin

def _invalidate_op_cache(db: Session, calculation_id: UUID):
    from app.models.op_data_cache import OpDataCache
    db.query(OpDataCache).filter(
        OpDataCache.calculation_id == calculation_id
    ).delete(synchronize_session=False)

router = APIRouter(prefix="/biodiversity", route_class=IdempotentRoute)


@router.get("/species", response_model=BiodiversitySpeciesListResponse)
def get_species_list(
    category: Optional[str] = Query(None, description="Filter by category: vegetation, animal"),
    sub_category: Optional[str] = Query(None, description="Filter by sub-category"),
    search: Optional[str] = Query(None, description="Search in names (Nepali, English, Scientific)"),
    iucn_status: Optional[str] = Query(None, description="Filter by IUCN status"),
    cites_listed: Optional[bool] = Query(None, description="Filter CITES listed species"),
    is_invasive: Optional[bool] = Query(None, description="Filter invasive species"),
    is_protected: Optional[bool] = Query(None, description="Filter protected species"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db)
):
    """
    Get paginated list of biodiversity species with filters
    """
    query = db.query(BiodiversitySpecies)

    # Apply filters
    if category:
        query = query.filter(BiodiversitySpecies.category == category)

    if sub_category:
        query = query.filter(BiodiversitySpecies.sub_category == sub_category)

    if search:
        search_term = f"%{search}%"
        query = query.filter(
            or_(
                BiodiversitySpecies.nepali_name.ilike(search_term),
                BiodiversitySpecies.english_name.ilike(search_term),
                BiodiversitySpecies.scientific_name.ilike(search_term)
            )
        )

    if iucn_status:
        query = query.filter(BiodiversitySpecies.iucn_status == iucn_status)

    if cites_listed is not None:
        if cites_listed:
            query = query.filter(BiodiversitySpecies.cites_appendix.isnot(None))
            query = query.filter(BiodiversitySpecies.cites_appendix != 'Not listed')
        else:
            query = query.filter(
                or_(
                    BiodiversitySpecies.cites_appendix.is_(None),
                    BiodiversitySpecies.cites_appendix == 'Not listed'
                )
            )

    if is_invasive is not None:
        query = query.filter(BiodiversitySpecies.is_invasive == is_invasive)

    if is_protected is not None:
        query = query.filter(BiodiversitySpecies.is_protected == is_protected)

    # Get total count
    total = query.count()

    # Apply pagination
    offset = (page - 1) * page_size
    species = query.order_by(BiodiversitySpecies.category, BiodiversitySpecies.nepali_name)\
                   .offset(offset)\
                   .limit(page_size)\
                   .all()

    total_pages = (total + page_size - 1) // page_size

    return {
        "items": species,
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": total_pages
    }


@router.get("/species/{species_id}", response_model=BiodiversitySpeciesResponse)
def get_species_detail(
    species_id: UUID,
    db: Session = Depends(get_db)
):
    """Get single species details"""
    species = db.query(BiodiversitySpecies).filter(BiodiversitySpecies.id == species_id).first()
    if not species:
        raise HTTPException(status_code=404, detail="Species not found")
    return species


@router.get("/calculations/{calculation_id}/species", response_model=CalculationBiodiversitySummary)
def get_calculation_biodiversity(
    calculation_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get all biodiversity species selected for a calculation
    """
    # Verify calculation exists and user has access
    calculation = db.query(Calculation).filter(Calculation.id == calculation_id).first()
    if not calculation:
        raise HTTPException(status_code=404, detail=CalculationErrors.NOT_FOUND)

    # Check if user owns this calculation (or is admin)
    if not is_owner_or_admin(calculation, current_user):
        raise HTTPException(status_code=403, detail="Not authorized to access this calculation")

    # Get all biodiversity records
    records = db.query(CalculationBiodiversity)\
                .filter(CalculationBiodiversity.calculation_id == calculation_id)\
                .all()

    # Calculate counts
    total_species = len(records)
    vegetation_count = sum(1 for r in records if r.species.category == 'vegetation')
    animal_count = sum(1 for r in records if r.species.category == 'animal')
    protected_count = sum(1 for r in records if r.species.is_protected or r.species.iucn_status in ['CR', 'EN', 'VU'])
    invasive_count = sum(1 for r in records if r.species.is_invasive)

    return {
        "calculation_id": calculation_id,
        "total_species": total_species,
        "vegetation_count": vegetation_count,
        "animal_count": animal_count,
        "protected_species_count": protected_count,
        "invasive_species_count": invasive_count,
        "species": records
    }


@router.post("/calculations/{calculation_id}/species", response_model=CalculationBiodiversityResponse)
def add_species_to_calculation(
    calculation_id: UUID,
    biodiversity_data: CalculationBiodiversityCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Add a single species to calculation biodiversity inventory
    """
    # Verify calculation exists and user has access
    calculation = db.query(Calculation).filter(Calculation.id == calculation_id).first()
    if not calculation:
        raise HTTPException(status_code=404, detail=CalculationErrors.NOT_FOUND)

    if not is_owner_or_admin(calculation, current_user):
        raise HTTPException(status_code=403, detail="Not authorized to access this calculation")

    # Verify species exists
    species = db.query(BiodiversitySpecies).filter(BiodiversitySpecies.id == biodiversity_data.species_id).first()
    if not species:
        raise HTTPException(status_code=404, detail="Species not found")

    # Check if already exists
    existing = db.query(CalculationBiodiversity)\
                 .filter(
                     and_(
                         CalculationBiodiversity.calculation_id == calculation_id,
                         CalculationBiodiversity.species_id == biodiversity_data.species_id
                     )
                 ).first()

    if existing:
        raise HTTPException(status_code=400, detail="Species already added to this calculation")

    # Create new record
    new_record = CalculationBiodiversity(
        calculation_id=calculation_id,
        species_id=biodiversity_data.species_id,
        presence_status=biodiversity_data.presence_status,
        abundance=biodiversity_data.abundance,
        notes=biodiversity_data.notes,
        photo_url=biodiversity_data.photo_url,
        latitude=biodiversity_data.latitude,
        longitude=biodiversity_data.longitude,
        recorded_by=current_user.id
    )

    db.add(new_record)
    db.commit()
    db.refresh(new_record)

    return new_record


@router.post("/calculations/{calculation_id}/species/bulk")
def bulk_add_species(
    calculation_id: UUID,
    bulk_data: CalculationBiodiversityBulkCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Bulk add multiple species to calculation
    """
    # Verify calculation exists and user has access
    calculation = db.query(Calculation).filter(Calculation.id == calculation_id).first()
    if not calculation:
        raise HTTPException(status_code=404, detail=CalculationErrors.NOT_FOUND)

    if not is_owner_or_admin(calculation, current_user):
        raise HTTPException(status_code=403, detail="Not authorized")

    # Verify all species exist
    species_ids = bulk_data.species_ids
    species_count = db.query(BiodiversitySpecies).filter(BiodiversitySpecies.id.in_(species_ids)).count()
    if species_count != len(species_ids):
        raise HTTPException(status_code=404, detail="One or more species not found")

    # Get existing records to avoid duplicates
    existing_ids = db.query(CalculationBiodiversity.species_id)\
                     .filter(CalculationBiodiversity.calculation_id == calculation_id)\
                     .filter(CalculationBiodiversity.species_id.in_(species_ids))\
                     .all()
    existing_ids = {row[0] for row in existing_ids}

    # Create new records for non-existing species
    new_records = []
    for species_id in species_ids:
        if species_id not in existing_ids:
            new_record = CalculationBiodiversity(
                calculation_id=calculation_id,
                species_id=species_id,
                presence_status=bulk_data.presence_status,
                notes=bulk_data.notes,
                recorded_by=current_user.id
            )
            new_records.append(new_record)

    if new_records:
        db.add_all(new_records)
        db.commit()
        _invalidate_op_cache(db, calculation_id)

    return {
        "added": len(new_records),
        "skipped": len(existing_ids),
        "total": len(species_ids)
    }


class InventoryImportRequest(BaseModel):
    scientific_names: List[str]


def _calc_for_owner(db: Session, calculation_id: UUID, user: User) -> Calculation:
    calculation = db.query(Calculation).filter(Calculation.id == calculation_id).first()
    if not calculation:
        raise HTTPException(status_code=404, detail=CalculationErrors.NOT_FOUND)
    if not is_owner_or_admin(calculation, user):
        raise HTTPException(status_code=403, detail="Not authorized")
    return calculation


@router.get("/calculations/{calculation_id}/species/from-inventory")
def preview_species_from_inventory(
    calculation_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """The unique tree species of this forest's field inventory and what adding them would do (read-only): each is already
    recorded, in the Biodiversity list, new (only in ``tree_species_coefficients``) or unresolved."""
    from ..services import biodiversity_inventory_import as imp

    _calc_for_owner(db, calculation_id, current_user)
    return imp.preview(db, calculation_id)


@router.post("/calculations/{calculation_id}/species/from-inventory")
def add_species_from_inventory(
    calculation_id: UUID,
    body: InventoryImportRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Record the chosen inventory species. Species only in the coefficient table get a Biodiversity entry built from it; species
    already recorded are skipped and their abundance / notes are never overwritten."""
    from ..services import biodiversity_inventory_import as imp

    _calc_for_owner(db, calculation_id, current_user)
    result = imp.apply(db, calculation_id, body.scientific_names, current_user.id)
    if result["added"]:
        _invalidate_op_cache(db, calculation_id)
        db.commit()
    return result


@router.post("/calculations/{calculation_id}/species/sync-from-inventory")
def sync_species_from_inventory(
    calculation_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Automatically list the field inventory's unique tree species in this forest's Biodiversity record. Runs once per processed
    inventory (a species removed afterwards stays removed); a no-op when there is no inventory or it was already listed."""
    from ..services import biodiversity_inventory_import as imp

    _calc_for_owner(db, calculation_id, current_user)
    result = imp.sync_from_inventory(db, calculation_id, current_user.id)
    if result.get("added"):
        _invalidate_op_cache(db, calculation_id)
        db.commit()
    return result


@router.delete("/calculations/{calculation_id}/species/{species_id}")
def remove_species_from_calculation(
    calculation_id: UUID,
    species_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Remove a species from calculation biodiversity inventory
    """
    # Verify calculation exists and user has access
    calculation = db.query(Calculation).filter(Calculation.id == calculation_id).first()
    if not calculation:
        raise HTTPException(status_code=404, detail=CalculationErrors.NOT_FOUND)

    if not is_owner_or_admin(calculation, current_user):
        raise HTTPException(status_code=403, detail="Not authorized")

    # Find and delete record
    record = db.query(CalculationBiodiversity)\
               .filter(
                   and_(
                       CalculationBiodiversity.calculation_id == calculation_id,
                       CalculationBiodiversity.species_id == species_id
                   )
               ).first()

    if not record:
        raise HTTPException(status_code=404, detail="Species not found in this calculation")

    db.delete(record)
    db.commit()
    _invalidate_op_cache(db, calculation_id)

    return {**i18n_success("success.species_removed")}


@router.get("/categories")
def get_categories(db: Session = Depends(get_db)):
    """
    Get available categories and sub-categories with counts
    """
    # Get category counts
    categories = db.query(
        BiodiversitySpecies.category,
        BiodiversitySpecies.sub_category,
        func.count(BiodiversitySpecies.id).label('count')
    ).group_by(
        BiodiversitySpecies.category,
        BiodiversitySpecies.sub_category
    ).all()

    # Organize into hierarchy
    result = {}
    for category, sub_category, count in categories:
        if category not in result:
            result[category] = {"total": 0, "sub_categories": {}}

        result[category]["total"] += count

        if sub_category:
            result[category]["sub_categories"][sub_category] = count

    return result
