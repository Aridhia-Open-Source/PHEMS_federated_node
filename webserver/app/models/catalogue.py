from typing import Any
from datetime import datetime as dt

from sqlalchemy import Integer, DateTime, String, ForeignKey, UniqueConstraint, select, update
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.orm.properties import MappedColumn
from sqlalchemy.sql import func
from app.helpers.base_model import BaseModel
from app.models.dataset import Dataset


class Catalogue(BaseModel):
    __tablename__ = 'catalogues'
    __table_args__ = (
        UniqueConstraint('title', 'dataset_id'),
    )
    id: MappedColumn[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    version: MappedColumn[str] = mapped_column(String(256))
    title: MappedColumn[str] = mapped_column(String(256), nullable=False)
    description: MappedColumn[str] = mapped_column(String(4096), nullable=False)
    created_at: MappedColumn[dt] = mapped_column(DateTime(timezone=False), server_default=func.now())
    updated_at: MappedColumn[dt] = mapped_column(DateTime(timezone=False), onupdate=func.now(), nullable=True)

    dataset_id: MappedColumn[Any] = mapped_column(Integer, ForeignKey(Dataset.id, ondelete='CASCADE'))
    dataset:Mapped["Dataset"] = relationship("Dataset")
