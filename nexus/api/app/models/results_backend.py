"""Results backend model for storage configuration (git, S3, Azure, GCP)."""
from enum import Enum

import sqlalchemy as sa
from sqlalchemy.orm import relationship, validates

from app.helpers.base_model import BaseModel, db
from app.helpers.exceptions import InvalidDBEntry
from app.models import sqla_column


class BackendType(str, Enum):
    GIT = "git"
    S3 = "s3"
    AZURE = "azure"
    GCP = "gcp"

    def __str__(self):
        return self.value


class ResultsBackend(db.Model, BaseModel):
    __tablename__ = 'results_backends'

    id = sa.Column(sa.Integer, primary_key=True, autoincrement=True)
    project_id = sa.Column(sa.Integer, sa.ForeignKey('projects.id', ondelete='CASCADE'), unique=True, nullable=False)
    type = sa.Column(sa.String(16), nullable=False, server_default=BackendType.GIT.value)
    config = sa.Column(sa.JSON, nullable=False, default=dict, server_default='{}')
    created_at = sqla_column.created_at()
    updated_at = sqla_column.updated_at()

    project = relationship('Project', back_populates='results_backend')

    def __init__(self, project_id: int, type: str = BackendType.GIT.value, config: dict | None = None):
        self.project_id = project_id
        self.type = BackendType(type).value
        self.config = config or {}

    @validates('config')
    def validate_config(self, key, config):
        """Backend-specific required-field check, run at save time (per-type, not a deep schema validator)."""
        if self.type == BackendType.GIT.value:
            return config or {}
        if not config or 'url' not in config:
            raise InvalidDBEntry(f"{self.type} config must include 'url'")
        if self.type == BackendType.S3.value:
            required = ['access_key_id', 'secret_access_key']
        elif self.type == BackendType.AZURE.value:
            if 'account_key' not in config and 'connection_string' not in config:
                raise InvalidDBEntry("azure config must include 'account_key' or 'connection_string'")
            required = []
        elif self.type == BackendType.GCP.value:
            required = ['projectname']
        else:
            raise InvalidDBEntry(f"unknown backend type: {self.type}")
        missing = [f for f in required if f not in config]
        if missing:
            raise InvalidDBEntry(f"{self.type} config missing required fields: {missing}")
        return config

    def __repr__(self):
        return f'<ResultsBackend ({self.type}, project_id={self.project_id})>'
