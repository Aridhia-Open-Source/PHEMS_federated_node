import sqlalchemy as sa
from sqlalchemy.orm import relationship

from app.helpers.base_model import BaseModel, db
from app.helpers.const import TASK_IMAGE_MAX_LENGTH


class TaskSpec(db.Model, BaseModel):
    """
    What a task runs: the image, the dataset it runs against, if any, its env and its CPU and memory resources.
    """
    __tablename__ = 'task_specs'

    id = sa.Column(sa.Integer, primary_key=True, autoincrement=True)
    image = sa.Column(sa.String(TASK_IMAGE_MAX_LENGTH), nullable=False)
    dataset_id = sa.Column(sa.Integer, sa.ForeignKey('datasets.id', ondelete='RESTRICT'), nullable=True)
    env = sa.Column(sa.JSON, nullable=False, server_default='{}')
    # Kubernetes requests and limits for the task's container, as the spec gave them
    resources = sa.Column(sa.JSON, nullable=False, server_default='{}')

    dataset = relationship("Dataset")

    def __init__(self, image: str, dataset_id: int | None, env: dict, resources: dict | None = None):
        self.image = image
        self.dataset_id = dataset_id
        self.env = env
        # None would be stored as a JSON null, not the empty object the column's default means
        self.resources = resources or {}
