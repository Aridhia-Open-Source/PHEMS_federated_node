import re

import sqlalchemy as sa
from sqlalchemy.orm import relationship, validates

from app.helpers.base_model import BaseModel, db
from app.helpers.exceptions import InvalidRequest
from app.models import sqla_column
from app.models.secret_provider_type import SecretProviderType


class Secret(db.Model, BaseModel):
    """
    A reference to a secret. The value only ever lives in the secret store that provider
    names; this row records which secrets exist, so one that repositories share cannot be
    dropped from under them. A secret belongs to a project, and only that project's datasets and
    repositories can point at it. The label is local to the project; the key is what the
    secret is called in the store. It is generated at creation and never changes, so a
    label can be renamed without touching the stored secret.
    """
    __tablename__ = 'secrets'

    id = sa.Column(sa.Integer, primary_key=True, autoincrement=True)
    project_id = sa.Column(
        sa.Integer, sa.ForeignKey('projects.id', ondelete='RESTRICT'), nullable=False
    )
    label = sa.Column(sa.String(253), nullable=False)
    description = sa.Column(sa.String(4096), nullable=True)
    provider = sa.Column(sa.Enum(SecretProviderType), nullable=False)
    # What the secret is called in the store, which has no notion of projects.
    key = sa.Column(sa.String(253), unique=True, nullable=False)

    __table_args__ = (
        sa.UniqueConstraint('project_id', 'label'),
        # The target of the composite foreign keys that tie a dataset or repository to a
        # secret of its own project.
        sa.UniqueConstraint('project_id', 'id'),
    )

    created_at = sqla_column.created_at()
    updated_at = sqla_column.updated_at()

    trigger_repositories = relationship(
        "TriggerRepository", back_populates="secret", overlaps="trigger_repositories,project"
    )
    results_repositories = relationship(
        "ResultsRepository", back_populates="secret", overlaps="results_repositories,project"
    )
    datasets = relationship("Dataset", back_populates="secret", overlaps="datasets,project")

    @classmethod
    def get_in_project(cls, project_id: int, label: str) -> "Secret":
        """For the requests that reference a secret by label, so a missing one is a 400."""
        secret = cls.query.filter(cls.project_id == project_id, cls.label == label).one_or_none()
        if not secret:
            raise InvalidRequest(f"Secret {label} does not exist")
        return secret

    @validates('label')
    def validate_label(self, key, value):
        """The label is part of the key, which is a store secret name (a Kubernetes one today): a DNS subdomain, so it can be created as-is."""
        if not value or len(value) > 253 - len(self._store_prefix(self.project_id)) or not re.fullmatch(r'[a-z0-9]([-a-z0-9.]*[a-z0-9])?', value):
            raise ValueError(
                "label must be lowercase alphanumerics, '-' or '.', starting and "
                "ending with an alphanumeric, and short enough to fit the project prefix "
                "in 253 characters"
            )
        return value

    @staticmethod
    def _store_prefix(project_id: int) -> str:
        return f"{project_id}-"

    def __init__(
        self, project_id: int, label: str, provider: SecretProviderType,
        description: str | None = None
    ):
        self.project_id = project_id
        self.label = label
        self.description = description
        self.provider = provider
        self.key = f"{self._store_prefix(project_id)}{label}"

    def __repr__(self):
        return f'<Secret ({self.key})>'
