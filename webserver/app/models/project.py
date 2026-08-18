"""
Projects, the top of the ownership chain.
"""
from sqlalchemy import Column, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.helpers.base_model import BaseModel, db


class Project(db.Model, BaseModel):
    __tablename__ = 'projects'

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(256), unique=True, nullable=False)
    description = Column(String(4096), nullable=True)
    # datasets.project_id already points the other way, so this side has to be deferred or
    # SQLAlchemy cannot order the two CREATE TABLEs.
    default_dataset_id = Column(
        Integer,
        ForeignKey('datasets.id', ondelete='SET NULL', use_alter=True,
                   name='fk_projects_default_dataset'),
        nullable=True,
    )
    created_at = Column(DateTime(timezone=False), nullable=False, server_default=func.now())
    updated_at = Column(
        DateTime(timezone=False), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    datasets = relationship(
        "Dataset", back_populates="project", foreign_keys="Dataset.project_id"
    )
    default_dataset = relationship("Dataset", foreign_keys=[default_dataset_id])
    requests = relationship("Request", back_populates="project")
    delivery_targets = relationship("DeliveryTarget", back_populates="project")
    trigger_repositories = relationship("TriggerRepository", back_populates="project")
    whitelisted_images = relationship("WhitelistedImage", back_populates="project")

    def __init__(self, name: str, description: str | None = None, **kwargs):
        self.name = name
        self.description = description

    def __repr__(self):
        return f'<Project {self.name}>'
