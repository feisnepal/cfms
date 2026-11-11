"""
Operational Plan Document Builder Service
"""
from .tree_models import TreeNode, TreeOperations, DocumentTree
from .auto_numbering import recompute_numbers, to_devanagari_number, DEVANAGARI_DIGITS
from .seed_data import get_default_seed_tree
from .variable_registry import VARIABLE_REGISTRY, VariableDef, get_variable, get_variables_by_category, get_all_variables
from .variable_resolver import VariableResolver
from .plan_readiness import plan_readiness, classify_tokens
from .variable_enrichment import (
    enrich_variable, get_enriched_variables, build_csv_string,
    CATEGORY_NAMES, SOURCE_DESCRIPTIONS, resolve_origin_tab,
    SUB_GROUPS, DESCRIPTIONS, TEMPLATE_USED, CSV_COLUMNS,
)

__all__ = [
    "TreeNode", "TreeOperations", "DocumentTree",
    "recompute_numbers", "to_devanagari_number", "DEVANAGARI_DIGITS",
    "get_default_seed_tree",
    "VARIABLE_REGISTRY", "VariableDef", "get_variable", "get_variables_by_category", "get_all_variables",
    "VariableResolver", "plan_readiness", "classify_tokens",
    "enrich_variable", "get_enriched_variables", "build_csv_string",
    "CATEGORY_NAMES", "SOURCE_DESCRIPTIONS", "resolve_origin_tab",
    "SUB_GROUPS", "DESCRIPTIONS", "TEMPLATE_USED", "CSV_COLUMNS",
]
