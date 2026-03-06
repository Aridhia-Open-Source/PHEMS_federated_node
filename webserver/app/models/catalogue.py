from sqlalchemy import Column, Integer, DateTime, String, ForeignKey, UniqueConstraint, select, update
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.helpers.base_model import BaseModel, get_db
from app.models.dataset import Dataset
from app.helpers.exceptions import InvalidRequest


class Catalogue(BaseModel):
    __tablename__ = 'catalogues'
    __table_args__ = (
        UniqueConstraint('title', 'dataset_id'),
    )
    id = Column(Integer, primary_key=True, autoincrement=True)
    version = Column(String(256))
    title = Column(String(256), nullable=False)
    description = Column(String(4096), nullable=False)
    created_at = Column(DateTime(timezone=False), server_default=func.now())
    updated_at = Column(DateTime(timezone=False), onupdate=func.now())

    dataset_id = Column(Integer, ForeignKey(Dataset.id, ondelete='CASCADE'))
    dataset = relationship("Dataset")
