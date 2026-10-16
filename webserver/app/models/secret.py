import sqlalchemy as sa
from sqlalchemy.orm import relationship, validates

from app.helpers.base_model import BaseModel, db
from app.helpers.exceptions import InvalidRequest
from app.helpers.kubernetes_names import validate_dns_subdomain
from app.models import sqla_column
from app.models.secret_provider_type import SecretProviderType

KEY_PREFIX = "fn-secret-"


class Secret(db.Model, BaseModel):
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
    label = sa.Column(sa.String(253), nullable=False, unique=True)
    description = sa.Column(sa.String(4096), nullable=True)
    provider = sa.Column(sa.Enum(SecretProviderType), nullable=False)
    # What the secret is called in the store.
    key = sa.Column(sa.String(253), unique=True, nullable=False)
    # Where the store keeps it, for stores that have such a notion. Set by the backend.
    namespace = sa.Column(sa.String(253), nullable=True)
    # Turned on or off for the whole node, whatever the projects' links say
    enabled = sa.Column(sa.Boolean, nullable=False, default=True, server_default=sa.true())

    created_at = sqla_column.created_at()
    updated_at = sqla_column.updated_at()

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
