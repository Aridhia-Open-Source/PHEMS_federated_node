from sqlalchemy import Integer, DateTime, String, ForeignKey, UniqueConstraint, select, update
from sqlalchemy.orm import relationship, mapped_column
from sqlalchemy.sql import func
from app.helpers.base_model import BaseModel, get_db
from app.helpers.exceptions import InvalidRequest
from app.models.dataset import Dataset


class Dictionary(BaseModel):
    __tablename__ = 'dictionaries'
    __table_args__ = (
        UniqueConstraint('table_name', 'dataset_id', 'field_name'),
    )
    id = mapped_column(Integer, primary_key=True, autoincrement=True)
    table_name = mapped_column(String(256), nullable=False)
    field_name = mapped_column(String(256), nullable=False)
    label = mapped_column(String(256))
    description = mapped_column(String(4096), nullable=False)
    created_at = mapped_column(DateTime(timezone=False), server_default=func.now())
    updated_at = mapped_column(DateTime(timezone=False), onupdate=func.now())

    dataset_id = mapped_column(Integer, ForeignKey(Dataset.id, ondelete='CASCADE'))
    dataset = relationship("Dataset")
