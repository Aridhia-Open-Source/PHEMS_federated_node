from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import relationship

from app.helpers.base_model import BaseModel, db
from app.helpers.const import TASK_IMAGE_MAX_LENGTH


class TaskSpec(db.Model, BaseModel):
    """
    What a task runs: the image, the dataset it runs against, if any, its env, its compute, its tags, its config and the
    metadata that came with it.
    """
    __tablename__ = 'task_specs'

    id = sa.Column(sa.Integer, primary_key=True, autoincrement=True)
    image = sa.Column(sa.String(TASK_IMAGE_MAX_LENGTH), nullable=False)
    dataset_id = sa.Column(sa.Integer, sa.ForeignKey('datasets.id', ondelete='RESTRICT'), nullable=True)
    env = sa.Column(sa.JSON, nullable=False, server_default='{}')
    # The CPU and memory the spec asked for: Kubernetes requests and limits, only what it gave, no defaults
    compute = sa.Column(sa.JSON, nullable=False, server_default='{}')
    # Copied onto the task's run as tags
    tags = sa.Column(sa.JSON, nullable=False, server_default='{}')
    # A JSON object the task reads as a file, as the spec gave it. Null if the spec has none
    config = sa.Column(sa.JSON, nullable=True)
    # The client's own, any JSON value, not checked. The attribute has a trailing underscore because SQLAlchemy
    # reserves `metadata`: the column and the API key are `metadata`
    metadata_ = sa.Column("metadata", sa.JSON, nullable=True)

    dataset = relationship("Dataset")

    def __init__(
        self, image: str, dataset_id: int | None, env: dict, compute: dict | None = None, tags: dict | None = None,
        config: dict | None = None, metadata: Any = None
    ):
        self.image = image
        self.dataset_id = dataset_id
        self.env = env
        # None would be stored as a JSON null, not the empty object the column's default means
        self.compute = compute or {}
        self.tags = tags or {}
        self.config = config
        self.metadata_ = metadata
