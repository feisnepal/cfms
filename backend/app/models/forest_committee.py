"""
Forest User Committee Models
"""
from sqlalchemy import Index, Column, String, Integer, Boolean, DateTime, ForeignKey, CheckConstraint, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
import uuid

from ..core.database import Base


class ForestUserCommittee(Base):
    """
    Main Forest User Committee (सामुदायिक वन उपभोक्ता समिति)
    Maximum 15 members
    """
    __tablename__ = "forest_user_committee"
    __table_args__ = (
        Index('idx_forest_committee_calculation_id', 'calculation_id'),
        Index('idx_forest_committee_serial_no', 'calculation_id', 'serial_no'),
        CheckConstraint(
            "gender IN ('महिला', 'पुरूष')",
            name="check_gender_values"
        ),
        CheckConstraint(
            "position IN ('अध्यक्ष', 'उपाध्यक्ष', 'कोषाध्यक्ष', 'सह कोषाध्यक्ष', 'सचिव', 'सह सचिव', 'सदस्य')",
            name="check_position_values"
        ),
        CheckConstraint(
            "caste_category IN ('जनजाती', 'आदिवासी', 'दलित', 'सिमान्तकृत', 'अन्य')",
            name="check_caste_category_values"
        ),
        CheckConstraint(
            "serial_no >= 1 AND serial_no <= 15",
            name="check_serial_no_range"
        ),
        CheckConstraint(
            "mobile IS NULL OR length(mobile) = 10",
            name="check_mobile_length"
        ))

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    calculation_id = Column(UUID(as_uuid=True), ForeignKey('calculations.id', ondelete='CASCADE'), nullable=False)

    # Committee member details
    serial_no = Column(Integer, nullable=False)  # सि.नं. (1-15)
    gender = Column(String(10), nullable=False)  # लिङ्ग (महिला/पुरूष)
    position = Column(String(50), nullable=False)  # पद
    caste_category = Column(String(50), nullable=False)  # जातिय वर्ग
    name = Column(String(200), nullable=False)  # नाम
    address = Column(Text, nullable=True)  # ठेगाना (optional)
    mobile = Column(String(10), nullable=True)  # मोवाइल नंवर (optional)

    # Metadata
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    created_by = Column(UUID(as_uuid=True), ForeignKey('users.id'), nullable=False)

    # Relationships
    calculation = relationship("Calculation", back_populates="forest_committee_members")
    created_by_user = relationship("User", foreign_keys=[created_by])

    def __repr__(self):
        return f"<ForestUserCommittee(name={self.name}, position={self.position}, serial_no={self.serial_no})>"


class AdvisoryCommittee(Base):
    """
    Advisory Committee (सल्लाहाकार समिति)
    Maximum 10 members, optional
    """
    __tablename__ = "advisory_committee"
    __table_args__ = (
        Index('idx_advisory_committee_calculation_id', 'calculation_id'),
        CheckConstraint(
            "serial_no >= 1 AND serial_no <= 10",
            name="check_advisory_serial_no_range"
        ),
        CheckConstraint(
            "mobile IS NULL OR length(mobile) = 10",
            name="check_advisory_mobile_length"
        ))

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    calculation_id = Column(UUID(as_uuid=True), ForeignKey('calculations.id', ondelete='CASCADE'), nullable=False)

    # Committee member details
    serial_no = Column(Integer, nullable=False)  # सि.नं. (1-10)
    name = Column(String(200), nullable=False)  # नाम
    address = Column(Text, nullable=True)  # ठेगाना (optional)
    mobile = Column(String(10), nullable=True)  # मोवाइल नंवर (optional)

    # Metadata
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    created_by = Column(UUID(as_uuid=True), ForeignKey('users.id'), nullable=False)

    # Relationships
    calculation = relationship("Calculation", back_populates="advisory_committee_members")
    created_by_user = relationship("User", foreign_keys=[created_by])

    def __repr__(self):
        return f"<AdvisoryCommittee(name={self.name}, serial_no={self.serial_no})>"


class FinancialCommittee(Base):
    """
    Financial Committee (आर्थिक समिति)
    Maximum 10 members, optional
    """
    __tablename__ = "financial_committee"
    __table_args__ = (
        Index('idx_financial_committee_calculation_id', 'calculation_id'),
        CheckConstraint(
            "serial_no >= 1 AND serial_no <= 10",
            name="check_financial_serial_no_range"
        ),
        CheckConstraint(
            "mobile IS NULL OR length(mobile) = 10",
            name="check_financial_mobile_length"
        ))

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    calculation_id = Column(UUID(as_uuid=True), ForeignKey('calculations.id', ondelete='CASCADE'), nullable=False)

    # Committee member details
    serial_no = Column(Integer, nullable=False)  # सि.नं. (1-10)
    name = Column(String(200), nullable=False)  # नाम
    address = Column(Text, nullable=True)  # ठेगाना (optional)
    mobile = Column(String(10), nullable=True)  # मोवाइल नंवर (optional)

    # Metadata
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    created_by = Column(UUID(as_uuid=True), ForeignKey('users.id'), nullable=False)

    # Relationships
    calculation = relationship("Calculation", back_populates="financial_committee_members")
    created_by_user = relationship("User", foreign_keys=[created_by])

    def __repr__(self):
        return f"<FinancialCommittee(name={self.name}, serial_no={self.serial_no})>"
