from sqlalchemy import Column, Integer, Boolean, ForeignKey
from sqlalchemy.orm import relationship
from app.helpers.base_model import BaseModel, db
from app.models.dataset import Dataset
from app.models.container import Container
from app.helpers.exceptions import DatasetContainerException


class DatasetContainer(db.Model, BaseModel):
    __tablename__ = 'datasetcontainers'

    all = Column(Boolean(), default=False)
    use = Column(Boolean(), default=False)

    id = Column(Integer, primary_key=True, autoincrement=True)
    dataset_id = Column(Integer, ForeignKey(Dataset.id, ondelete='CASCADE'), nullable=True)
    dataset = relationship("Dataset")

    container_id = Column(Integer, ForeignKey(Container.id, ondelete='CASCADE'), nullable=True)
    container = relationship("Container")

    def __init__(
            self,
            dataset:Dataset=None,
            container:Container=None,
            all:bool=False,
            use:bool=False
        ):
        super().__init__()
        self.dataset = dataset
        self.container = container
        self.all = all
        self.use = use

    @classmethod
    def get_by_dataset(cls, dataset:Dataset, to_dict:bool=False) -> list:
        """
        Simply fetch by dataset, and format for output
        """
        dcs = DatasetContainer.query.join(
            Container, isouter=True
        ).filter(
            DatasetContainer.dataset_id == dataset.id,
            ((DatasetContainer.use == True) | (DatasetContainer.all == True))
        ).all()
        if not to_dict:
            return dcs

        parsed_list = []
        for dc in dcs:
            if not dc.container:
                return ['*']

            parsed_list.append(dc.container.sanitized_dict())
        return parsed_list
