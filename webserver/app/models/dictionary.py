from datetime import datetime
from sqlalchemy import Column, Integer, DateTime, String, ForeignKey, UniqueConstraint
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.helpers.base_model import BaseModel, db
from app.helpers.exceptions import InvalidRequest
from app.models.dataset import Dataset

class Dictionary( db.Model, BaseModel):
    __tablename__ = 'dictionaries'
    __table_args__ = (
        UniqueConstraint('table_name', 'dataset_id', 'field_name'),
    )
    id = Column(Integer, primary_key=True, autoincrement=True)
    table_name = Column(String(256), nullable=False)
    field_name = Column(String(256), nullable=False)
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
                 **kwargs):
        self.table_name = table_name
        self.description = description
        self.dataset = dataset
        self.label = label
        self.field_name = field_name
        self.created_at = created_at
        self.updated_at = datetime.now()

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
