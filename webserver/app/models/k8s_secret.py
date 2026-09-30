import re

import sqlalchemy as sa
from sqlalchemy.orm import relationship, validates

from app.helpers.base_model import BaseModel, db
from app.helpers.exceptions import InvalidRequest
from app.models import sqla_column


class K8sSecret(db.Model, BaseModel):
    """
    A reference to a Kubernetes secret. The value only ever lives in the cluster; this row
    records which secrets exist, so one that repositories share cannot be dropped from
    under them. Kubernetes cannot rename a secret, so the name is the immutable key
    the repositories point at.
    """
    __tablename__ = 'k8s_secrets'

    id = sa.Column(sa.Integer, primary_key=True, autoincrement=True)
    name = sa.Column(sa.String(253), unique=True, nullable=False)

    created_at = sqla_column.created_at()
    updated_at = sqla_column.updated_at()

    trigger_repositories = relationship("TriggerRepository", back_populates="k8s_secret")
    datasets = relationship("Dataset", back_populates="k8s_secret")

    @classmethod
    def check_exists(cls, name: str):
        """For the models that reference a secret by name, so a missing one is a 400."""
        if not cls.query.filter(cls.name == name).one_or_none():
            raise InvalidRequest(f"K8s secret {name} does not exist")

    @validates('name')
    def validate_name(self, key, value):
        """A Kubernetes secret name: a DNS subdomain, so it can be created as-is."""
        if not value or len(value) > 253 or not re.fullmatch(r'[a-z0-9]([-a-z0-9.]*[a-z0-9])?', value):
            raise ValueError(
                "name must be lowercase alphanumerics, '-' or '.', starting and "
                "ending with an alphanumeric, and at most 253 characters"
            )
        return value

    def __init__(self, name: str):
        self.name = name

    def __repr__(self):
        return f'<K8sSecret ({self.name})>'
