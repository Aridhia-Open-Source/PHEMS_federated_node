"""
nexus-api settings read from the environment (pydantic-settings), grouped by concern.

One `settings` object, read once at import, holds a group per concern: `settings.keycloak.realm`,
`settings.database.host`, `settings.kubernetes.namespaces.tasks`. A field without a default is required: a missing
value fails the import. The rest of the app reads settings from here, never from os.environ.
"""
from dataclasses import dataclass, field
from typing import Self

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class EnvSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=None, case_sensitive=True, populate_by_name=True)


class DatabaseSettings(EnvSettings):
    """nexus-api's own Postgres database."""
    user: str = Field(alias="NEXUS_DB_USER")
    password: str = Field(alias="NEXUS_DB_PASSWORD")
    host: str = Field(alias="PGHOST")
    port: str = Field(alias="PGPORT")
    name: str = Field(alias="NEXUS_DB_NAME")
    # Appended to the connection URI as is, e.g. `?sslmode=require`
    ssl: str = Field(default="", alias="DB_SSL")


class KeycloakSettings(EnvSettings):
    namespace: str | None = Field(default=None, alias="KEYCLOAK_NAMESPACE")
    # Defaults to the in-cluster service in `namespace`
    url: str | None = Field(default=None, alias="KEYCLOAK_URL")
    realm: str = Field(default="FederatedNode", alias="KEYCLOAK_REALM")
    client: str = Field(default="global", alias="KEYCLOAK_CLIENT")
    # `admin` is the operator's Keycloak console account. It is kept here only so the user list can
    # filter it out -- nothing authenticates as it. Its password is operator-owned and may change at
    # any time, so relying on it would make the backend break whenever an operator rotated it.
    admin: str | None = Field(default=None, alias="KEYCLOAK_ADMIN")
    # The platform's service account. Holds realm-management's realm-admin in the node's realm and no
    # node role (ADR 0036): it manages Keycloak users and groups and never calls nexus-api.
    service_user: str = Field(default="fn-service", alias="KEYCLOAK_SERVICE_USER")
    # kc-secrets is mounted as a directory (see the chart's kcSecretsMountPath helper) rather than
    # injected via envFrom, so that a credential rotation reaches this process without a restart.
    secrets_path: str = Field(default="/etc/secrets/kc", alias="KC_SECRETS_PATH")
    # Fallbacks for the mounted credentials above, for local runs and docker-compose, which have no mount
    secret: str = Field(default="", alias="KEYCLOAK_SECRET")
    service_password: str = Field(default="", alias="KEYCLOAK_SERVICE_PASSWORD")
    # How long a service-account token may be reused, in seconds. 0 disables caching.
    # Without this, every Keycloak() instantiation performs a fresh password grant, and a single request
    # builds several Keycloak objects -- so a brief authentication outage during a credential rotation
    # turns into a total outage rather than a few failed calls. Defaults to off so the existing test
    # suite, which mocks the token endpoint per test, is unaffected; the chart enables it in production.
    token_cache_ttl: int = Field(default=0, alias="KEYCLOAK_TOKEN_CACHE_TTL")
    # How many times to retry a service-account login before giving up, and how long to wait between
    # attempts. Passwords have no dual-credential grace period in Keycloak (unlike client secrets), so
    # during a rotation there is a brief cutover where the credential on disk and the one Keycloak holds
    # disagree. Re-reading and retrying rides over the instant of changeover.
    service_login_attempts: int = Field(default=3, alias="KEYCLOAK_SERVICE_LOGIN_ATTEMPTS")
    service_login_backoff: float = Field(default=1.5, alias="KEYCLOAK_SERVICE_LOGIN_BACKOFF")

    @model_validator(mode="after")
    def default_url(self) -> Self:
        if self.url is None:
            self.url = f"http://keycloak.{self.namespace}.svc.cluster.local"
        return self


class NamespacesSettings(EnvSettings):
    """The namespaces nexus-api puts things in."""
    # Where project secrets are stored, apart from the release namespace
    secrets: str | None = Field(default=None, alias="SECRETS_NAMESPACE")
    # Where a disabled secret's value is kept, out of reach of everything that reads the secrets' own namespace
    quarantine: str = Field(default="fn-quarantine", alias="QUARANTINE_NAMESPACE")
    # Where tasks run
    tasks: str | None = Field(default=None, alias="TASK_NAMESPACE")


class TaskLimitsSettings(EnvSettings):
    """
    What a task spec's compute may ask for, from the chart's taskCompute values: nothing over the max, and a request
    without a limit of its own has to fit the default limit the task namespace's LimitRange gives.
    """
    max_cpu: str = Field(alias="TASK_COMPUTE_MAX_CPU")
    max_memory: str = Field(alias="TASK_COMPUTE_MAX_MEMORY")
    default_limit_cpu: str = Field(alias="TASK_COMPUTE_DEFAULT_LIMIT_CPU")
    default_limit_memory: str = Field(alias="TASK_COMPUTE_DEFAULT_LIMIT_MEMORY")


class KubernetesSettings(EnvSettings):
    # Set by Kubernetes in every pod: its presence means nexus-api runs in a cluster
    service_host: str | None = Field(default=None, alias="KUBERNETES_SERVICE_HOST")
    namespaces: NamespacesSettings = Field(default_factory=NamespacesSettings)
    task_limits: TaskLimitsSettings = Field(default_factory=TaskLimitsSettings)


class NodeSettings(EnvSettings):
    public_url: str | None = Field(default=None, alias="PUBLIC_URL")
    dagster_webserver_uri: str | None = Field(default=None, alias="DAGSTER_WEBSERVER_URI")


class AccessTokenSettings(EnvSettings):
    """
    How nexus-api checks Keycloak access tokens (ADR 0035). Tokens are issued for Keycloak's address on the node's
    host (KC_HOSTNAME); the keys are fetched in-cluster. The chart sets both. A value left unset defaults from the
    Keycloak group (see Settings).
    """
    issuer: str | None = Field(default=None, alias="KEYCLOAK_ISSUER")
    jwks_url: str | None = Field(default=None, alias="KEYCLOAK_JWKS_URL")
    client: str | None = Field(default=None, alias="KEYCLOAK_CLIENT")


@dataclass
class Settings:
    """Every group, read once at import. Access tokens default from the Keycloak group."""

    database: DatabaseSettings = field(default_factory=DatabaseSettings)
    keycloak: KeycloakSettings = field(default_factory=KeycloakSettings)
    kubernetes: KubernetesSettings = field(default_factory=KubernetesSettings)
    node: NodeSettings = field(default_factory=NodeSettings)
    access_token: AccessTokenSettings = field(default_factory=AccessTokenSettings)

    def __post_init__(self):
        realm_url = f"{self.keycloak.url}/realms/{self.keycloak.realm}"
        token = self.access_token
        if token.issuer is None:
            token.issuer = realm_url
        if token.jwks_url is None:
            token.jwks_url = f"{realm_url}/protocol/openid-connect/certs"
        if token.client is None:
            token.client = self.keycloak.client


settings = Settings()
