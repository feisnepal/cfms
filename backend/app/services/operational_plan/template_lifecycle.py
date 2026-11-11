"""OP template lifecycle state machine + single audit funnel.

State machine (OP_MULTI_TEMPLATE_PLAN.md §3.3):

    draft --submit--> in_review --reject(note)--> rejected --edit--> draft
                          |
                    approve (one click) = validate + snapshot + publish
                          v
                      published --unpublish--> draft
                        |  ^
                  deprecate  republish (= approve again)
                        v  |
                     deprecated --retire(reason)--> retired  (terminal)

`status` is the single authority. `approved_by/at` / `published_by/at` /
`approval_note` are kept as real audit metadata; the derived legacy flags
(is_active / visibility / approval_status / is_default) live only on the API
response models now (Phase 7 dropped the columns).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy import select, func
from sqlalchemy.orm import Session

from ...models.op_template import OPTemplate, OPTemplateVersion, OPTemplateAudit
from ...models.operational_plan import OperationalPlan
from .template_utils import generate_template_summaries
from .template_validation import validate_template


class TransitionError(Exception):
    """A lifecycle transition was refused. `code` is a stable slug; `issues`
    carries validation issues when the refusal is a failed gate."""

    def __init__(self, code: str, message: str, issues: Optional[List[dict]] = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.issues = issues or []


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _write_audit(
    db: Session,
    template: OPTemplate,
    *,
    actor_id: Optional[UUID],
    action: str,
    from_status: Optional[str],
    to_status: Optional[str],
    note: Optional[str] = None,
    version: Optional[int] = None,
) -> None:
    """The one funnel every transition writes through."""
    db.add(
        OPTemplateAudit(
            template_id=template.id,
            actor_id=actor_id,
            action=action,
            from_status=from_status,
            to_status=to_status,
            note=(note or None),
            version=version,
        )
    )


def _regenerate_summaries(template: OPTemplate) -> None:
    summaries = generate_template_summaries(template.tree or [])
    template.sections_summary = summaries["sections_summary"]
    template.variables_summary = summaries["variables_summary"]


def _forbid_system(template: OPTemplate, action: str) -> None:
    """The System Template must always exist as ``published`` — it is the fork
    parent for every template and the fallback for a plan created with no
    template. Block every lifecycle transition that could move it off
    ``published`` or out of the gallery (OP_TEMPLATE_MANAGEMENT_PLAN.md §3.1).
    Editing its tree is still allowed (super admin only, guarded in the API)."""
    if template.is_system:
        raise TransitionError(
            "system_protected",
            f"The System Template cannot be {action}. Edit it in the template "
            f"designer (super admin only) instead.",
        )


def _gate(db: Session, template: OPTemplate, *, for_publish: bool) -> None:
    result = validate_template(
        db,
        template.tree or [],
        plan_kind=template.plan_kind,
        for_publish=for_publish,
        description=template.description,
        is_system=bool(template.is_system),
    )
    if not result["ok"]:
        raise TransitionError(
            "validation_failed",
            "Template validation failed; fix the errors and resubmit.",
            issues=result["errors"],
        )


# ── transitions ──────────────────────────────────────────────────────────


def submit(
    db: Session, template: OPTemplate, *, actor_id: Optional[UUID]
) -> OPTemplate:
    _forbid_system(template, "submitted for review")
    if template.status not in ("draft", "rejected"):
        raise TransitionError(
            "bad_state",
            f"Only a draft or rejected template can be submitted "
            f"(current: {template.status}).",
        )
    _gate(db, template, for_publish=False)

    prev = template.status
    template.status = "in_review"
    template.approval_note = ""
    template.updated_at = _now()
    _write_audit(
        db,
        template,
        actor_id=actor_id,
        action="submit",
        from_status=prev,
        to_status="in_review",
        version=template.version,
    )
    return template


def _publish_snapshot(db: Session, template: OPTemplate, actor_id: Optional[UUID], note: str) -> None:
    """Pin the current tree as the next published version and mark the template published."""
    # published_version is a publish counter, independent of `version` (the edit
    # counter): each publish -> published_version + 1, with a snapshot pinned to
    # it. Only the latest snapshot keeps is_published_snapshot = True.
    new_pv = (template.published_version or 0) + 1
    db.query(OPTemplateVersion).filter(
        OPTemplateVersion.template_id == template.id,
        OPTemplateVersion.is_published_snapshot.is_(True),
    ).update({"is_published_snapshot": False}, synchronize_session=False)
    db.add(
        OPTemplateVersion(
            template_id=template.id,
            version=new_pv,
            tree=template.tree,
            name=template.name,
            description=template.description or "",
            changelog=(note or template.changelog or f"Published v{new_pv}"),
            is_published_snapshot=True,
        )
    )

    now = _now()
    template.published_version = new_pv
    template.status = "published"
    template.published_by = actor_id
    template.published_at = now
    template.approved_by = actor_id
    template.approved_at = now
    template.approval_note = note or ""
    template.updated_at = now


def approve_publish(
    db: Session, template: OPTemplate, *, actor_id: Optional[UUID], note: str = ""
) -> OPTemplate:
    if template.status not in ("in_review", "deprecated"):
        raise TransitionError(
            "bad_state",
            f"Only an in-review or deprecated template can be published "
            f"(current: {template.status}).",
        )
    _gate(db, template, for_publish=True)

    prev = template.status

    _publish_snapshot(db, template, actor_id, note)
    if template.tier == "community":
        template.tier = "verified"  # the super admin's approval is what Verified means
    if template.share_scope == "private":
        template.share_scope = "public"  # approving a template for the gallery is publishing it to everyone

    _regenerate_summaries(template)
    _write_audit(
        db,
        template,
        actor_id=actor_id,
        action="approve_publish",
        from_status=prev,
        to_status="published",
        note=note,
        version=template.published_version,
    )
    return template


def reject(
    db: Session, template: OPTemplate, *, actor_id: Optional[UUID], note: str
) -> OPTemplate:
    _forbid_system(template, "rejected")
    if template.status != "in_review":
        raise TransitionError(
            "bad_state",
            f"Only an in-review template can be rejected (current: {template.status}).",
        )
    if not (note or "").strip():
        raise TransitionError("note_required", "A rejection note is required.")

    prev = template.status
    template.status = "rejected"
    template.approval_note = note
    template.updated_at = _now()
    _write_audit(
        db,
        template,
        actor_id=actor_id,
        action="reject",
        from_status=prev,
        to_status="rejected",
        note=note,
        version=template.version,
    )
    return template


def unpublish(
    db: Session, template: OPTemplate, *, actor_id: Optional[UUID], note: str = ""
) -> OPTemplate:
    _forbid_system(template, "unpublished")
    if template.status not in ("published", "deprecated"):
        raise TransitionError(
            "bad_state",
            f"Only a published or deprecated template can be unpublished "
            f"(current: {template.status}).",
        )
    prev = template.status
    template.status = "draft"
    template.updated_at = _now()
    _write_audit(
        db,
        template,
        actor_id=actor_id,
        action="unpublish",
        from_status=prev,
        to_status="draft",
        note=note,
        version=template.version,
    )
    return template


def deprecate(
    db: Session,
    template: OPTemplate,
    *,
    actor_id: Optional[UUID],
    note: str = "",
    superseded_by_template_id: Optional[UUID] = None,
) -> OPTemplate:
    _forbid_system(template, "deprecated")
    if template.status != "published":
        raise TransitionError(
            "bad_state",
            f"Only a published template can be deprecated (current: {template.status}).",
        )
    prev = template.status
    template.status = "deprecated"
    template.deprecated_by_template_id = superseded_by_template_id
    # stays visible/usable — legacy flags unchanged
    template.updated_at = _now()
    _write_audit(
        db,
        template,
        actor_id=actor_id,
        action="deprecate",
        from_status=prev,
        to_status="deprecated",
        note=note,
        version=template.version,
    )
    return template


def _live_plan_count(db: Session, template_id: UUID) -> int:
    return int(
        db.execute(
            select(func.count())
            .select_from(OperationalPlan)
            .where(
                OperationalPlan.plan_metadata["template_id"].astext == str(template_id)
            )
        ).scalar()
        or 0
    )


def retire(
    db: Session, template: OPTemplate, *, actor_id: Optional[UUID], note: str
) -> Dict[str, Any]:
    _forbid_system(template, "retired")
    if template.status == "retired":
        raise TransitionError("bad_state", "Template is already retired.")
    if not (note or "").strip():
        raise TransitionError("note_required", "A retirement reason is required.")

    live = _live_plan_count(db, template.id)
    prev = template.status
    now = _now()
    template.status = "retired"
    template.retired_reason = note
    template.retired_by = actor_id
    template.retired_at = now
    template.updated_at = now
    _write_audit(
        db,
        template,
        actor_id=actor_id,
        action="retire",
        from_status=prev,
        to_status="retired",
        note=f"{note} (live plans: {live})",
        version=template.version,
    )
    return {"template": template, "live_plan_count": live}


def legacy_publish_shim(
    db: Session, template: OPTemplate, *, actor_id: Optional[UUID], is_active: bool
) -> OPTemplate:
    """Backs the deprecated ``PUT /templates/{id}/publish`` toggle. Lenient —
    no validation gate — so existing callers/tests keep working while the real
    lifecycle endpoints take over."""
    prev = template.status
    now = _now()
    if is_active:
        if template.status not in ("published", "deprecated"):
            template.status = "published"
            template.published_version = (template.published_version or 0) + 1
            template.published_at = now
            template.published_by = actor_id
        if template.share_scope == "private":
            template.share_scope = "public"  # the old toggle meant "in the gallery for everyone"
        action, to = "legacy_publish", template.status
    else:
        if template.status in ("published", "deprecated"):
            template.status = "draft"
        template.share_scope = "private"
        action, to = "legacy_unpublish", template.status
    template.updated_at = now
    _write_audit(
        db,
        template,
        actor_id=actor_id,
        action=action,
        from_status=prev,
        to_status=to,
        version=template.version,
    )
    return template


def share(
    db: Session,
    template: OPTemplate,
    *,
    actor_id: Optional[UUID],
    scope: str,
    license: str,
    organization_id: Optional[UUID] = None,
) -> OPTemplate:
    """The author (or the super admin) sets who may see the template.

    ``private`` takes a live template back to a draft. ``office`` / ``public`` publish it at once as a Community template: no
    review is needed (owner, 2026-10-16); the caller has already run the publish check. Verified and Official are the super
    admin's alone and are not touched here.
    """
    _forbid_system(template, "shared")
    prev = template.status
    if scope == "private":
        if template.status in ("published", "deprecated"):
            template.status = "draft"
        template.share_scope = "private"
        template.organization_id = None
        template.updated_at = _now()
        _write_audit(db, template, actor_id=actor_id, action="unshare", from_status=prev, to_status=template.status,
                     version=template.version)
        return template

    if template.status == "retired":
        raise TransitionError("bad_state", "A retired template cannot be shared.")
    if scope == "office" and organization_id is None:
        raise TransitionError("no_office", "You are not part of an office, so the template cannot be shared with one.")
    if template.status != "published":
        _publish_snapshot(db, template, actor_id, "")
        if template.tier == "community":
            # nobody approved it; do not let the record say so
            template.approved_by = None
            template.approved_at = None
            template.approval_note = ""
    template.share_scope = scope
    template.license = license
    template.organization_id = organization_id if scope == "office" else None
    template.updated_at = _now()
    _regenerate_summaries(template)
    _write_audit(db, template, actor_id=actor_id, action=f"share_{scope}", from_status=prev, to_status="published",
                 note=license, version=template.published_version)
    return template


def set_tier(
    db: Session, template: OPTemplate, *, actor_id: Optional[UUID], tier: str, note: str = ""
) -> OPTemplate:
    """Super admin only (the caller checks): Verified and Official are granted, never claimed."""
    if tier not in ("community", "verified", "official"):
        raise TransitionError("bad_tier", f"Unknown tier '{tier}'.")
    if tier != "community" and template.status not in ("published", "deprecated") and not template.is_system:
        raise TransitionError("bad_state", "Only a shared template can be made Verified or Official.")
    prev = template.tier
    template.tier = tier
    template.updated_at = _now()
    _write_audit(db, template, actor_id=actor_id, action="set_tier", from_status=prev, to_status=tier, note=note,
                 version=template.version)
    return template
