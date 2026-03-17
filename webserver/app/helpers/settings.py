from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
  model_config = SettingsConfigDict(
    env_ignore_empty=True,
    case_sensitive=False
  )

  pguser:str
  pgpassword:str
  pghost:str
  pgport:str
  pgdatabase:str
  dbssl:Optional[str] = ""
  controller_namespace:str
  task_namespace:str
  default_namespace:str
  public_url:str
  cleanup_after_days:int = 3
  task_pod_results_path:str
  task_pod_inputs_path:str = "/mnt/inputs"
  crd_domain:Optional[str] = None
  results_path:str
  task_review:Optional[str] = None
  task_controller:Optional[str] = None
  storage_class:str
  github_delivery:Optional[str] = None
  other_delivery:Optional[str] = None
  alpine_image:str
  claim_capacity:str
  image_tag:str
  auto_delivery_results:Optional[str] = None
  azure_storage_enabled:Optional[str] = None
  azure_secret_name:Optional[str] = None
  azure_share_name:Optional[str] = None
  aws_storage_enabled:Optional[str] = None
  aws_storage_driver:Optional[str] = None
  aws_files_system_id:Optional[str] = None


class KeycloakSettings(BaseSettings):
  model_config = SettingsConfigDict(env_ignore_empty=True)

  keycloak_namespace:str
  keycloak_url:str = "http://keycloak.keycloak.svc.cluster.local"
  realm:str = "FederatedNode"
  keycloak_client:str = "global"
  keycloak_secret:str
  keycloak_admin:str
  keycloak_admin_password:str

settings = Settings()
kc_settings = KeycloakSettings()
