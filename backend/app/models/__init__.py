"""Database models"""
from .user import User, UserRole, UserStatus
from .user_role_change import UserRoleChange
from .forest_decision import ForestDecision
from .unit_analysis import UnitAnalysis
from .organization import Organization, SubscriptionType
from .forest_manager import ForestManager
from .operational_plan import OperationalPlan
from .document_submission import DocumentSubmission, SUBMISSION_CHANNELS
from .forest_metadata import ForestMetadata
from .yearly_activities import ProposedYearlyActivity, ActivityYearDetail, ActivityDrawnFeature, YearlyPlanStatus
from .calculation import Calculation, CalculationStatus
from .boundary_audit import ForestBoundaryAudit
from .boundary_dispute import BoundaryDispute, DisputeStatus
from .structure_lock_audit import StructureLockAudit
from .calculation_audit_log import CalculationAuditLog
from .deleted_calculation import DeletedCalculation
from .calculation_progress import CalculationProgress
from .forest_block import ForestBlock
from .raster_layer import RasterLayer
from .forest_sub_area import ForestSubArea
from .forest_boundary_piece import ForestBoundaryPiece
from .community_forest import CommunityForest
from .inventory import (
    TreeSpeciesCoefficient,
    InventoryCalculation,
    InventoryTree,
    InventoryValidationLog,
    InventoryValidationIssue,
)
from .fieldbook import Fieldbook
from .sampling import SamplingDesign
from .biodiversity import BiodiversitySpecies, CalculationBiodiversity
from .synthetic_tree_model import SyntheticTreeModel
from .all_tree_export import AllTreeExport
from .field_inventory import (
    FieldInventoryCalculation,
    FieldInventorySamplePlot,
    FieldInventoryMeasurement,
    FieldInventoryBlockSummary,
)
from .user_group import UserGroupExtent, UserGroupBuilding
from .household_information import HouseholdInformation
from .household_summary_data import HouseholdSummaryData  # noqa: F401
from .caste_classification import CasteClassification
from .forest_committee import ForestUserCommittee, AdvisoryCommittee, FinancialCommittee
from .compartment import CompartmentSplitHistory
from .op_table import OPTableDefinition, OPTableData
from .op_template import OPTemplate, OPTemplateVersion, OPTemplateCategory, OPPlanKind, OPTemplateAudit
from .op_data_cache import OpDataCache
from .policy_species import PolicyReferenceSpecies
from .soil_erosion_profile import SoilErosionProfile
from .hazard_vuln_profile import HazardVulnProfile
from .sfm_prescription import SfmForestTypePrescription
from .sfm_profile import SfmProfile
from .cost_benefit import CostBenefitAnalysis, CBACostItem, CBABenefitItem, CBAResult
from .cba_rate_profile import CbaRateProfile
from .workspace_layer import WorkspaceLayer
from .workspace_layout import WorkspaceLayout
from .digitize_audit_log import DigitizeAuditLog
from .tenant_flag import TenantFlag
from .refresh_token import RefreshToken
from .idempotency import IdempotencyRecord
from .translation import Translation
from .forum import (  # noqa: F401
    ForumAction, ForumAttachment, ForumFlag, ForumNotificationPrefs, ForumPost, ForumPostRevision, ForumPostTag, ForumProfile,
    ForumReputationEvent, ForumSubscription, ForumTag, ForumTagMark, ForumTagSynonym,
)
from .chat import ChatAccess, ChatHelpChunk, ChatMessage, ChatSettings, ChatUsage  # noqa: F401
from .ntfp_method import NtfpHarvestPlan, NtfpMethodProfile, NtfpMethodValue, NtfpObservation, NtfpSamplePlot, NtfpSamplingDesign, NtfpSource, NtfpWeightSample

# Force full mapper configuration now that every model class is imported.
# This makes string-based relationships (e.g. Calculation.operational_plan)
# resolve regardless of import order, including in subprocesses like the arq worker.
from sqlalchemy.orm import configure_mappers

configure_mappers()

__all__ = [
    "User",
    "UserRole",
    "UserStatus",
    "Organization",
    "SubscriptionType",
    "ForestManager",
    "Calculation",
    "CalculationStatus",
    "ForestBlock",
    "ForestSubArea",
    "ForestBoundaryPiece",
    "CommunityForest",
    "TreeSpeciesCoefficient",
    "InventoryCalculation",
    "InventoryTree",
    "InventoryValidationLog",
    "InventoryValidationIssue",
    "Fieldbook",
    "SamplingDesign",
    "BiodiversitySpecies",
    "CalculationBiodiversity",
    "SyntheticTreeModel",
    "AllTreeExport",
    "FieldInventoryCalculation",
    "FieldInventorySamplePlot",
    "FieldInventoryMeasurement",
    "FieldInventoryBlockSummary",
    "UserGroupExtent",
    "UserGroupBuilding",
    "HouseholdInformation",
    "CasteClassification",
    "ForestUserCommittee",
    "AdvisoryCommittee",
    "FinancialCommittee",
    "CompartmentSplitHistory",
    "OPTableDefinition",
    "OPTableData",
    "OPTemplate",
    "OPTemplateVersion",
    "OPTemplateCategory",
    "OPPlanKind",
    "OPTemplateAudit",
    "OpDataCache",
    "PolicyReferenceSpecies",
    "SoilErosionProfile",
    "HazardVulnProfile",
    "SfmForestTypePrescription",
    "SfmProfile",
    "CostBenefitAnalysis",
    "CBACostItem",
    "CBABenefitItem",
    "CBAResult",
    "CbaRateProfile",
    "WorkspaceLayer",
    "WorkspaceLayout",
    "DigitizeAuditLog",
    "OperationalPlan",
    "DocumentSubmission", "SUBMISSION_CHANNELS",
    "ForestMetadata",
    "ProposedYearlyActivity",
    "ActivityYearDetail",
    "ForestBoundaryAudit",
    "BoundaryDispute",
    "DisputeStatus",
    "StructureLockAudit",
    "CalculationAuditLog",
    "DeletedCalculation",
    "CalculationProgress",
    "TenantFlag",
    "RefreshToken",
    "IdempotencyRecord",
    "Translation",
]
