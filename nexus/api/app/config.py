"""
nexus-api settings read from the environment (pydantic-settings), grouped by concern.

Each group is read once, at import, into the module-level instances at the bottom. A field without a default is
required: a missing value fails the import. The rest of the app reads settings from here, never from os.environ.
"""
from typing import Self

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class EnvConfig(BaseSettings):
    model_config = SettingsConfigDict(env_file=None, case_sensitive=True, populate_by_name=True)


class DatabaseConfig(EnvConfig):
    """nexus-api's own Postgres database."""
    user: str = Field(alias="NEXUS_DB_USER")
    password: str = Field(alias="NEXUS_DB_PASSWORD")
    host: str = Field(alias="PGHOST")
    port: str = Field(alias="PGPORT")
    name: str = Field(alias="NEXUS_DB_NAME")
    # Appended to the connection URI as is, e.g. `?sslmode=require`
    ssl: str = Field(default="", alias="DB_SSL")


class KeycloakConfig(EnvConfig):
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
    # node role (ADR 0037): it manages Keycloak users and groups and never calls nexus-api.
    service_user: str = Field(default="fn-service", alias="KEYCLOAK_SERVICE_USER")
    # kc-secrets is mounted as a directory (see the chart's kcSecretsMountPath helper) rather than
    # injected via envFrom, so that a credential rotation reaches this process without a restart.
    secrets_path: str = Field(default="/etc/secrets/kc", alias="KC_SECRETS_PATH")
    # Fallbacks for the mounted credentials above, for local runs and docker-compose, which have no mount
    secret: str = Field(default="", alias="KEYCLOAK_SECRET")
    service_password: str = Field(default="", alias="KEYCLOAK_SERVICE_PASSWORD")
    # How long a service-account token may be reused, in seconds. 0 disables caching (see keycloak.py)
    token_cache_ttl: int = Field(default=0, alias="KEYCLOAK_TOKEN_CACHE_TTL")
    # Service-account login retries across a password rotation (see keycloak.py)
    service_login_attempts: int = Field(default=3, alias="KEYCLOAK_SERVICE_LOGIN_ATTEMPTS")
    service_login_backoff: float = Field(default=1.5, alias="KEYCLOAK_SERVICE_LOGIN_BACKOFF")

    @model_validator(mode="after")
    def default_url(self) -> Self:
        if self.url is None:
            self.url = f"http://keycloak.{self.namespace}.svc.cluster.local"
        return self


class KubernetesConfig(EnvConfig):
    # Set by Kubernetes in every pod: its presence means nexus-api runs in a cluster
    service_host: str | None = Field(default=None, alias="KUBERNETES_SERVICE_HOST")
    # Where project secrets are stored, apart from the release namespace
    secrets_namespace: str | None = Field(default=None, alias="SECRETS_NAMESPACE")
    # Where a disabled secret's value is kept, out of reach of everything that reads the secrets' own namespace
    quarantine_namespace: str = Field(default="fn-quarantine", alias="QUARANTINE_NAMESPACE")
    task_namespace: str | None = Field(default=None, alias="TASK_NAMESPACE")


class TaskComputeConfig(EnvConfig):
    """
    What a spec's compute may ask for, from the chart's taskCompute values: nothing over the max, and a request
    without a limit of its own has to fit the default limit the task namespace's LimitRange gives.
    """
    max_cpu: str = Field(alias="TASK_COMPUTE_MAX_CPU")
    max_memory: str = Field(alias="TASK_COMPUTE_MAX_MEMORY")
    default_limit_cpu: str = Field(alias="TASK_COMPUTE_DEFAULT_LIMIT_CPU")
    default_limit_memory: str = Field(alias="TASK_COMPUTE_DEFAULT_LIMIT_MEMORY")
    enable_image_whitelist: bool = Field(default=False, alias="ENABLE_IMAGE_WHITELIST")


class NodeConfig(EnvConfig):
    public_url: str | None = Field(default=None, alias="PUBLIC_URL")
    dagster_webserver_uri: str | None = Field(default=None, alias="DAGSTER_WEBSERVER_URI")


database = DatabaseConfig()
keycloak = KeycloakConfig()
kubernetes = KubernetesConfig()
task_compute = TaskComputeConfig()
node = NodeConfig()


class AccessTokenConfig(EnvConfig):
    """
    How nexus-api checks Keycloak access tokens (ADR 0036). Tokens are issued for Keycloak's address on the node's
    host (KC_HOSTNAME); the keys are fetched in-cluster. The chart sets both.
    """
    issuer: str = Field(default=f"{keycloak.url}/realms/{keycloak.realm}", alias="KEYCLOAK_ISSUER")
    jwks_url: str = Field(
        default=f"{keycloak.url}/realms/{keycloak.realm}/protocol/openid-connect/certs", alias="KEYCLOAK_JWKS_URL"
    )
    client: str = Field(default=keycloak.client, alias="KEYCLOAK_CLIENT")
