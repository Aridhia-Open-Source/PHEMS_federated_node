import re

import sqlalchemy as sa
from sqlalchemy.orm import relationship, validates

from app.helpers.base_model import BaseModel, db
from app.helpers.exceptions import InvalidRequest
from app.models import sqla_column
from app.models.secret_type import SecretType


class Secret(db.Model, BaseModel):
    """
    A reference to a secret. The value only ever lives in the secret store that secret_type
    names; this row records which secrets exist, so one that repositories share cannot be
    dropped from under them. A secret belongs to a project, and only that project's datasets and
    repositories can point at it. Kubernetes cannot rename a secret, so the name is
    immutable. The name is local to the project; the store one is store_name.
    """
    __tablename__ = 'secrets'

    id = sa.Column(sa.Integer, primary_key=True, autoincrement=True)
    project_id = sa.Column(
        sa.Integer, sa.ForeignKey('projects.id', ondelete='RESTRICT'), nullable=False
    )
    name = sa.Column(sa.String(253), nullable=False)
    secret_type = sa.Column(sa.Enum(SecretType), nullable=False)
    # What the secret is called in the store, which has no notion of projects.
    store_name = sa.Column(sa.String(253), unique=True, nullable=False)

    __table_args__ = (
        sa.UniqueConstraint('project_id', 'name'),
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
    def get_in_project(cls, project_id: int, name: str) -> "Secret":
        """For the requests that reference a secret by name, so a missing one is a 400."""
        secret = cls.query.filter(cls.project_id == project_id, cls.name == name).one_or_none()
        if not secret:
            raise InvalidRequest(f"Secret {name} does not exist")
        return secret

    @validates('name')
    def validate_name(self, key, value):
        """A store secret name (a Kubernetes one today): a DNS subdomain, so it can be created as-is."""
        if not value or len(value) > 253 - len(self._store_prefix(self.project_id)) or not re.fullmatch(r'[a-z0-9]([-a-z0-9.]*[a-z0-9])?', value):
            raise ValueError(
                "name must be lowercase alphanumerics, '-' or '.', starting and "
                "ending with an alphanumeric, and short enough to fit the project prefix "
                "in 253 characters"
            )
        return value

    @staticmethod
    def _store_prefix(project_id: int) -> str:
        return f"{project_id}-"

    def __init__(self, project_id: int, name: str, secret_type: SecretType):
        self.project_id = project_id
        self.name = name
        self.secret_type = secret_type
        self.store_name = f"{self._store_prefix(project_id)}{name}"

    def __repr__(self):
        return f'<Secret ({self.store_name})>'
