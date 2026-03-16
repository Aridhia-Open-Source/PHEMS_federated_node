from datetime import datetime as dt
from sqlalchemy import Integer, DateTime, String, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, relationship, mapped_column
from sqlalchemy.orm.properties import MappedColumn
from sqlalchemy.sql import func

from app.helpers.base_model import BaseModel
from app.models.dataset import Dataset


class Dictionary(BaseModel):
    __tablename__ = 'dictionaries'
    __table_args__ = (
        UniqueConstraint('table_name', 'dataset_id', 'field_name'),
    )
    id: MappedColumn[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    table_name: MappedColumn[str] = mapped_column(String(256), nullable=False)
    field_name: MappedColumn[str] = mapped_column(String(256), nullable=False)
    label: MappedColumn[str] = mapped_column(String(256), nullable=True)
    description: MappedColumn[str] = mapped_column(String(4096), nullable=False)
    created_at: Mapped[dt] = mapped_column(DateTime(timezone=False), nullable=False, insert_default=func.now())
    updated_at: Mapped[dt] = mapped_column(DateTime(timezone=False), nullable=True, onupdate=func.now())

    dataset_id: MappedColumn[int] = mapped_column(Integer, ForeignKey(Dataset.id, ondelete='CASCADE'))
    dataset: Mapped["Dataset"] = relationship("Dataset")
