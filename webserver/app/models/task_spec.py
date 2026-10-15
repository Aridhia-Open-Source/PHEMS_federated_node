import sqlalchemy as sa
from sqlalchemy.orm import relationship

from app.helpers.base_model import BaseModel, db
from app.helpers.const import TASK_IMAGE_MAX_LENGTH


class TaskSpec(db.Model, BaseModel):
    """
    What a task runs: the image, the dataset it runs against, if any, and its env.
    """
    __tablename__ = 'task_specs'

    id = sa.Column(sa.Integer, primary_key=True, autoincrement=True)
    image = sa.Column(sa.String(TASK_IMAGE_MAX_LENGTH), nullable=False)
    dataset_id = sa.Column(sa.Integer, sa.ForeignKey('datasets.id', ondelete='CASCADE'), nullable=True)
    env = sa.Column(sa.JSON, nullable=False, server_default='{}')

    dataset = relationship("Dataset")

    def __init__(self, image: str, dataset_id: int | None, env: dict):
        self.image = image
        self.dataset_id = dataset_id
        self.env = env
