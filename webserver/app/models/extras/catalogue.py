from datetime import datetime as dt

import sqlalchemy as sa
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.helpers.base_model import BaseModel, db
from app.models.dataset import Dataset
from app.helpers.exceptions import InvalidRequest


class Catalogue(db.Model, BaseModel):
    __tablename__ = 'catalogues'

    id = sa.Column(sa.Integer, primary_key=True, autoincrement=True)
    dataset_id = sa.Column(sa.Integer, sa.ForeignKey('datasets.id', ondelete='CASCADE'), nullable=True)
    version = sa.Column(sa.String(256), nullable=True, default='1')
    title = sa.Column(sa.String(256), nullable=False)
    description = sa.Column(sa.String(4096), nullable=False)
    created_at = sa.Column(sa.DateTime(timezone=False), nullable=False, server_default=func.now())
    updated_at = sa.Column(
        sa.DateTime(timezone=False), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    dataset = relationship("Dataset")

    __table_args__ = (
        sa.UniqueConstraint('title', 'dataset_id'),
    )

    def __init__(self,
                 title: str,
                 description: str,
                 dataset: Dataset,
                 version: str = '1',
                 **kwargs
    ):
        self.version = version
        self.title = title
        self.dataset = dataset
        self.description = description

    def update(self, **data):
        for k, v in data.items():
            if not hasattr(self, k):
                raise InvalidRequest(f"Field {k} is not a valid one")
            else:
                setattr(self, k, v)
        self.query.filter(Catalogue.id == self.id).update(data, synchronize_session='evaluate')

    @classmethod
    def update_or_create(cls, data:dict, ds:Dataset):
        """
        """
        current_cata = cls.query.filter(cls.dataset_id == ds.id).one_or_none()
        if current_cata:
            current_cata.update(**data)
        else:
            cata_body = cls.validate(data)
            catalogue = cls(dataset=ds, **cata_body)
            catalogue.add(commit=False)
