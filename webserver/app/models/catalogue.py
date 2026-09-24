from sqlalchemy import Column, Integer, String, ForeignKey, UniqueConstraint
from sqlalchemy.orm import relationship

from app.models import SqlaColumn
from app.helpers.base_model import BaseModel, db
from app.models.dataset import Dataset
from app.helpers.exceptions import InvalidRequest


class Catalogue(db.Model, BaseModel):
    __tablename__ = 'catalogues'
    __table_args__ = (
        UniqueConstraint('title', 'dataset_id'),
    )
    id = Column(Integer, primary_key=True, autoincrement=True)
    version = Column(String(256))
    title = Column(String(256), nullable=False)
    description = Column(String(4096), nullable=False)
    created_at = SqlaColumn.created_at()
    updated_at = SqlaColumn.updated_at()

    dataset_id = Column(Integer, ForeignKey(Dataset.id, ondelete='CASCADE'))
    dataset = relationship("Dataset")

    def __init__(
        self,
        title: str,
        description: str,
        version: str = '1',
        dataset_id: int | None = None,
        dataset: Dataset | None = None,
    ):
        self.title = title
        self.description = description
        self.version = version
        self.dataset_id = dataset_id
        if dataset is not None:
            self.dataset = dataset

    def update(self, **data):
        for k, v in data.items():
            if hasattr(self, k):
                setattr(self, k, v)
                continue

            raise InvalidRequest(f"Field {k} is invalid.")

        update_data = {getattr(Catalogue, k): v for k, v in data.items()}
        q = self.query.filter(Catalogue.id == self.id)
        q.update(update_data, synchronize_session='evaluate')

    @classmethod
    def update_or_create(cls, data: dict, ds: Dataset):
        """
        Update the dataset's catalogue if it already has one, otherwise create it.
        """
        if current_cata := cls.query.filter(cls.dataset_id == ds.id).one_or_none():  # pyright: ignore[reportArgumentType]
            current_cata.update(**data)
            return

        cata_body = cls.validate(data)
        catalogue = cls(dataset=ds, **cata_body)
        catalogue.add(commit=False)
