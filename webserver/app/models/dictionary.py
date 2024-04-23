from datetime import datetime
from sqlalchemy import Column, Integer, DateTime, String, ForeignKey, UniqueConstraint
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.helpers.db import BaseModel, db
from app.models.dataset import Dataset

class Dictionary( db.Model, BaseModel):
    __tablename__ = 'dictionaries'
    __table_args__ = (
        UniqueConstraint('table_name', 'dataset_id', 'field_name'),
    )
    id = Column(Integer, primary_key=True, autoincrement=True)
    table_name = Column(String(256), nullable=False)
    field_name = Column(String(256))
    label = Column(String(256))
    description = Column(String(4096), nullable=False)
    created_at = Column(DateTime(timezone=False), server_default=func.now())
    updated_at = Column(DateTime(timezone=False), onupdate=func.now())

    dataset_id = Column(Integer, ForeignKey(Dataset.id, ondelete='CASCADE'))
    dataset = relationship("Dataset")

    def __init__(self,
                 table_name:str,
                 description:str,
                 dataset:Dataset,
                 label:str='',
                 field_name:str='',
                 created_at:datetime=datetime.now(),
                 ):
        self.table_name = table_name
        self.description = description
        self.dataset = dataset
        self.label = label
        self.field_name = field_name
        self.created_at = created_at
        self.updated_at = datetime.now()
