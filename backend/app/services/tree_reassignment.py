"""
Tree reassignment service for compartments
"""
from sqlalchemy.orm import Session
from geoalchemy2.shape import to_shape
from shapely.geometry import Point, mapping
from typing import Dict, List, Optional
from uuid import UUID
import logging

from ..models.forest_block import ForestBlock
from ..models.inventory import InventoryTree

logger = logging.getLogger(__name__)


async def get_trees_needing_assignment(
    db: Session,
    block_id: UUID
) -> Dict[str, any]:
    """
    Get trees assigned to parent block that need compartment assignment

    Args:
        db: Database session
        block_id: Parent block ID

    Returns:
        Dictionary with trees, compartments, and suggestions
    """
    # Get parent block
    block = db.query(ForestBlock).filter(ForestBlock.id == block_id).first()
    if not block:
        raise ValueError("Block not found")

    # Get compartments for this block
    compartments = db.query(ForestBlock).filter(
        ForestBlock.parent_block_id == block_id,
        ForestBlock.is_compartment == True
    ).all()

    if not compartments:
        return {
            "trees": [],
            "compartments": [],
            "message": "No compartments exist for this block"
        }

    # Get trees assigned to parent block
    trees = db.query(InventoryTree).filter(
        InventoryTree.block_id == block_id
    ).all()

    # Generate suggestions for each tree
    tree_data = []
    for tree in trees:
        suggested_comp = find_containing_compartment(tree, compartments)

        tree_location = extract_coordinates(tree.location)

        tree_data.append({
            "id": str(tree.id),
            "species": tree.species,
            "location": tree_location,
            "suggested_block_id": str(suggested_comp.id) if suggested_comp else None,
            "suggested_block_name": suggested_comp.compartment_code if suggested_comp else None
        })

    compartment_data = []
    for comp in compartments:
        comp_geom = to_shape(comp.geometry)
        compartment_data.append({
            "id": str(comp.id),
            "name": comp.compartment_code or comp.name,
            "geometry": mapping(comp_geom)
        })

    return {
        "block_name": block.name,
        "compartments": compartment_data,
        "trees": tree_data,
        "total_trees": len(trees)
    }


async def auto_assign_trees_by_location(
    db: Session,
    block_id: UUID
) -> Dict[str, any]:
    """
    Auto-assign trees from parent block to compartments based on GPS location

    Args:
        db: Database session
        block_id: Parent block ID

    Returns:
        Assignment statistics
    """
    # Get compartments
    compartments = db.query(ForestBlock).filter(
        ForestBlock.parent_block_id == block_id,
        ForestBlock.is_compartment == True
    ).all()

    if not compartments:
        raise ValueError("No compartments exist for this block")

    # Get trees
    trees = db.query(InventoryTree).filter(
        InventoryTree.block_id == block_id
    ).all()

    assigned_count = 0
    unassigned_count = 0
    by_compartment = {}

    for tree in trees:
        compartment = find_containing_compartment(tree, compartments)

        if compartment:
            # Assign tree to compartment by updating block_id
            tree.block_id = compartment.id
            tree.block_name = compartment.compartment_code or compartment.name
            # Forest Structure rule (D10, FS-1d.3): the live unit link.
            tree.unit_id = compartment.id
            assigned_count += 1

            # Track count per compartment
            comp_id = str(compartment.id)
            if comp_id not in by_compartment:
                by_compartment[comp_id] = {
                    "name": compartment.compartment_code or compartment.name,
                    "count": 0
                }
            by_compartment[comp_id]["count"] += 1
        else:
            # Tree not in any compartment (edge case)
            unassigned_count += 1
            logger.warning(f"Tree {tree.id} ({tree.species}) not in any compartment")

    db.commit()

    logger.info(f"Assigned {assigned_count} trees, {unassigned_count} unassigned")

    return {
        "total_assigned": assigned_count,
        "unassigned": unassigned_count,
        "by_compartment": by_compartment
    }


async def manual_assign_trees(
    db: Session,
    manual_assignments: Dict[UUID, UUID]
) -> Dict[str, any]:
    """
    Manually assign specific trees to compartments

    Args:
        db: Database session
        manual_assignments: Dict mapping tree_id -> block_id (compartment)

    Returns:
        Assignment statistics
    """
    assigned_count = 0
    failed_assignments = []
    by_compartment = {}

    for tree_id, block_id in manual_assignments.items():
        try:
            # Get tree
            tree = db.query(InventoryTree).filter(InventoryTree.id == tree_id).first()
            if not tree:
                failed_assignments.append(str(tree_id))
                continue

            # Get compartment
            compartment = db.query(ForestBlock).filter(
                ForestBlock.id == block_id,
                ForestBlock.is_compartment == True
            ).first()
            if not compartment:
                failed_assignments.append(str(tree_id))
                continue

            # Assign
            tree.block_id = compartment.id
            tree.block_name = compartment.compartment_code or compartment.name
            # Forest Structure rule (D10, FS-1d.3): the live unit link.
            tree.unit_id = compartment.id
            assigned_count += 1

            # Track count
            comp_id = str(compartment.id)
            if comp_id not in by_compartment:
                by_compartment[comp_id] = {
                    "name": compartment.compartment_code or compartment.name,
                    "count": 0
                }
            by_compartment[comp_id]["count"] += 1

        except Exception as e:
            logger.error(f"Failed to assign tree {tree_id}: {e}")
            failed_assignments.append(str(tree_id))

    db.commit()

    return {
        "total_assigned": assigned_count,
        "failed": len(failed_assignments),
        "failed_tree_ids": failed_assignments,
        "by_compartment": by_compartment
    }


def find_containing_compartment(
    tree: InventoryTree,
    compartments: List[ForestBlock]
) -> Optional[ForestBlock]:
    """
    Find which compartment contains a tree based on GPS location

    Args:
        tree: InventoryTree object
        compartments: List of ForestBlock compartments

    Returns:
        ForestBlock that contains the tree, or None
    """
    try:
        tree_point = to_shape(tree.location)

        for comp in compartments:
            comp_polygon = to_shape(comp.geometry)

            if comp_polygon.contains(tree_point):
                return comp

        # If no exact match, try finding closest compartment (tolerance)
        min_distance = float('inf')
        closest_comp = None

        for comp in compartments:
            comp_polygon = to_shape(comp.geometry)
            distance = tree_point.distance(comp_polygon)

            # If within 10 meters (approximate), consider it
            if distance < 0.0001 and distance < min_distance:  # ~10m in degrees
                min_distance = distance
                closest_comp = comp

        if closest_comp:
            logger.info(f"Tree {tree.id} assigned to nearest compartment (distance: {min_distance:.6f})")
            return closest_comp

        return None
    except Exception as e:
        logger.error(f"Error finding compartment for tree {tree.id}: {e}")
        return None


def extract_coordinates(location) -> Dict[str, float]:
    """Extract lat/lon from PostGIS geography"""
    try:
        point = to_shape(location)
        return {
            "lon": point.x,
            "lat": point.y
        }
    except Exception as e:
        logger.error(f"Failed to extract coordinates: {e}")
        return {"lon": 0, "lat": 0}
