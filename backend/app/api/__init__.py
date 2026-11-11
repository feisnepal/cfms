"""API routers"""
from .auth import router as auth_router
from .forests import router as forests_router
from .blocks import router as blocks_router
from .inventory import router as inventory_router
from .species import router as species_router
from .tree_models import router as tree_models_router
from .all_tree_exports import router as all_tree_exports_router
from . import biodiversity
from . import household_info
from . import forest_committee
from . import yearly_activities
from . import compartments
from . import demand_supply
from . import workspace
from . import workspace_layout
from . import fire_lines

__all__ = ["auth_router", "forests_router", "blocks_router", "inventory_router", "species_router", "tree_models_router", "all_tree_exports_router", "biodiversity", "household_info", "forest_committee", "yearly_activities", "compartments", "demand_supply", "workspace", "workspace_layout"]
