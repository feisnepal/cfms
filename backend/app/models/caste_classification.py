"""
Caste Classification reference model
Stores surname-to-caste mapping for auto-classification
"""
from sqlalchemy import Index, Column, String, Integer, UniqueConstraint
from ..core.database import Base


class CasteClassification(Base):
    """
    Caste Classification reference table
    Maps surnames to caste classifications (जातिय वर्गिकरण)
    Data source: testData/households_information/caste_classification.csv
    Note: Same surname can appear in multiple castes/classifications
    """
    __tablename__ = "caste_classification"
    __table_args__ = (
        Index('idx_caste_surname', 'surname_ne'),
    )
    id = Column(Integer, primary_key=True, autoincrement=True)
    classification_ne = Column(String(100), nullable=False)  # जनजाती, दलित, etc.
    caste_ne = Column(String(100), nullable=False)  # मगर, गुरुङ, etc.
    surname_ne = Column(String(100), nullable=False)  # थापा, राना, etc.
    classification_en = Column(String(100), nullable=True)
    caste_en = Column(String(100), nullable=True)
    surname_en = Column(String(100), nullable=True)

    def __repr__(self):
        return f"<CasteClassification(surname={self.surname_ne}, classification={self.classification_ne})>"
