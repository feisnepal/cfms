"""
Species API endpoints for testing species matcher
"""

from fastapi import APIRouter, HTTPException, Query, Depends
from typing import List, Optional
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import text

from app.services.species_matcher import get_species_matcher
from app.core.database import get_db


router = APIRouter()


class SpeciesIdentifyResponse(BaseModel):
    """Response for species identification"""
    success: bool
    species: Optional[dict] = None
    match_type: Optional[str] = None
    confidence: Optional[float] = None
    matched_field: Optional[str] = None
    message: Optional[str] = None


class SpeciesSuggestionResponse(BaseModel):
    """Response for species suggestions"""
    suggestions: List[dict]
    count: int


class BatchIdentifyRequest(BaseModel):
    """Request for batch identification"""
    species_list: List[str]


class BatchIdentifyResponse(BaseModel):
    """Response for batch identification"""
    results: List[dict]
    total: int
    matched: int
    unmatched: int


@router.get("/identify", response_model=SpeciesIdentifyResponse)
async def identify_species(q: str = Query(..., description="Species name, code, or abbreviation")):
    """
    Identify a species from any format

    Supports:
    - Numeric codes (1, 18, 5)
    - Scientific names (Shorea robusta, Alnus nepalensis)
    - Abbreviated codes (sho, rob, sho rob, sho/rob)
    - Nepali Unicode (साल, उत्तिस, खयर)
    - Nepali Romanized (Sal, Uttis, Khayar)
    - Common names (Khair, Utis)

    Examples:
    - /api/species/identify?q=18
    - /api/species/identify?q=sho
    - /api/species/identify?q=sho rob
    - /api/species/identify?q=साल
    """
    matcher = get_species_matcher()
    result = matcher.identify(q)

    if result:
        return SpeciesIdentifyResponse(
            success=True,
            species=result["species"],
            match_type=result["match_type"],
            confidence=result["confidence"],
            matched_field=result["matched_field"]
        )
    else:
        return SpeciesIdentifyResponse(
            success=False,
            message=f"Species '{q}' not found"
        )


@router.get("/suggest", response_model=SpeciesSuggestionResponse)
async def suggest_species(
    q: str = Query(..., description="Partial species name"),
    limit: int = Query(5, ge=1, le=20, description="Maximum number of suggestions")
):
    """
    Get species suggestions for autocomplete

    Examples:
    - /api/species/suggest?q=sal
    - /api/species/suggest?q=pin&limit=3
    - /api/species/suggest?q=sho
    """
    matcher = get_species_matcher()
    suggestions = matcher.suggest(q, limit=limit)

    return SpeciesSuggestionResponse(
        suggestions=suggestions,
        count=len(suggestions)
    )


@router.post("/identify-batch", response_model=BatchIdentifyResponse)
async def identify_batch(request: BatchIdentifyRequest):
    """
    Identify multiple species at once

    Example request:
    {
        "species_list": ["18", "sho", "aln nep", "साल", "Sal"]
    }
    """
    matcher = get_species_matcher()
    results = matcher.identify_batch(request.species_list)

    matched = sum(1 for r in results if r is not None)
    unmatched = len(results) - matched

    return BatchIdentifyResponse(
        results=results,
        total=len(results),
        matched=matched,
        unmatched=unmatched
    )


@router.get("/all")
async def get_all_species():
    """
    Get all species in the database

    Returns list of all 23 species with all fields
    """
    matcher = get_species_matcher()
    all_species = matcher.get_all_species()

    return {
        "species": all_species,
        "total": len(all_species)
    }


@router.get("/search")
def search_species(
    q: str = Query("", description="Search query (scientific name, local name, or family)"),
    limit: int = Query(50, ge=1, le=200, description="Maximum results"),
    db: Session = Depends(get_db)
):
    """
    Search all species in tree_species_coefficients with full characteristics

    Supports searching by:
    - Scientific name (e.g., "Shorea robusta")
    - Local name (e.g., "Sal")
    - Family name (e.g., "Dipterocarpaceae")

    Returns species with all characteristics including:
    - Growth rate, altitude range, economic value
    - Main uses, nitrogen fixing, rarity status
    """
    query_text = text("""
        SELECT
            id,
            scientific_name,
            local_name,
            family,
            growth_rate,
            min_altitude_m,
            max_altitude_m,
            economic_value,
            main_uses,
            nitrogen_fixing,
            rarity_status,
            ecological_role
        FROM tree_species_coefficients
        WHERE
            LOWER(scientific_name) LIKE LOWER(:search)
            OR LOWER(local_name) LIKE LOWER(:search)
            OR LOWER(family) LIKE LOWER(:search)
        ORDER BY scientific_name
        LIMIT :limit
    """)

    search_pattern = f"%{q}%"
    results = db.execute(query_text, {"search": search_pattern, "limit": limit}).fetchall()

    species_list = []
    for r in results:
        species_list.append({
            "id": r.id,
            "scientific_name": r.scientific_name,
            "local_name": r.local_name or "Unknown",
            "family": r.family,
            "growth_rate": r.growth_rate,
            "min_altitude_m": r.min_altitude_m,
            "max_altitude_m": r.max_altitude_m,
            "economic_value": r.economic_value,
            "main_uses": r.main_uses,
            "nitrogen_fixing": r.nitrogen_fixing or False,
            "rarity_status": r.rarity_status or "Common",
            "ecological_role": r.ecological_role
        })

    return {
        "species": species_list,
        "count": len(species_list),
        "query": q
    }


@router.post("/validate-column")
async def validate_species_column(request: BatchIdentifyRequest):
    """
    Validate a column of species data (for CSV uploads)

    Returns detailed validation report with:
    - Matched species (high confidence)
    - Unmatched species (with suggestions)
    - Low confidence matches (need user confirmation)

    Example request:
    {
        "species_list": ["1", "साल", "Uttis", "Shisham", "XYZ", "", "18", "Pine"]
    }
    """
    matcher = get_species_matcher()
    validation = matcher.validate_species_column(request.species_list, min_confidence=0.6)

    return validation


@router.get("/{code}")
async def get_species_by_code(code: int):
    """
    Get species by numeric code

    Example:
    - /api/species/18 → Returns Shorea robusta
    """
    matcher = get_species_matcher()
    species = matcher.get_species_by_code(code)

    if species:
        return {
            "success": True,
            "species": species
        }
    else:
        raise HTTPException(status_code=404, detail=f"Species with code {code} not found")
