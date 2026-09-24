"""
Projects, the top of the ownership chain.
"""
from sqlalchemy import Column, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.models import SqlaColumn
from app.helpers.base_model import BaseModel, db


class Project(db.Model, BaseModel):
    __tablename__ = 'projects'

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(256), unique=True, nullable=False)
    description = Column(String(4096), nullable=True)
    created_at = SqlaColumn.created_at()
    updated_at = SqlaColumn.updated_at()

    default_dataset_id = Column(
        Integer,
        ForeignKey(
            'datasets.id', ondelete='SET NULL', use_alter=True,
            name='fk_projects_default_dataset'
        ),
        nullable=True,
    )

    default_dataset = relationship("Dataset", foreign_keys=[default_dataset_id])
    requests = relationship("Request", back_populates="project")
    delivery_targets = relationship("DeliveryTarget", back_populates="project")
    trigger_repositories = relationship("TriggerRepository", back_populates="project")
    whitelisted_images = relationship("WhitelistedImage", back_populates="project")
    datasets = relationship(
        "Dataset",
        back_populates="project",
        foreign_keys="Dataset.project_id"
    )

    def __init__(self, name: str, description: str | None = None, **kwargs):
        self.name = name
        self.description = description
        super().__init__(**kwargs)

    def __repr__(self):
        return f'<Project {self.name}>'
