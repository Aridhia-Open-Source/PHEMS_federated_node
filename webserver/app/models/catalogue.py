from datetime import datetime
from sqlalchemy import Column, Integer, DateTime, String, ForeignKey, UniqueConstraint
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.helpers.base_model import BaseModel, db
from app.models.dataset import Dataset
from app.helpers.exceptions import InvalidRequest

class Catalogue( db.Model, BaseModel):
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

    def __init__(self,
                 title:str,
                 description:str,
                 dataset:Dataset,
                 version:str='1',
                 created_at:datetime=datetime.now(),
                 **kwargs
        ):
        self.version = version
        self.title = title
        self.dataset = dataset
        self.description = description
        self.created_at = created_at
        self.updated_at = datetime.now()

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
