from app.core.errors import CalculationErrors
"""Map generation API endpoints (unused).

Provides endpoint routes for generating thematic map images (topographic,
forest type, canopy height, soil, forest health). These endpoints are not
currently registered in the app router and may be dead code.

Each endpoint returns a PNG image rendered via the map generation service.
"""

@router.get("/calculations/{calculation_id}/maps/topographic")
def generate_topographic_map_endpoint(
    calculation_id: UUID,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """
    Generate topographic map with elevation contours

    Returns PNG image (A5 size, 300 DPI) with elevation gradient
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

    if not calculation.boundary_geom:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Calculation has no boundary geometry"
        )

    try:
        # Convert boundary to GeoJSON
        geom_shape = wkb.loads(bytes(calculation.boundary_geom.data))
        geometry = mapping(geom_shape)

        # Generate map
        map_generator = get_map_generator()
        buffer = map_generator.generate_topographic_map(
            geometry=geometry,
            db_session=db,
            forest_name=calculation.forest_name or 'Community Forest',
            orientation='auto'
        )

        # Return as SVG image (preserves text shaping for Devanagari)
        return StreamingResponse(
            io.BytesIO(buffer.getvalue()),
            media_type="image/svg+xml",
            headers={"Content-Disposition": f"inline; filename=topographic_map_{calculation_id}.svg"}
        )

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error generating topographic map: {str(e)}"
        )


@router.get("/calculations/{calculation_id}/maps/forest_type")
def generate_forest_type_map_endpoint(
    calculation_id: UUID,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """
    Generate forest type map showing species classification

    Returns PNG image (A5 size, 300 DPI) with forest species
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

    if not calculation.boundary_geom:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Calculation has no boundary geometry"
        )

    try:
        # Convert boundary to GeoJSON
        geom_shape = wkb.loads(bytes(calculation.boundary_geom.data))
        geometry = mapping(geom_shape)

        # Generate map
        map_generator = get_map_generator()
        buffer = map_generator.generate_forest_type_map(
            geometry=geometry,
            db_session=db,
            forest_name=calculation.forest_name or 'Community Forest',
            orientation='auto'
        )

        # Return as SVG image (preserves text shaping for Devanagari)
        return StreamingResponse(
            io.BytesIO(buffer.getvalue()),
            media_type="image/svg+xml",
            headers={"Content-Disposition": f"inline; filename=forest_type_map_{calculation_id}.svg"}
        )

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error generating forest type map: {str(e)}"
        )


@router.get("/calculations/{calculation_id}/maps/canopy_height")
def generate_canopy_height_map_endpoint(
    calculation_id: UUID,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """
    Generate canopy height map showing forest structure

    Returns PNG image (A5 size, 300 DPI) with canopy height classes
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

    if not calculation.boundary_geom:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Calculation has no boundary geometry"
        )

    try:
        # Convert boundary to GeoJSON
        geom_shape = wkb.loads(bytes(calculation.boundary_geom.data))
        geometry = mapping(geom_shape)

        # Generate map
        map_generator = get_map_generator()
        buffer = map_generator.generate_canopy_height_map(
            geometry=geometry,
            db_session=db,
            forest_name=calculation.forest_name or 'Community Forest',
            orientation='auto'
        )

        # Return as SVG image (preserves text shaping for Devanagari)
        return StreamingResponse(
            io.BytesIO(buffer.getvalue()),
            media_type="image/svg+xml",
            headers={"Content-Disposition": f"inline; filename=canopy_height_map_{calculation_id}.svg"}
        )

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error generating canopy height map: {str(e)}"
        )


@router.get("/calculations/{calculation_id}/maps/soil")
def generate_soil_map_endpoint(
    calculation_id: UUID,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """
    Generate soil texture map from SoilGrids

    Returns PNG image (A5 size, 300 DPI) with soil texture classes
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

    if not calculation.boundary_geom:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Calculation has no boundary geometry"
        )

    try:
        # Convert boundary to GeoJSON
        geom_shape = wkb.loads(bytes(calculation.boundary_geom.data))
        geometry = mapping(geom_shape)

        # Generate map
        map_generator = get_map_generator()
        buffer = map_generator.generate_soil_map(
            geometry=geometry,
            db_session=db,
            forest_name=calculation.forest_name or 'Community Forest',
            orientation='auto'
        )

        # Return as SVG image (preserves text shaping for Devanagari)
        return StreamingResponse(
            io.BytesIO(buffer.getvalue()),
            media_type="image/svg+xml",
            headers={"Content-Disposition": f"inline; filename=soil_map_{calculation_id}.svg"}
        )

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error generating soil map: {str(e)}"
        )


@router.get("/calculations/{calculation_id}/maps/forest_health")
def generate_forest_health_map_endpoint(
    calculation_id: UUID,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """
    Generate forest health map showing vegetation health status

    Returns PNG image (A5 size, 300 DPI) with forest health classes
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

    if not calculation.boundary_geom:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Calculation has no boundary geometry"
        )

    try:
        # Convert boundary to GeoJSON
        geom_shape = wkb.loads(bytes(calculation.boundary_geom.data))
        geometry = mapping(geom_shape)

        # Generate map
        map_generator = get_map_generator()
        buffer = map_generator.generate_forest_health_map(
            geometry=geometry,
            db_session=db,
            forest_name=calculation.forest_name or 'Community Forest',
            orientation='auto'
        )

        # Return as SVG image (preserves text shaping for Devanagari)
        return StreamingResponse(
            io.BytesIO(buffer.getvalue()),
            media_type="image/svg+xml",
            headers={"Content-Disposition": f"inline; filename=forest_health_map_{calculation_id}.svg"}
        )

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error generating forest health map: {str(e)}"
        )
