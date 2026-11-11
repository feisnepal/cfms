"""Pydantic schemas for Operational Plan API endpoints.

Defines the full request/response model set for the OP document API:
tree structure, node CRUD, export configuration, template management,
and section-level operations. Mirrors the TreeNode model from the
service layer for API serialization.

See also:
    app.services.operational_plan.tree_models — service-layer models
    app.api.operational_plans — API endpoints
"""

from pydantic import BaseModel, Field, UUID4, model_validator
from typing import Optional, Dict, Any, List, Literal
from datetime import datetime


class TreeNodeSchema(BaseModel):
    """Schema for a tree node in the operational plan document tree."""
    id: str
    type: Literal["preamble", "toc", "section", "subsection", "appendix"] = "section"
    title_ne: str = ""
    title_en: str = ""
    number: Optional[str] = None
    level: int = 0
    content_type: Literal["richtext", "chart", "table", "map", "static_table"] = "richtext"
    content: str = ""
    chart_type: Optional[str] = None
    table_id: Optional[str] = None
    map_type: Optional[str] = None
    static_table: Optional[dict] = None
    inline_tables: Optional[list] = None
    children: List["TreeNodeSchema"] = []
    is_locked: bool = False
    hidden_in_export: bool = False
    deleted: bool = False
    page_break_before: bool = False
    # page layout (see tree_models.TreeNode): numbering format / restart, landscape, heading number prefix + separator
    page_format: Optional[Literal["decimal", "upperRoman", "lowerRoman", "upperLetter", "lowerLetter"]] = None
    restart_pages: bool = False
    landscape: bool = False
    number_prefix: Optional[str] = None
    number_sep: Optional[str] = None
    last_modified: Optional[str] = None
    # OP multi-template §3.9 — template-owned cover page (Phase 0: fields only).
    is_cover: bool = False
    cover_meta: Optional[dict] = None
    # OP multi-template §3.4 — stable key a plan-kind's required_section_keys
    # matches against (title matching is the fallback). Optional; unset on
    # legacy nodes.
    section_key: Optional[str] = None
    # THEMATIC_MAP_VARIABLES_PLAN P6 — per-node thematic-map tuning.
    thememap_spec: Optional[dict] = None
    opsmap_key: Optional[str] = None
    year: Optional[int] = None
    # see services/operational_plan/plan_live.py
    source_content: Optional[str] = None
    populated_hash: Optional[str] = None


class OperationalPlanCreate(BaseModel):
    """Request schema for creating a new operational plan."""
    calculation_id: UUID4
    forest_name: Optional[str] = None
    custom_notes: Optional[str] = None


class OperationalPlanUpdate(BaseModel):
    """Request schema for updating an operational plan."""
    sections: Optional[Dict[str, Any]] = None
    tree: Optional[List[TreeNodeSchema]] = None
    status: Optional[str] = None
    plan_metadata: Optional[Dict[str, Any]] = None


class OperationalPlanSectionUpdate(BaseModel):
    """Request schema for updating a section's content and auto-data."""
    content: str
    auto_data: Optional[Dict[str, Any]] = None


class TreeNodeCreate(BaseModel):
    """Request schema for creating a new tree node."""
    parent_id: Optional[str] = None
    type: Literal["preamble", "toc", "section", "subsection", "appendix"] = "section"
    title_ne: str = ""
    title_en: str = ""
    content: str = ""
    content_type: Literal["richtext", "chart", "table", "map", "static_table"] = "richtext"
    chart_type: Optional[str] = None
    table_id: Optional[str] = None
    map_type: Optional[str] = None
    static_table: Optional[dict] = None
    position: int = -1


class TreeNodeUpdate(BaseModel):
    """Request schema for updating a tree node."""
    title_ne: Optional[str] = None
    title_en: Optional[str] = None
    content: Optional[str] = None
    content_type: Optional[Literal["richtext", "chart", "table", "map", "static_table"]] = None
    chart_type: Optional[str] = None
    table_id: Optional[str] = None
    map_type: Optional[str] = None
    static_table: Optional[dict] = None
    hidden_in_export: Optional[bool] = None
    deleted: Optional[bool] = None


class TreeNodeReorder(BaseModel):
    """Request schema for reordering a tree node."""
    node_id: str
    new_parent_id: Optional[str] = None
    new_position: int = -1


class VariableDefResponse(BaseModel):
    """Response schema for a variable definition."""
    key: str
    category: str
    label_ne: str
    label_en: str
    var_type: str
    source: str
    auto_populate: bool
    description: str
    description_ne: str = ""
    table_columns: List[str] = []
    mock_rows: List[Dict[str, Any]] = []


class OperationalPlanResponse(BaseModel):
    """Response schema for an operational plan."""
    id: UUID4
    calculation_id: UUID4
    forest_name: Optional[str] = None
    sections: Dict[str, Any] = {}
    tree: List[TreeNodeSchema] = []
    plan_metadata: Dict[str, Any] = {}
    status: str
    created_at: datetime
    updated_at: datetime
    submitted_at: Optional[datetime] = None
    approved_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class OperationalPlanListResponse(BaseModel):
    """Response schema for an operational plan list item."""
    id: UUID4
    calculation_id: UUID4
    forest_name: Optional[str] = None
    status: str
    updated_at: datetime

    class Config:
        from_attributes = True


# OP multi-template — lifecycle + two-axis plan kind (OP_MULTI_TEMPLATE_PLAN.md).
TemplateStatus = Literal[
    "draft", "in_review", "rejected", "published", "deprecated", "retired"
]
PlanStage = Literal["new", "revision"]
PlanRegime = Literal["sustainable_fmp", "brief_fmp", "scientific_fmp"]


# status -> legacy approval_status, for response compatibility (Phase 7).
_APPROVAL_BY_STATUS = {
    "draft": "none", "in_review": "pending", "rejected": "rejected",
    "published": "approved", "deprecated": "approved", "retired": "none",
}


class TemplateCreate(BaseModel):
    """Request schema for creating a template."""
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = ""
    tree: List[TreeNodeSchema]
    is_system: bool = False
    tags: Optional[List[str]] = None
    template_category: Optional[str] = None
    plan_kind: Optional[str] = None
    plan_regime: Optional[PlanRegime] = None
    plan_stage: Optional[PlanStage] = None


class TemplateUpdate(BaseModel):
    """Request schema for updating a template."""
    name: Optional[str] = None
    description: Optional[str] = None
    tree: Optional[List[TreeNodeSchema]] = None
    tags: Optional[List[str]] = None
    template_category: Optional[str] = None
    changelog: Optional[str] = None
    plan_kind: Optional[str] = None
    plan_regime: Optional[PlanRegime] = None
    plan_stage: Optional[PlanStage] = None
    preview_image_url: Optional[str] = None


class TemplatePublish(BaseModel):
    """Request schema for publishing/unpublishing a template (legacy shim)."""
    is_active: bool


class TemplateClone(BaseModel):
    """Request schema for cloning a template."""
    name: Optional[str] = None
    target_plan_kind: Optional[str] = None
    target_plan_regime: Optional[PlanRegime] = None
    target_plan_stage: Optional[PlanStage] = None


class TemplateApprove(BaseModel):
    """Request schema for approving or rejecting a template.

    ``approve`` is one-click publish (validate + snapshot + publish);
    ``reject`` requires a note.
    """
    action: Literal["approve", "reject"]
    note: Optional[str] = ""


class TemplateLifecycleRequest(BaseModel):
    """Request body for unpublish / deprecate / retire transitions."""
    note: Optional[str] = ""
    superseded_by_template_id: Optional[UUID4] = None  # deprecate only


class ValidationIssue(BaseModel):
    """One error or warning from the template validation gate."""
    severity: Literal["error", "warning"]
    code: str
    message: str
    node_id: Optional[str] = None
    token: Optional[str] = None


class TemplateValidateResponse(BaseModel):
    """Result of the template validation gate (§3.4)."""
    ok: bool
    errors: List[ValidationIssue] = []
    warnings: List[ValidationIssue] = []


class TemplateAuditEntry(BaseModel):
    """One row of the append-only template lifecycle trail."""
    id: UUID4
    template_id: UUID4
    actor_id: Optional[UUID4] = None
    action: str
    from_status: Optional[str] = None
    to_status: Optional[str] = None
    note: Optional[str] = None
    version: Optional[int] = None
    created_at: datetime

    class Config:
        from_attributes = True


class PlanKindResponse(BaseModel):
    """A management-plan kind = (plan_stage x plan_regime)."""
    key: str
    plan_stage: str
    plan_regime: str
    parent_kind_key: Optional[str] = None
    label_ne: str
    label_en: str
    description: str = ""
    required_section_keys: List[str] = []
    effective_required_section_keys: List[str] = []
    variable_allowlist: Optional[List[str]] = None
    allowlist_strict: bool = False
    default_template_id: Optional[UUID4] = None
    cover_style: Optional[str] = None
    export_basename: Optional[str] = None
    min_sections: int = 0
    sort_order: int = 0
    is_active: bool = True

    class Config:
        from_attributes = True


class PlanKindUpdate(BaseModel):
    """Super-admin edit of a plan kind (kinds-manager UI)."""
    label_ne: Optional[str] = None
    label_en: Optional[str] = None
    description: Optional[str] = None
    required_section_keys: Optional[List[str]] = None
    variable_allowlist: Optional[List[str]] = None
    allowlist_strict: Optional[bool] = None
    default_template_id: Optional[UUID4] = None
    cover_style: Optional[str] = None
    export_basename: Optional[str] = None
    min_sections: Optional[int] = None
    sort_order: Optional[int] = None
    is_active: Optional[bool] = None


class PlanTemplateStatusResponse(BaseModel):
    """Whether the template a plan was built from has a newer published version."""
    has_template: bool = False
    template_id: Optional[UUID4] = None
    template_name: Optional[str] = None
    template_status: Optional[str] = None
    pinned_version: Optional[int] = None
    latest_published_version: Optional[int] = None
    upgrade_available: bool = False
    changelog_since: List[str] = []


class TemplateUpgradeRequest(BaseModel):
    """Adopt the latest published version of the plan's template."""
    confirm: bool = False  # false = dry run (returns the diff only)


class TemplateUpgradeDiff(BaseModel):
    added: List[str] = []           # section titles new in the published version
    removed: List[str] = []         # plan sections dropped (not in the new structure)
    kept: int = 0                   # matched by node id
    content_preserved: int = 0      # matched nodes whose authored content was carried over


class TemplateUpgradeResponse(BaseModel):
    applied: bool
    from_version: Optional[int] = None
    to_version: Optional[int] = None
    diff: TemplateUpgradeDiff


class SuggestKindResponse(BaseModel):
    """Advisory (Phase 4): stage the UI may pre-highlight. Not enforced."""
    suggested_stage: Literal["new", "revision"] = "new"
    has_prior_plan: bool = False
    reason: str = ""


class TemplateSummary(BaseModel):
    """Response schema for a template summary.

    `status` is authoritative; `is_active` / `visibility` / `approval_status` /
    `is_default` are derived here for response compatibility (Phase 7 dropped
    the columns).
    """
    id: UUID4
    name: str
    description: str = ""
    is_system: bool = False
    is_kind_default: bool = False  # set by list_public_templates
    version: int = 1
    status: str = "draft"
    plan_kind: Optional[str] = None
    plan_regime: Optional[str] = None
    plan_stage: Optional[str] = None
    published_version: Optional[int] = None
    tags: List[str] = []
    template_category: Optional[str] = None
    sections_summary: List[str] = []
    variables_summary: List[str] = []
    created_by: Optional[UUID4] = None
    created_at: datetime
    updated_at: datetime

    # sharing (migration 125). ``author_name`` is filled in only for templates that are shared, never for a private one.
    item_type: str = "template"
    share_scope: str = "private"
    tier: str = "community"
    license: str = "cc_by"
    organization_id: Optional[UUID4] = None
    author_name: Optional[str] = None
    # the original this copy was taken from (the "original updated" notice reads it)
    source_template_id: Optional[UUID4] = None

    # derived-from-status compatibility fields
    is_active: bool = True
    is_default: bool = False
    visibility: str = "private"
    approval_status: str = "none"

    class Config:
        from_attributes = True

    @model_validator(mode="before")
    @classmethod
    def _derive_legacy_flags(cls, data):
        if isinstance(data, dict):
            return data
        st = getattr(data, "status", "draft") or "draft"
        public = st in ("published", "deprecated")
        out = {f: getattr(data, f) for f in cls.model_fields if hasattr(data, f)}
        out["is_active"] = public
        out["visibility"] = "global" if public else "private"
        out["approval_status"] = _APPROVAL_BY_STATUS.get(st, "none")
        out["is_default"] = bool(getattr(data, "is_system", False))
        return out


class TemplateResponse(TemplateSummary):
    """Response schema for a full template with tree."""
    tree: List[TreeNodeSchema] = []
    approval_note: str = ""
    approved_by: Optional[UUID4] = None
    approved_at: Optional[datetime] = None
    published_by: Optional[UUID4] = None
    published_at: Optional[datetime] = None
    source_calculation_id: Optional[UUID4] = None
    source_template_id: Optional[UUID4] = None
    changelog: Optional[str] = None


class TemplateVersionResponse(BaseModel):
    """Response schema for a template version."""
    id: UUID4
    template_id: UUID4
    version: int
    name: str
    description: str = ""
    changelog: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


class SystemTemplateSeedSync(BaseModel):
    """Whether the System Template's stored tree still matches the code-owned
    seed tree (OP_TEMPLATE_MANAGEMENT_PLAN.md T1)."""
    in_sync: bool
    missing_sections: List[str] = []
    unregistered_tokens: List[str] = []


class SystemTemplateResponse(BaseModel):
    """The one is_system template, its version history, and its seed-sync
    status."""
    template: TemplateResponse
    versions: List[TemplateVersionResponse] = []
    seed_sync: SystemTemplateSeedSync


class AdoptFromPlanDiff(BaseModel):
    """What ``adopt-from-plan`` would change on the System Template."""
    added: List[str] = []
    removed: List[str] = []
    token_restored: List[str] = []
    needs_review: List[str] = []
    kept: int = 0


class AdoptFromPlanResponse(BaseModel):
    diff: AdoptFromPlanDiff
    applied: bool = False
    template: Optional[TemplateResponse] = None


class TemplateRollbackRequest(BaseModel):
    """Request schema for rolling back a template to a previous version."""
    version: int


class UpdateDefaultTemplateRequest(BaseModel):
    """Request schema for updating the default template."""
    changelog: Optional[str] = ""


class CategoryCreate(BaseModel):
    """Request schema for creating a variable category."""
    key: str = Field(..., min_length=1, max_length=50)
    label_ne: str = Field(..., min_length=1, max_length=255)
    label_en: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = ""
    color: Optional[str] = "purple"
    sort_order: int = 0


class CategoryUpdate(BaseModel):
    """Request schema for updating a variable category."""
    label_ne: Optional[str] = None
    label_en: Optional[str] = None
    description: Optional[str] = None
    color: Optional[str] = None
    sort_order: Optional[int] = None


class CategoryResponse(BaseModel):
    """Response schema for a variable category."""
    id: UUID4
    key: str
    label_ne: str
    label_en: str
    description: str = ""
    color: str = "purple"
    sort_order: int = 0
    created_at: datetime

    class Config:
        from_attributes = True