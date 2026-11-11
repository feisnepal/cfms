"""OP template model (op_templates).

Stores saved document tree templates for the Operational Plan. Each
template contains a complete document structure (tree as JSONB) that
can be cloned to create a new OP. Supports system-level defaults and
user-created private templates.

See also:
    app.models.operational_plan.OperationalPlan — the OP instance model
    app.services.operational_plan.seed_data — default tree definition
    OP_MULTI_TEMPLATE_PLAN.md — the multi-template / plan-kind design
"""

from sqlalchemy import Index, Column, String, Boolean, DateTime, ForeignKey, Text, Integer
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from sqlalchemy import func
import uuid
from ..core.database import Base


class OPTemplate(Base):
    """Operational Plan document template with versioning and approval workflow."""
    __tablename__ = "op_templates"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True, default="")
    tree = Column(JSONB, nullable=False, default=list)

    # `is_system` = seeded / protected (cannot be deleted). The legacy
    # visibility / is_default / is_active / approval_status columns were dropped
    # in migration 071 — `status` is now the single authority and the API
    # derives the old flags for response compatibility.
    is_system = Column(Boolean, nullable=False, default=False)

    version = Column(Integer, nullable=False, server_default="1")
    changelog = Column(Text, nullable=True, default="")
    template_category = Column(String(100), nullable=True)
    preview_image_url = Column(Text, nullable=True)
    source_template_id = Column(UUID(as_uuid=True), nullable=True)
    # the version of the original this copy was taken from (migration 129); NULL for copies made before it existed
    source_version = Column(Integer, nullable=True)

    tags = Column(JSONB, nullable=True, default=list)
    sections_summary = Column(JSONB, nullable=True, default=list)
    variables_summary = Column(JSONB, nullable=True, default=list)

    # review note — the reviewer's free-text reason (not derivable from status).
    approval_note = Column(Text, nullable=True, default="")
    approved_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    approved_at = Column(DateTime(timezone=True), nullable=True)

    # ── OP multi-template (migration 066) ─────────────────────────────
    # Lifecycle state machine — see OP_MULTI_TEMPLATE_PLAN.md §3.3.
    # draft | in_review | rejected | published | deprecated | retired
    # Phase 0 adds the columns only; no code reads `status` yet — the
    # legacy visibility/approval_status/is_active flags still drive behaviour.
    status = Column(String(20), nullable=False, server_default="draft")
    # Composite plan kind "<regime>_<stage>" (FK-ish to op_plan_kinds.key);
    # NULL = the universal बृन्दावन base template (exempt from required-section
    # validation). plan_regime / plan_stage are denormalised for grouping.
    plan_kind = Column(String(50), nullable=True)
    plan_regime = Column(String(30), nullable=True)
    plan_stage = Column(String(20), nullable=True)
    # Version pinned at the moment of publish; the matching op_template_versions
    # row carries is_published_snapshot = true.
    published_version = Column(Integer, nullable=True)
    # Actor id columns are FK-less, matching source_template_id /
    # source_calculation_id on this same table (kept lock-light).
    published_by = Column(UUID(as_uuid=True), nullable=True)
    published_at = Column(DateTime(timezone=True), nullable=True)
    deprecated_by_template_id = Column(UUID(as_uuid=True), nullable=True)
    retired_reason = Column(Text, nullable=True)
    retired_by = Column(UUID(as_uuid=True), nullable=True)
    retired_at = Column(DateTime(timezone=True), nullable=True)

    # 'template' = a whole plan layout; 'section' = one chapter kept in the shared section library (migration 126)
    item_type = Column(String(10), nullable=False, server_default="template", default="template")

    # ── sharing (migration 125) ───────────────────────────────────────
    # who may see it: private (the author) | office (users of the author's organisation = a DFO office) | public (everyone).
    share_scope = Column(String(10), nullable=False, server_default="private", default="private")
    # trust: community (unreviewed) | verified | official. Only a super admin raises it; an author's edit to a verified or
    # official template drops it back to community.
    tier = Column(String(10), nullable=False, server_default="community", default="community")
    # what others may do: cc_by (use, copy and edit, with credit) | cc0 (anything) | view_only (use it, not copy it)
    license = Column(String(10), nullable=False, server_default="cc_by", default="cc_by")
    organization_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="SET NULL"), nullable=True)

    source_calculation_id = Column(UUID(as_uuid=True), nullable=True)
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    def __repr__(self):
        return f"<OPTemplate(id={self.id}, name={self.name}, version={self.version})>"


class OPTemplateVersion(Base):
    """Immutable version snapshot of an OP template for rollback history."""
    __tablename__ = "op_template_versions"
    __table_args__ = (
        Index('ix_public_op_template_versions_template_id', 'template_id'),
    )
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    template_id = Column(UUID(as_uuid=True), ForeignKey("op_templates.id", ondelete="CASCADE"), nullable=False, index=True)
    version = Column(Integer, nullable=False)
    tree = Column(JSONB, nullable=False)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True, default="")
    changelog = Column(Text, nullable=True, default="")
    # True for the snapshot that was live when the template last entered
    # `published` status (migration 069).
    is_published_snapshot = Column(Boolean, nullable=False, server_default="false")
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    template = relationship("OPTemplate", backref="versions")

    def __repr__(self):
        return f"<OPTemplateVersion(template_id={self.template_id}, version={self.version})>"


class OPTemplateCategory(Base):
    """Category classification for OP templates (e.g., 'district', 'municipal')."""
    __tablename__ = "op_template_categories"
    __table_args__ = (
        Index('ix_public_op_template_categories_key', 'key', unique=True),
    )
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    key = Column(String(50), unique=True, nullable=False, index=True)
    label_ne = Column(String(255), nullable=False)
    label_en = Column(String(255), nullable=False)
    description = Column(Text, nullable=True, default="")
    color = Column(String(20), nullable=True, default="purple")
    sort_order = Column(Integer, nullable=False, server_default="0")
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    def __repr__(self):
        return f"<OPTemplateCategory(key={self.key}, label_en={self.label_en})>"


class OPPlanKind(Base):
    """A management-plan kind = (plan_stage x plan_regime).

    Six seeded rows: {sustainable,brief,scientific}_fmp_{new,revision}. Each
    carries the statutory mandatory-section list, the recommended default
    template, and cover/export hints. A ``*_revision`` row points at its
    ``*_new`` row via ``parent_kind_key``; its effective required sections are
    the parent's list UNION its own. Super-admin managed. See
    OP_MULTI_TEMPLATE_PLAN.md §3.2. (migration 067)
    """
    __tablename__ = "op_plan_kinds"
    key = Column(String(50), primary_key=True)
    plan_stage = Column(String(20), nullable=False)   # new | revision
    plan_regime = Column(String(30), nullable=False)  # sustainable_fmp | brief_fmp | scientific_fmp
    parent_kind_key = Column(String(50), ForeignKey("op_plan_kinds.key"), nullable=True)

    label_ne = Column(String(255), nullable=False)
    label_en = Column(String(255), nullable=False)
    description = Column(Text, nullable=True, default="")

    # Filled in later via the kinds-manager UI (D2b) — seeded empty.
    required_section_keys = Column(JSONB, nullable=False, server_default="[]")
    variable_allowlist = Column(JSONB, nullable=True)
    allowlist_strict = Column(Boolean, nullable=False, server_default="false")

    default_template_id = Column(UUID(as_uuid=True), ForeignKey("op_templates.id"), nullable=True)
    cover_style = Column(String(30), nullable=True)      # sustainable | brief | scientific
    export_basename = Column(String(255), nullable=True)
    min_sections = Column(Integer, nullable=False, server_default="0")

    sort_order = Column(Integer, nullable=False, server_default="0")
    is_active = Column(Boolean, nullable=False, server_default="true")
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    def __repr__(self):
        return f"<OPPlanKind(key={self.key})>"


class OPTemplateAudit(Base):
    """Append-only audit trail of OP template lifecycle transitions.

    One row per transition (submit / approve-publish / reject / unpublish /
    deprecate / retire), written through a single funnel. See
    OP_MULTI_TEMPLATE_PLAN.md §3.3. (migration 068)
    """
    __tablename__ = "op_template_audit"
    __table_args__ = (
        Index('ix_public_op_template_audit_template_id', 'template_id'),
    )
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    template_id = Column(UUID(as_uuid=True), ForeignKey("op_templates.id", ondelete="CASCADE"), nullable=False)
    actor_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    action = Column(String(30), nullable=False)
    from_status = Column(String(20), nullable=True)
    to_status = Column(String(20), nullable=True)
    note = Column(Text, nullable=True)
    version = Column(Integer, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    def __repr__(self):
        return f"<OPTemplateAudit(template_id={self.template_id}, action={self.action})>"


class OPTemplateReport(Base):
    """A complaint about a shared template; the super admin dismisses it or acts on it."""
    __tablename__ = "op_template_reports"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    template_id = Column(UUID(as_uuid=True), ForeignKey("op_templates.id", ondelete="CASCADE"), nullable=False, index=True)
    reporter_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    reason = Column(Text, nullable=False)
    status = Column(String(10), nullable=False, server_default="open")  # open | dismissed | actioned
    handled_by = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    handled_at = Column(DateTime(timezone=True), nullable=True)
    handled_note = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
