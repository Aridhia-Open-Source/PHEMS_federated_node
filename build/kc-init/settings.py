import os


class Settings:
  keycloak_namespace:str
  keycloak_client:str
  keycloak_admin:str
  keycloak_admin_password:str
  keycloak_global_client_secret:str
  keycloak_url:str
  first_user_pass:str
  first_user_email:str
  first_user_first_name:str = ""
  first_user_last_name:str = ""
  keycloak_realm:str = "FederatedNode"
  realm:str = "master"
  kc_namespace:str = "keycloak"
  max_retries:int = 20
  max_replicas:int = 2

  def __init__(self):
    for attr in self.__annotations__.keys():
      if os.getenv(attr.upper()):
        if isinstance(attr, int):
          setattr(self, attr, int(os.getenv(attr.upper())))
        else:
          setattr(self, attr, os.getenv(attr.upper()))


settings = Settings()
