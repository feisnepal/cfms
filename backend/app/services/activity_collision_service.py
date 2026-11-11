"""
Collision detection service for activity features (R7 backend extension).

Detects spatial overlaps between drawn features across different proposed
activities within the same calculation, with configurable buffer tolerance.
"""
import json
import logging
from typing import List, Optional, Tuple
from uuid import UUID

from sqlalchemy.orm import Session
from sqlalchemy import func
from geoalchemy2.shape import to_shape as g2s
from shapely.geometry import shape, mapping
from shapely import set_precision

from ..models.yearly_activities import ActivityDrawnFeature

from app.core.dropped import report_dropped

logger = logging.getLogger(__name__)

DEG_PER_M = 1.0 / 111_320.0


def check_collision(
    db: Session,
    calculation_id: UUID,
    input_geojson: dict,
    buffer_m: float = 0.5,
    exclude_feature_id: Optional[UUID] = None,
    exclude_activity_id: Optional[UUID] = None,
) -> dict:
    """Check if input_geojson collides with existing drawn features."""
    try:
        input_shape = shape(input_geojson)
    except Exception as e:
        logger.exception(
            "input geometry unreadable - reporting no collisions, which is "
            "not the same as finding none"
        )
        return {"has_collision": False, "collision_count": 0, "collisions": [], "error": str(e)}

    buffered = input_shape.buffer(buffer_m * DEG_PER_M)

    query = db.query(ActivityDrawnFeature).filter(
        ActivityDrawnFeature.calculation_id == calculation_id,
        ActivityDrawnFeature.deleted_at.is_(None),
        func.ST_Intersects(
            ActivityDrawnFeature.geometry,
            func.ST_GeomFromText(buffered.wkt, 4326),
        ),
    )
    if exclude_feature_id:
        query = query.filter(ActivityDrawnFeature.id != exclude_feature_id)
    if exclude_activity_id:
        query = query.filter(
            ActivityDrawnFeature.proposed_activity_id != exclude_activity_id
        )

    colliding: List[ActivityDrawnFeature] = query.all()

    collisions = []
    for f in colliding:
        try:
            f_shape = g2s(f.geometry)
            dist_m = round(input_shape.distance(f_shape) * 111_320.0, 2)
        except Exception:
            report_dropped(
                logger, "collision distance",
                "the collision is reported with no distance to the feature",
            )
            dist_m = None
        collisions.append({
            "feature_id": str(f.id),
            "proposed_activity_id": str(f.proposed_activity_id),
            "feature_type": f.feature_type,
            "properties": f.properties,
            "distance_from_input_m": dist_m,
        })

    return {
        "has_collision": len(colliding) > 0,
        "collision_count": len(colliding),
        "collisions": collisions,
    }


def compute_intersecting_block_ids(
    db: Session,
    calculation_id: UUID,
    geometry_geojson: dict,
) -> List[str]:
    """Return block IDs whose geometry intersects the given feature."""
    from geoalchemy2 import WKTElement
    from shapely.geometry import shape
    from ..models.forest_block import ForestBlock

    try:
        geom_shape = shape(geometry_geojson)
    except Exception:
        logger.exception(
            "geometry unreadable - returning no intersecting features, which "
            "is not the same as finding none"
        )
        return []

    blocks = (
        db.query(ForestBlock)
        .filter(
            ForestBlock.calculation_id == calculation_id,
            ForestBlock.deleted_at.is_(None),
            func.ST_Intersects(
                ForestBlock.geometry,
                func.ST_GeomFromText(geom_shape.wkt, 4326),
            ),
        )
        .all()
    )

    return [str(b.id) for b in blocks]
