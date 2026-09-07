import os

from secrets_reader import read_secret


class Settings:
  """
  Configuration for keycloak-realm-init.

  Ordinary configuration is read from the environment once, at import. Credentials are NOT: they are
  exposed as properties that read the mounted kc-secrets file on every access, because this is a
  long-running controller and a credential rotation must reach it without a restart. Caching them at
  import would defeat the entire point of volume-mounting the secret.
  """
  keycloak_namespace:str = ""
  keycloak_client:str = ""
  # `admin` is the operator's Keycloak console account. The platform creates it with a temporary
  # password and never touches it again, so its password may be changed freely by an operator.
  keycloak_admin:str = ""
  # fn-service is the account the platform authenticates as for every programmatic call. It holds
  # Super Administrator in the FederatedNode realm and never needs master-realm access.
  keycloak_service_user:str = "fn-service"
  kc_bootstrap_admin_username:str = ""
  keycloak_url:str = ""
  first_user_pass:str = ""
  first_user_email:str = ""
  first_user_first_name:str = ""
  first_user_last_name:str = ""
  dagster_kc_user:str = ""
  dagster_kc_email:str = ""
  manage_realm:bool = True
  keycloak_realm:str = "FederatedNode"
  realm:str = "master"
  kc_namespace:str = "keycloak"
  max_retries:int = 20
  kc_replicas:int = 2

  def __init__(self):
    for attr in self.__annotations__.keys():
      raw = os.getenv(attr.upper())
      if not raw:
        continue
      current = getattr(self, attr)
      if isinstance(current, bool):
        setattr(self, attr, raw.strip().lower() in ("1", "true", "yes", "on"))
      elif isinstance(current, int):
        setattr(self, attr, int(raw))
      else:
        setattr(self, attr, raw)

  # Credentials, re-read on every access so a rotation is observed without a restart. Deliberately
  # NOT declared as annotations above, or the loader would try to assign over these properties.
  @property
  def keycloak_admin_password(self) -> str:
    return read_secret("KEYCLOAK_ADMIN_PASSWORD")

  @property
  def keycloak_service_password(self) -> str:
    return read_secret("KEYCLOAK_SERVICE_PASSWORD")

  @property
  def keycloak_secret(self) -> str:
    """The `global` client secret."""
    return read_secret("KEYCLOAK_SECRET")

  @property
  def kc_bootstrap_admin_password(self) -> str:
    return read_secret("KC_BOOTSTRAP_ADMIN_PASSWORD")

  @property
  def dagster_kc_password(self) -> str:
    return read_secret("DAGSTER_KC_PASSWORD")


settings = Settings()
