from http import HTTPStatus

import sqlalchemy as sa
from sqlalchemy.orm import relationship, validates

from app.helpers.base_model import BaseModel, db
from app.helpers.exceptions import InvalidRequest
from app.helpers.kubernetes_names import validate_dns_subdomain
from app.helpers.soft_delete import SoftDeleteMixin
from app.models import sqla_column
from app.models.secret_provider_type import SecretProviderType

KEY_PREFIX = "fn-secret-"


class Secret(SoftDeleteMixin, db.Model, BaseModel):
    """
    A reference to a secret. The value only ever lives in the secret store that provider
    names; this row records which secrets exist, so one that repositories share cannot be
    dropped from under them. A secret belongs to no project: any dataset or repository can
    point at it. The label is unique across the node; the key is what the secret is called
    in the store. It is generated at creation and never changes, so a label can be renamed
    without touching the stored secret.
    """
    __tablename__ = 'secrets'

    id = sa.Column(sa.Integer, primary_key=True, autoincrement=True)
    label = sa.Column(sa.String(253), nullable=False)
    description = sa.Column(sa.String(4096), nullable=True)
    provider = sa.Column(sa.Enum(SecretProviderType), nullable=False)
    # What the secret is called in the store.
    key = sa.Column(sa.String(253), nullable=False)
    # Where the store keeps it, for stores that have such a notion. Set by the backend.
    namespace = sa.Column(sa.String(253), nullable=True)
    # Turned on or off for the whole node, whatever the projects' links say
    enabled = sa.Column(sa.Boolean, nullable=False, default=True, server_default=sa.true())

    created_at = sqla_column.created_at()
    updated_at = sqla_column.updated_at()

    __table_args__ = (
        sa.Index('uq_secrets_label', 'label', unique=True, postgresql_where=sa.text('deleted_at IS NULL')),
        sa.Index('uq_secrets_key', 'key', unique=True, postgresql_where=sa.text('deleted_at IS NULL')),
    )

    trigger_repositories = relationship(
        "TriggerRepository", back_populates="secret"
    )
    results_repositories = relationship(
        "ResultsRepository", back_populates="secret"
    )
    datasets = relationship("Dataset", back_populates="secret")
    project_assignments = relationship("ProjectSecret", back_populates="secret")

    @classmethod
    def get_by_label(cls, label: str) -> "Secret":
        """For the requests that reference a secret by label, so a missing one is a 400."""
        secret = cls.query.filter(cls.label == label).one_or_none()
        if not secret:
            raise InvalidRequest(f"Secret {label} does not exist")
        return secret

    @classmethod
    def get_enabled_by_label(cls, label: str, current_id: int | None = None) -> "Secret":
        """
        For create and patch: like get_by_label, but a disabled secret is a 400. Naming the
        secret the resource already uses (current_id) is not a change, so it is let through.
        """
        secret = cls.get_by_label(label)
        if not secret.enabled and secret.id != current_id:
            raise InvalidRequest(f"Secret {label} is disabled")
        return secret

    def require_usable(self) -> None:
        """
        For enabling a dataset or repository that uses this secret: a 409 while the secret is
        disabled or deleted, repoint it first. Not a 400 like naming a disabled secret, since
        the request is fine and it is the state of the node that refuses it.
        """
        if self.deleted_at is not None:
            raise InvalidRequest(f"Secret {self.label} is deleted", code=HTTPStatus.CONFLICT)
        if not self.enabled:
            raise InvalidRequest(f"Secret {self.label} is disabled", code=HTTPStatus.CONFLICT)

    @validates('label')
    def validate_label(self, key, value):
        """The key, "fn-secret-<label>", is a store secret name (a Kubernetes one today): a DNS subdomain, so it can be created as-is."""
        if not isinstance(value, str):
            raise InvalidRequest("label must be a string")
        validate_dns_subdomain(f"{KEY_PREFIX}{value}", "label")
        return value

    def __init__(
        self, label: str, provider: SecretProviderType,
        description: str | None = None, namespace: str | None = None,
        enabled: bool = True
    ):
        self.label = label
        self.description = description
        self.provider = provider
        self.namespace = namespace
        self.enabled = enabled
        self.key = f"{KEY_PREFIX}{label}"

    def __repr__(self):
        return f'<Secret ({self.key})>'
