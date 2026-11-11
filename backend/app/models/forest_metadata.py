"""Forest metadata: the facts about a forest that a person writes down.

WORKSPACE_FLOW_NAV_PLAN D5 puts "Forest Metadata" as the third tab of the Field
Inventory page, because that is where the information is actually gathered --
someone stands in the compartment with a GPS unit and a field sheet. It used to
live in the component state of `ReportTab`, which meant:

  * it was lost on reload, and
  * nothing else could read it, so every .docx generation re-posted it from the
    browser. Two people generating a report for the same forest produced
    different cover pages, and neither of those cover pages was a record.

So it is a table. A dedicated table rather than a JSONB blob inside
`calculations.result_data`, because these are *authored* facts, not computed
results: they have a fixed shape, they are validated, they change on their own
schedule, and mixing them into `result_data` would put a form's output in the
same bag as a species tally -- so every reader would have to know which is which.

1:1 with a calculation, enforced by a UNIQUE constraint rather than by
convention, because the alternative is a forest with two competing cover pages
and no way to say which one is current.

`fy_start` / `fy_end` are free text, not integers or dates. That is deliberate:
the cover page prints them verbatim
(`services/report/document_builder.py:79`) and a Nepali fiscal year is written
"2081/82", "2081/2082" or "२०८१/८२" depending on who is typing. Storing an int
would force one spelling and reject the other two, which is a validation rule
nobody asked for. The length caps are the guard instead.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID

from ..core.database import Base


class ForestMetadata(Base):
    """One forest's identifying details, as recorded in the field."""

    __tablename__ = "forest_metadata"
    __table_args__ = (
        # The 1:1. Not a primary key on calculation_id only so the row keeps an
        # identity of its own for audit and for the report to point at.
        UniqueConstraint(
            "calculation_id", name="uq_forest_metadata_calculation_id"
        ),
        CheckConstraint(
            "char_length(trim(cf_national_code)) <= 32",
            name="ck_forest_metadata_cf_national_code_len",
        ),
        CheckConstraint(
            "char_length(trim(fy_start)) <= 32", name="ck_forest_metadata_fy_start_len"
        ),
        CheckConstraint(
            "char_length(trim(fy_end)) <= 32", name="ck_forest_metadata_fy_end_len"
        ),
        Index("ix_forest_metadata_updated_at", "updated_at"),
    )

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=func.gen_random_uuid(),
    )

    # CASCADE, unlike `document_submissions`. The difference is the point of that
    # table: a statutory handover must outlive the forest. This row is a
    # description *of* the forest, so it goes when the forest does -- and a
    # surviving orphan would let a deleted forest's cover page be regenerated.
    calculation_id = Column(
        UUID(as_uuid=True),
        ForeignKey("calculations.id", ondelete="CASCADE"),
        nullable=False,
    )

    # --- identification
    forest_name = Column(String(255), nullable=True)
    group_name = Column(String(255), nullable=True)
    province = Column(String(255), nullable=True)
    district = Column(String(255), nullable=True)
    palika = Column(String(255), nullable=True)
    ward = Column(String(64), nullable=True)
    division = Column(String(255), nullable=True)
    sub_division = Column(String(255), nullable=True)
    address = Column(Text, nullable=True)

    # --- the identifiers the forest office files the report under
    serial_number = Column(String(64), nullable=True)
    # The one community-forest code: the national database code of Schedule 11 (PPP/DDD/SS/LL/NNN).
    cf_national_code = Column(String(32), nullable=True)

    # --- reporting period, printed verbatim on the cover page
    fy_start = Column(String(32), nullable=True)
    fy_end = Column(String(32), nullable=True)

    # --- plan details that belong to the forest, entered once here and used by every plan (OPTIONAL: they are not
    #     part of the mandatory form and never keep the Forest Metadata step red). The plan's own form wins when filled.
    sub_division_chief = Column(String(255), nullable=True)
    forest_management_section_chief = Column(String(255), nullable=True)
    division_forest_officer = Column(String(255), nullable=True)
    technical_assistance_org = Column(String(255), nullable=True)
    cf_handover_date = Column(String(32), nullable=True)
    cf_first_renewal_date = Column(String(32), nullable=True)
    cf_history_note = Column(Text, nullable=True)
    # forest / group facts moved here from the plan's Metadata form (owner 2026-10-14: entered once, no per-plan copy)
    cf_registration_number = Column(String(64), nullable=True)
    constitution_approved_year = Column(String(32), nullable=True)
    user_group_reg_no = Column(String(32), nullable=True)
    cf_sn_number = Column(String(32), nullable=True)
    cf_boundary_east = Column(Text, nullable=True)
    cf_boundary_south = Column(Text, nullable=True)
    cf_boundary_west = Column(Text, nullable=True)
    cf_boundary_north = Column(Text, nullable=True)
    physiography_zone = Column(String(255), nullable=True)
    protected_area_status = Column(String(255), nullable=True)
    forest_type = Column(String(64), nullable=True)
    forest_abundance = Column(String(64), nullable=True)
    forest_avg_age = Column(String(32), nullable=True)
    main_non_timber_fp = Column(Text, nullable=True)
    avg_crown_density_pct = Column(String(32), nullable=True)
    ug_province = Column(String(255), nullable=True)
    ug_district = Column(String(255), nullable=True)
    ug_municipality = Column(String(255), nullable=True)
    ug_municipality_type = Column(String(64), nullable=True)
    ug_ward = Column(String(64), nullable=True)
    ug_division = Column(String(255), nullable=True)
    ug_sub_division = Column(String(255), nullable=True)
    ug_settlement = Column(String(255), nullable=True)
    ug_boundary_east = Column(Text, nullable=True)
    ug_boundary_south = Column(Text, nullable=True)
    ug_boundary_west = Column(Text, nullable=True)
    ug_boundary_north = Column(Text, nullable=True)

    # --- audit. `updated_by` is a plain id, not an FK to users, so that
    # deactivating a user does not cascade into losing the record of who wrote
    # the cover page.
    created_at = Column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
    updated_by = Column(UUID(as_uuid=True), nullable=True)

    def __repr__(self):
        return (
            f"<ForestMetadata(calculation_id={self.calculation_id}, "
            f"forest_name={self.forest_name!r}, cf_national_code={self.cf_national_code!r})>"
        )
