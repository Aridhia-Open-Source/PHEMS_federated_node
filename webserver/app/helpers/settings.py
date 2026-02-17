import os


class BaseSettings:
  def __init__(self):
    for attr in self.__annotations__.keys():
      if os.getenv(attr.upper()):
        if isinstance(getattr(self, attr), int):
          setattr(self, attr, int(os.getenv(attr.upper())))
        else:
          setattr(self, attr, os.getenv(attr.upper()))

class Settings(BaseSettings):
  pguser:str = ""
  pgpassword:str = ""
  pghost:str = ""
  pgport:str = ""
  pgdatabase:str = ""
  dbssl:str = ""
  controller_namespace:str = ""
  task_namespace:str = ""
  default_namespace:str = ""
  public_url:str = ""
  cleanup_after_days:int = 3
  task_pod_results_path:str = ""
  task_pod_inputs_path:str = "/mnt/inputs"
  crd_domain:str = ""
  results_path:str = ""
  task_review:str = ""
  task_controller:str = ""
  storage_class:str = ""
  github_delivery:str = ""
  other_delivery:str = ""
  alpine_image:str = ""
  claim_capacity:str = ""
  image_tag:str = ""
  azure_storage_enabled:str = ""
  azure_secret_name:str = ""
  azure_share_name:str = ""
  aws_storage_enabled:str = ""
  aws_storage_driver:str = ""
  aws_files_system_id:str = ""


class KeycloakSettings(BaseSettings):
  keycloak_namespace:str = ""
  keycloak_url:str = "http://keycloak.keycloak.svc.cluster.local"
  realm:str = "FederatedNode"
  keycloak_client:str = "global"
  keycloak_secret:str = ""
  keycloak_admin:str = ""
  keycloak_admin_password:str = ""

settings = Settings()
kc_settings = KeycloakSettings()
