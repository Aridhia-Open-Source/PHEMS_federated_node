from datetime import datetime as dt

import sqlalchemy as sa
from sqlalchemy.orm import relationship

from app.helpers.base_model import BaseModel, db
from app.helpers.exceptions import InvalidRequest
from app.models import sqla_column
from app.models.dataset import Dataset


class Dictionary(db.Model, BaseModel):
    __tablename__ = 'dictionaries'

    id = sa.Column(sa.Integer, primary_key=True, autoincrement=True)
    dataset_id = sa.Column(sa.Integer, sa.ForeignKey('datasets.id', ondelete='CASCADE'), nullable=True)
    table_name = sa.Column(sa.String(256), nullable=False)
    field_name = sa.Column(sa.String(256), nullable=False)
    label = sa.Column(sa.String(256), nullable=True, default='')
    description = sa.Column(sa.String(4096), nullable=False)
    created_at = sqla_column.created_at()
    updated_at = sqla_column.updated_at()

    dataset = relationship("Dataset")

    __table_args__ = (
        sa.UniqueConstraint('table_name', 'dataset_id', 'field_name'),
    )

    def __init__(self,
                 table_name: str,
                 description: str,
                 dataset: Dataset,
                 label: str = '',
                 field_name: str = '',
                 **kwargs):
        self.table_name = table_name
        self.description = description
        self.dataset = dataset
        self.label = label
        self.field_name = field_name

    def update(self, **data):
        for k, v in data.items():
            if not hasattr(self, k):
                raise InvalidRequest(f"Field {k} is not a valid one")
            else:
                setattr(self, k, v)
        self.query.filter(Dictionary.id == self.id).update(data, synchronize_session='evaluate')

    @classmethod
    def update_or_create(cls, data:dict, ds:Dataset):
        cls.validate(data)
        current_dict = cls.query.filter(
            cls.dataset_id == ds.id,
            cls.field_name == data["field_name"],
            cls.table_name == data["table_name"]
        ).one_or_none()
        if current_dict:
            current_dict.update(**data)
        else:
            dict_body = cls.validate(data)
            dictionary = cls(dataset=ds, **dict_body)
            dictionary.add(commit=False)
