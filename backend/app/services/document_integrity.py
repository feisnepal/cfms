"""Tamper-evidence and provenance for issued documents (H7.4 · S1-54).

An operational plan carries statutory weight. Until this module there was no
way to demonstrate that a `.docx` in a district forest office was the one this
system produced, no record that it had been produced at all, and nothing tying
its figures to the geometry and inventory that generated them. If a plan's
numbers were disputed, the inputs could not be established.

The order of operations, which is the whole design
---------------------------------------------------
1. Mint a verification code. It has to exist BEFORE the document is built,
   because it is printed inside it.
2. Build the document with the code embedded.
3. Hash the FINAL bytes -- the ones actually sent.
4. Record the issuance.

Hashing before embedding would produce a hash of a document that was never
issued: verification would then fail for every genuine copy, which is worse
than having no verification at all.

What a hash here does and does not prove
-----------------------------------------
It proves a file is byte-identical to what was issued, and it makes any edit
detectable. It does NOT bind the document to an authority -- that is a
signature, and it is task 7.5, deliberately separate because it needs a key,
a custodian and a legal answer about where a signature is actually required.
"""

from __future__ import annotations

import hashlib
import logging
import secrets
from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

# Crockford-style: no I, L, O or U, so a code read aloud from a paper copy or
# typed from a printout cannot become a different valid code. The excluded
# letters are the ones confused with 1, 0 and each other.
_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
CODE_GROUPS = 3
CODE_GROUP_LEN = 4


def mint_verification_code() -> str:
    """A short code a person can read down a telephone. e.g. `K7Q2-9FHM-3XR4`.

    ~60 bits from `secrets`. Not derived from the content: it must exist before
    the content does, and a code that can be recomputed from a document is not
    a reference to a record, it is just another hash.
    """
    groups = [
        "".join(secrets.choice(_ALPHABET) for _ in range(CODE_GROUP_LEN))
        for _ in range(CODE_GROUPS)
    ]
    return "-".join(groups)


def sha256_of(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def collect_provenance(db: Session, calculation_id: Optional[UUID]) -> dict[str, Any]:
    """The inputs that produced the document's numbers.

    Cheap because the schema already carries them: `geometry_version` is the
    optimistic-lock clock (U02), and the inventory runs are rows with ids. The
    report's point was that the binding was absent, not that it was hard.

    Never raises: a document must still be issuable if provenance cannot be
    read. A record with a hash and no provenance is worth more than no record.
    """
    out: dict[str, Any] = {}
    if not calculation_id:
        return out
    try:
        row = db.execute(
            text(
                """
            SELECT c.geometry_version,
                   (SELECT id FROM inventory_calculations i
                     WHERE i.calculation_id = c.id
                     ORDER BY created_at DESC LIMIT 1),
                   (SELECT id FROM field_inventory_calculations f
                     WHERE f.calculation_id = c.id
                     ORDER BY created_at DESC LIMIT 1),
                   c.forest_name
            FROM calculations c WHERE c.id = :cid
        """
            ),
            {"cid": str(calculation_id)},
        ).first()
        if row:
            out = {
                "geometry_version": row[0],
                "inventory_calculation_id": str(row[1]) if row[1] else None,
                "field_inventory_calculation_id": str(row[2]) if row[2] else None,
                "forest_name": row[3],
            }
    except Exception:  # noqa: BLE001 -- see the docstring
        logger.error(
            "document integrity: could not collect provenance for %s",
            calculation_id,
            exc_info=True,
        )
    return out


def record_issuance(
    db: Session,
    *,
    document_bytes: bytes,
    verification_code: str,
    document_type: str,
    calculation_id: Optional[UUID] = None,
    plan_id: Optional[UUID] = None,
    filename: Optional[str] = None,
    extra_provenance: Optional[dict[str, Any]] = None,
) -> Optional[str]:
    """Persist the issuance. Returns the sha256, or None if it could not.

    Never raises. A failure to record must not deny somebody the document they
    are entitled to -- but it IS logged at ERROR, because an unrecorded
    issuance is the exact gap this task exists to close and must not pass
    quietly.
    """
    try:
        import json

        from ..core.correlation import get_correlation_id
        from ..core.request_context import get_identity

        digest = sha256_of(document_bytes)
        identity = get_identity()
        prov = collect_provenance(db, calculation_id)
        if extra_provenance:
            prov.update(extra_provenance)

        db.execute(
            text(
                """
            INSERT INTO public.document_issuances
                (verification_code, sha256, byte_size, calculation_id, plan_id,
                 document_type, filename, forest_name, geometry_version,
                 inventory_calculation_id, field_inventory_calculation_id,
                 provenance, issued_by, ip_address, client_type, correlation_id)
            VALUES
                (:code, :sha, :size, CAST(:calc AS uuid), CAST(:plan AS uuid),
                 :dtype, :fname, :forest, :geomver,
                 CAST(:inv AS uuid), CAST(:finv AS uuid),
                 CAST(:prov AS jsonb), CAST(:by AS uuid), :ip, :client, :corr)
        """
            ),
            {
                "code": verification_code,
                "sha": digest,
                "size": len(document_bytes),
                "calc": str(calculation_id) if calculation_id else None,
                "plan": str(plan_id) if plan_id else None,
                "dtype": document_type,
                "fname": filename,
                "forest": prov.get("forest_name"),
                "geomver": prov.get("geometry_version"),
                "inv": prov.get("inventory_calculation_id"),
                "finv": prov.get("field_inventory_calculation_id"),
                "prov": json.dumps(prov, default=str),
                "by": identity.user_id,
                "ip": identity.ip_address,
                "client": identity.client_type,
                "corr": get_correlation_id(),
            },
        )
        db.commit()
        logger.info(
            "document issued: type=%s code=%s sha256=%s bytes=%d calc=%s",
            document_type,
            verification_code,
            digest[:16],
            len(document_bytes),
            calculation_id,
        )
        return digest
    except Exception:  # noqa: BLE001 -- see the docstring
        try:
            db.rollback()
        except Exception:  # noqa: BLE001 -- rollback failure must not mask the original
            pass
        logger.error(
            "document integrity: FAILED to record issuance of %s for calculation %s. "
            "The document was still delivered; there is now no record of it.",
            document_type,
            calculation_id,
            exc_info=True,
        )
        return None


def lookup(db: Session, verification_code: str) -> Optional[dict[str, Any]]:
    """Resolve a code to its provenance record, or None."""
    row = db.execute(
        text(
            """
        SELECT verification_code, sha256, byte_size, document_type, filename,
               forest_name, geometry_version, inventory_calculation_id,
               field_inventory_calculation_id, provenance, issued_at,
               calculation_id, plan_id
        FROM public.document_issuances
        WHERE upper(verification_code) = upper(:code)
    """
        ),
        {"code": verification_code.strip()},
    ).first()
    if row is None:
        return None
    return {
        "verification_code": row[0],
        "sha256": row[1],
        "byte_size": row[2],
        "document_type": row[3],
        "filename": row[4],
        "forest_name": row[5],
        "geometry_version": row[6],
        "inventory_calculation_id": str(row[7]) if row[7] else None,
        "field_inventory_calculation_id": str(row[8]) if row[8] else None,
        "provenance": row[9],
        "issued_at": row[10].isoformat() if row[10] else None,
        "calculation_id": str(row[11]) if row[11] else None,
        "plan_id": str(row[12]) if row[12] else None,
    }


# ── submission (WORKSPACE_FLOW_NAV_PLAN P1, D8/D17) ──────────────────────
def record_submission(
    db: Session,
    *,
    submitted_to: str,
    plan_id: Optional[UUID] = None,
    calculation_id: Optional[UUID] = None,
    issuance_id: Optional[UUID] = None,
    channel: str = "hand_delivery",
    reference_no: Optional[str] = None,
    notes: Optional[str] = None,
    submitted_at: Optional[datetime] = None,
) -> Optional[UUID]:
    """Record that an issued document was handed to a receiving office.

    Separate from :func:`record_issuance` because the two facts have different
    lifetimes. An issuance says *these bytes were produced*; a submission says
    *the document left the building, and this office gave it this reference*.
    The statutory route is a printed hard copy, so the reference number the office
    assigns is the only thing that ties a paper document in a district office back
    to a row in this database months later.

    A sibling table rather than more columns, because ``document_issuances`` is
    append-only by a RULE that refuses UPDATE. Rewriting a fact is how audit
    trails die; the constraint is correct and this table honours it.

    Returns the new row id, or None if it could not be recorded. Raises on a
    caller-supplied bad ``channel`` -- unlike an issuance, where a failed write
    must not deny somebody the document they are entitled to, a submission is an
    explicit act with a known-good payload, and silently dropping it would leave
    the user believing a cycle is closed when it is not.
    """
    # Imported lazily for the same reason `record_issuance` does it: pulling
    # `app.models` in at module scope risks an import cycle, since a model
    # module may reach back for document recording.
    from ..core.correlation import get_correlation_id
    from ..core.request_context import get_identity
    from ..models.document_submission import SUBMISSION_CHANNELS

    if channel not in SUBMISSION_CHANNELS:
        raise ValueError(
            f"unknown submission channel {channel!r}; expected one of {list(SUBMISSION_CHANNELS)}"
        )
    submitted_to = (submitted_to or "").strip()
    if not submitted_to:
        raise ValueError("submitted_to is required: a submission must name a receiving office")

    identity = get_identity()
    try:
        row = db.execute(
            text(
                """
            INSERT INTO public.document_submissions
                (issuance_id, calculation_id, plan_id, submitted_to, submitted_at,
                 channel, reference_no, notes, submitted_by, ip_address,
                 client_type, correlation_id)
            VALUES
                (:issuance_id, :calculation_id, :plan_id, :submitted_to,
                 COALESCE(:submitted_at, now()), :channel, :reference_no, :notes,
                 :submitted_by, :ip_address, :client_type, :correlation_id)
            RETURNING id
        """
            ),
            {
                "issuance_id": str(issuance_id) if issuance_id else None,
                "calculation_id": str(calculation_id) if calculation_id else None,
                "plan_id": str(plan_id) if plan_id else None,
                "submitted_to": submitted_to,
                "submitted_at": submitted_at,
                "channel": channel,
                "reference_no": (reference_no or "").strip() or None,
                "notes": notes,
                "submitted_by": str(identity.user_id) if identity.user_id else None,
                "ip_address": identity.ip_address,
                "client_type": identity.client_type,
                "correlation_id": get_correlation_id(),
            },
        ).first()
        db.commit()
        new_id = row[0] if row else None
        logger.info(
            "document submitted: plan=%s to=%r channel=%s ref=%r id=%s",
            plan_id, submitted_to, channel, reference_no, new_id,
        )
        return new_id
    except Exception:
        try:
            db.rollback()
        except Exception:  # noqa: BLE001 -- rollback failure must not mask the original
            pass
        logger.error(
            "document integrity: FAILED to record submission of plan %s to %r. "
            "The user believes this cycle is closed and the system has no record "
            "that it is.", plan_id, submitted_to, exc_info=True,
        )
        raise


def list_submissions(
    db: Session, *, plan_id: Optional[UUID] = None, limit: int = 50
) -> list[dict[str, Any]]:
    """Submissions for a plan, newest first. Never raises."""
    try:
        rows = db.execute(
            text(
                """
        SELECT id, issuance_id, calculation_id, plan_id, submitted_to, submitted_at,
               channel, reference_no, notes, submitted_by, ip_address, client_type,
               correlation_id
        FROM public.document_submissions
        WHERE (:plan_id IS NULL OR plan_id = :plan_id)
        ORDER BY submitted_at DESC, id DESC
        LIMIT :limit
    """
            ),
            {"plan_id": str(plan_id) if plan_id else None, "limit": max(1, min(int(limit), 500))},
        ).fetchall()
    except Exception:  # noqa: BLE001 -- a read must not 500 the page
        logger.exception("document integrity: FAILED to list submissions for plan %s", plan_id)
        return []
    return [
        {
            "id": str(r[0]),
            "issuance_id": str(r[1]) if r[1] else None,
            "calculation_id": str(r[2]) if r[2] else None,
            "plan_id": str(r[3]) if r[3] else None,
            "submitted_to": r[4],
            "submitted_at": r[5].isoformat() if r[5] else None,
            "channel": r[6],
            "reference_no": r[7],
            "notes": r[8],
            "submitted_by": str(r[9]) if r[9] else None,
            "ip_address": r[10],
            "client_type": r[11],
            "correlation_id": r[12],
        }
        for r in rows
    ]
