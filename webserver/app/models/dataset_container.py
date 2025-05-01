from sqlalchemy import Column, Integer, Boolean, ForeignKey
from sqlalchemy.orm import relationship
from app.helpers.base_model import BaseModel, db
from app.models.dataset import Dataset
from app.models.container import Container
from app.helpers.exceptions import DatasetContainerException


class DatasetContainer(db.Model, BaseModel):
    __tablename__ = 'datasetcontainers'

    all = Column(Boolean, default=False)

    dataset_id = Column(Integer, ForeignKey(Dataset.id, ondelete='CASCADE'), nullable=True)
    dataset = relationship("Dataset")

    container_id = Column(Integer, ForeignKey(Container.id, ondelete='CASCADE'), nullable=True)
    container = relationship("Container")

    def __init__(
            self,
            dataset:Dataset=None,
            container:Container=None,
            all:bool=False,
        ):
        super().__init__()
        self.dataset = dataset
        self.container = container
        self.all = all

    def validate(self, data:dict):
        dataset = Dataset.query.filter_by(id=data.get("dataset_id")).one_or_none()
        container = Container.query.filter_by(id=data.get("container_id")).one_or_none()
        if not dataset and not container:
            raise DatasetContainerException("Dataset or Container has to be provided")

        all = data.get("all")


