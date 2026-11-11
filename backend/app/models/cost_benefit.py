"""Cost-Benefit Analysis (CBA) — scenario-level financial analysis for a calculation.

Four tables (``CBA_MODULE_PLAN.md`` P0):

- ``cost_benefit_analyses`` — one row per *scenario* (base / high-harvest / …).
- ``cba_cost_items`` / ``cba_benefit_items`` — the editable line items. A row is
  *auto* (``source_link`` set — overwritten by re-populate) or *manual*
  (``source_link IS NULL`` — never touched).
- ``cba_results`` — the cached NPV / IRR / B-C / payback for one scenario,
  recomputed on demand.

History: this module was built in July 2026, lost when the repo was
re-initialised, and rebuilt from the recovered artefacts. The four tables
already exist in ``cf_db``; migration ``079_cba_models`` is idempotent.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship

from app.core.database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class CostBenefitAnalysis(Base):
    """A CBA scenario. Every non-computed field is user-editable in the UI."""

    __tablename__ = "cost_benefit_analyses"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    calculation_id = Column(
        UUID(as_uuid=True),
        ForeignKey("calculations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name = Column(String(200), nullable=False, default="Base Scenario")
    description = Column(Text)
    discount_rate = Column(Numeric(5, 2), nullable=False, default=10.00)
    time_horizon_years = Column(Integer, nullable=False, default=10)
    irr_start_year = Column(Integer, nullable=False, default=1)
    currency = Column(String(3), nullable=False, default="NPR")
    # {timber_sal, timber_mixed, timber_softwood, fuelwood, poles, carbon,
    #  grass, bedding, ntfp: {}} — depot/market rates, editable per scenario.
    default_rates = Column(JSONB, nullable=False, default=dict)
    is_base_scenario = Column(Boolean, nullable=False, default=False)
    status = Column(String(20), nullable=False, default="draft")
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)
    updated_at = Column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id"))

    cost_items = relationship(
        "CBACostItem",
        back_populates="cba",
        cascade="all, delete-orphan",
        order_by="CBACostItem.display_order",
    )
    benefit_items = relationship(
        "CBABenefitItem",
        back_populates="cba",
        cascade="all, delete-orphan",
        order_by="CBABenefitItem.display_order",
    )
    result = relationship(
        "CBAResult",
        back_populates="cba",
        uselist=False,
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return (
            f"<CostBenefitAnalysis(id={self.id}, name={self.name!r}, "
            f"is_base={self.is_base_scenario})>"
        )


class CBACostItem(Base):
    """One cost line item. ``total_amount`` is computed in Python on write."""

    __tablename__ = "cba_cost_items"
    __table_args__ = (
        CheckConstraint(
            "year_from >= 1 AND year_to >= year_from", name="ck_cost_year_range"
        ),
        CheckConstraint("amount_per_year >= 0", name="ck_cost_amount"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    cba_id = Column(
        UUID(as_uuid=True),
        ForeignKey("cost_benefit_analyses.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    category = Column(String(200), nullable=False)
    description = Column(Text, nullable=False, default="")
    year_from = Column(Integer, nullable=False, default=1)
    year_to = Column(Integer, nullable=False, default=1)
    amount_per_year = Column(Numeric(14, 2), nullable=False, default=0)
    is_recurring = Column(Boolean, nullable=False, default=False)
    total_amount = Column(Numeric(14, 2))  # computed: amount_per_year * n_years
    source_link = Column(String(200))  # "activity:{uuid}" etc.; NULL = manual
    notes = Column(Text)
    display_order = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)
    updated_at = Column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )

    cba = relationship("CostBenefitAnalysis", back_populates="cost_items")


class CBABenefitItem(Base):
    """One benefit line item. ``amount_per_year`` defaults to
    ``quantity * unit_price`` on auto-populate but is directly editable."""

    __tablename__ = "cba_benefit_items"
    __table_args__ = (
        CheckConstraint(
            "year_from >= 1 AND year_to >= year_from", name="ck_benefit_year_range"
        ),
        CheckConstraint("amount_per_year >= 0", name="ck_benefit_amount"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    cba_id = Column(
        UUID(as_uuid=True),
        ForeignKey("cost_benefit_analyses.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    source = Column(String(50), nullable=False)  # timber | fuelwood | carbon | ntfp | …
    description = Column(Text, nullable=False, default="")
    year_from = Column(Integer, nullable=False, default=1)
    year_to = Column(Integer, nullable=False, default=1)
    quantity = Column(Numeric(14, 2))  # m3 / kg / tCO2e / count
    unit_price = Column(Numeric(12, 2))  # NPR per unit
    amount_per_year = Column(Numeric(14, 2), nullable=False, default=0)
    is_recurring = Column(Boolean, nullable=False, default=False)
    total_amount = Column(Numeric(14, 2))  # computed
    source_link = Column(String(200))  # "block:{name}:timber" etc.; NULL = manual
    notes = Column(Text)
    display_order = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)
    updated_at = Column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )

    cba = relationship("CostBenefitAnalysis", back_populates="benefit_items")


class CBAResult(Base):
    """Cached computation for one scenario. Recomputed on any cost/benefit edit
    or an explicit ``POST /cba/{id}/compute``."""

    __tablename__ = "cba_results"
    __table_args__ = (UniqueConstraint("cba_id", name="uq_cba_results"),)

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    cba_id = Column(
        UUID(as_uuid=True),
        ForeignKey("cost_benefit_analyses.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    npv = Column(Numeric(16, 2))
    irr = Column(Numeric(8, 4))  # NULL when undefined (no sign change / no convergence)
    benefit_cost_ratio = Column(Numeric(10, 4))  # NULL when PV(cost) == 0
    payback_period_years = Column(Numeric(6, 2))
    total_cost_pv = Column(Numeric(16, 2))
    total_benefit_pv = Column(Numeric(16, 2))
    cash_flow_data = Column(JSONB)  # [{year, cost, benefit, net}, ...]
    computed_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)

    cba = relationship("CostBenefitAnalysis", back_populates="result")
