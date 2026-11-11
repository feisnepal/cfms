"""
CommunityForest model - READ-ONLY mapping to existing admin.community_forests table
"""
from sqlalchemy import Column, String, Integer, Index
from geoalchemy2 import Geometry

from ..core.database import Base
from ..core.constants import SQM_PER_HA


class CommunityForest(Base):
    """
    CommunityForest model - READ-ONLY mapping to admin.community_forests
    Represents the 3,922 existing community forest polygons
    """
    __tablename__ = "community forests"
    __table_args__ = (
        Index('sidx_community_forests_geom', 'geom', postgresql_using='gist'),
        {"schema": "admin"}
    )

    id = Column(Integer, primary_key=True)
    geom = Column(Geometry(geometry_type='MULTIPOLYGON', srid=4326), nullable=False)
    name = Column(String(254), nullable=True)
    code = Column(String(20), nullable=True)
    regime = Column(String(20), nullable=True)
    area_sqm = Column("area sqm", Integer, nullable=True)  # Column name has space

    def __repr__(self):
        return f"<CommunityForest(id={self.id}, name={self.name}, code={self.code})>"

    @property
    def area_hectares(self) -> float:
        """Convert square meters to hectares"""
        return self.area_sqm / SQM_PER_HA if self.area_sqm else 0.0
