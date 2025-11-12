import os
import logging
import requests
import time
from requests import Response
from kubernetes import config

from settings import settings

logger = logging.getLogger('realm_common')
logger.setLevel(logging.INFO)

def init_k8s():
    if os.getenv('KUBERNETES_SERVICE_HOST'):
      # Get configuration for an in-cluster setup
      config.load_incluster_config()
    elif os.path.exists(config.KUBE_CONFIG_DEFAULT_LOCATION):
      # Get config from outside the cluster. Mostly DEV
      config.load_kube_config()
    else:
      return

def health_check():
    """
    Checks Keycloak's pod ready state, as the normal health_check
    is not enough, and 1+ replicas can reset progress.
    """
    logger.info("Checking on keycloak's pod's ready state")

    for i in range(1, settings.max_retries):
      logger.info(f"Health check {i}/{settings.max_retries}")
      try:
        hc_resp = requests.get(f"{settings.keycloak_url}/realms/master")
        if hc_resp.ok:
          logger.info("Keycloak is alive")
          break
      except requests.exceptions.ConnectionError:
        pass

      logger.info("Retrying status in 10 seconds")
      time.sleep(10)

    if i == settings.max_retries:
      logger.error("Max retries reached. Keycloak pods not ready")
      exit(1)

def is_response_good(response:Response) -> None:
  if not response.ok and response.status_code != 409:
    logger.error(f"{response.status_code} - {response.text}")
    exit(1)


def login(kc_url:str, kc_user:str, kc_pass:str) -> str:
    """
    Common login function, gets the url and the password as the user is always the same.
    Returns the access_token
    """
    logger.info("Logging in...")
    url = f"{kc_url}/realms/master/protocol/openid-connect/token"
    headers = {
      'Content-Type': 'application/x-www-form-urlencoded'
    }

    response = requests.post(url, headers=headers, data={
      'client_id': 'admin-cli',
      'grant_type': 'password',
      'username': kc_user,
      'password': kc_pass
    })
    if not response.ok:
      logger.error(response.json())
      exit(1)

    logger.info("Successful")
    return response.json()["access_token"]

def get_role(role_name:str, admin_token:str):
    logger.info(f"Getting realms role {role_name} id")
    headers = {
      'Authorization': f'Bearer {admin_token}'
    }

    response = requests.get(
      f"{settings.keycloak_url}/admin/realms/{settings.keycloak_realm}/roles",
      headers=headers
    )
    is_response_good(response)
    role_id = [role for role in response.json() if role["name"] == role_name][0]["id"]
    logger.info("Got role")
    return role_id

def create_user(
      username:str,
      password:str,
      email:str="",
      first_name:str="Admin",
      last_name:str="Admin",
      role_name:str="Super Administrator",
      with_role:bool=True,
      admin_token:str=None,
      realm:str=settings.keycloak_realm
    ):
    """
    Given a set of info about the user, create in the settings.keycloak_realm and
    assigns it the role as it can't be done all in one call.

    The default role, is Super Administrator, which is basically to ensure the backend
    has full access to it
    """
    if not admin_token:
      admin_token = login(settings.keycloak_url, settings.kc_bootstrap_admin_password, settings.kc_bootstrap_admin_password)

    headers= {
      'Authorization': f'Bearer {admin_token}'
    }
    response_create_user = requests.post(
      f"{settings.keycloak_url}/admin/realms/{realm}/users",
      headers=headers,
      json={
        "firstName": first_name,
        "lastName": last_name,
        "email": email,
        "enabled": "true",
        "emailVerified": "true",
        "username": username,
        "credentials": [
          {
            "type": "password",
            "temporary": False,
            "value": password
          }
        ]
      }
    )
    is_response_good(response_create_user)

    if with_role:
      response_user_id = requests.get(
        f"{settings.keycloak_url}/admin/realms/{realm}/users",
        params={"username": username},
        headers=headers
      )
      is_response_good(response_user_id)
      user_id = response_user_id.json()[0]["id"]

      logger.info(f"Assigning role {role_name} to {username}")

      response_assign_role = requests.post(
        f"{settings.keycloak_url}/admin/realms/{realm}/users/{user_id}/role-mappings/realm",
        headers={
          'Content-Type': 'application/json',
          'Authorization': f'Bearer {admin_token}'
        },
        json=[
          {
            "id": get_role(role_name, admin_token),
            "name": role_name
          }
        ]
      )
      is_response_good(response_assign_role)

def set_token_exchange_v2(admin_token:str):
  """
  We don't actively use this, but it could be useful
  in the future
  """
  all_clients = requests.get(
    f"{settings.keycloak_url}/admin/realms/{settings.keycloak_realm}/clients",
    headers = {
      'Authorization': f'Bearer {admin_token}'
    }
  )
  is_response_good(all_clients)
  logger.info("Enabling the Permissions on the global client")
  all_clients = all_clients.json()
  client_id = list(filter(lambda x: x["clientId"] == 'global', all_clients))[0]['id']

  global_client_resp = requests.get(
    f"{settings.keycloak_url}/admin/realms/{settings.keycloak_realm}/clients/{client_id}",
    headers = {
      'Content-Type': 'application/json',
      'Authorization': f'Bearer {admin_token}'
    }
  )
  if not global_client_resp.ok:
      logger.error(global_client_resp.text)
      exit(1)

  client_properties = global_client_resp.json()
  client_properties["attributes"]["standard.token.exchange.enabled"] = True
  global_put_client_resp = requests.put(
    f"{settings.keycloak_url}/admin/realms/{settings.keycloak_realm}/clients/{client_id}",
    json=client_properties,
    headers = {
      'Content-Type': 'application/json',
      'Authorization': f'Bearer {admin_token}'
    }
  )
  if not global_put_client_resp.ok:
      logger.error(global_put_client_resp.text)
      exit(1)

def set_token_exchange_for_global_client(admin_token:str):
  logger.info("Setting up the token exchange for global client")
  all_clients = requests.get(
    f"{settings.keycloak_url}/admin/realms/{settings.keycloak_realm}/clients",
    headers = {
      'Authorization': f'Bearer {admin_token}'
    }
  )
  is_response_good(all_clients)
  logger.info("Enabling the Permissions on the global client")
  all_clients = all_clients.json()
  client_id = list(filter(lambda x: x["clientId"] == 'global', all_clients))[0]['id']

  rm_client_id = list(filter(lambda x: x["clientId"] == 'realm-management', all_clients))[0]['id']

  logger.info("Enabling the Permissions on the global client")
  client_permission_resp = requests.put(
    f"{settings.keycloak_url}/admin/realms/{settings.keycloak_realm}/clients/{client_id}/management/permissions",
    json={"enabled": True},
    headers = {
      'Content-Type': 'application/json',
      'Authorization': f'Bearer {admin_token}'
    }
  )
  if not client_permission_resp.ok:
    logger.error(client_permission_resp.text)
    exit(1)

  logger.info("Fetching the token exchange scope")
  # Fetching the token exchange scope
  client_te_scope_resp = requests.get(
    f"{settings.keycloak_url}/admin/realms/{settings.keycloak_realm}/clients/{rm_client_id}/authz/resource-server/scope?permission=false&name=token-exchange",
    headers = {
        'Authorization': f'Bearer {admin_token}'
    }
  )
  is_response_good(client_te_scope_resp)
  token_exch_scope = client_te_scope_resp.json()[0]["id"]

  logger.info("Fetching the global resource reference")
  # Fetching the global resource reference in the realm-management client
  resource_scope_resp = requests.get(
    f"{settings.keycloak_url}/admin/realms/{settings.keycloak_realm}/clients/{rm_client_id}/authz/resource-server/resource?name=client.resource.{client_id}",
    headers = {
        'Authorization': f'Bearer {admin_token}'
    }
  )
  is_response_good(resource_scope_resp)
  resource_id = resource_scope_resp.json()[0]["_id"]

  logger.info("Creating the client policy")
  # Creating the client policy
  global_client_policy_resp = requests.post(
    f"{settings.keycloak_url}/admin/realms/{settings.keycloak_realm}/clients/{rm_client_id}/authz/resource-server/policy/client",
    json={
      "name": "token-exchange-global",
      "logic": "POSITIVE",
      "clients": [client_id]
    },
    headers = {
      'Content-Type': 'application/json',
      'Authorization': f'Bearer {admin_token}'
    }
  )
  if global_client_policy_resp.status_code == 409:
    global_client_policy_resp = requests.get(
      f"{settings.keycloak_url}/admin/realms/{settings.keycloak_realm}/clients/{rm_client_id}/authz/resource-server/policy/client?name=token-exchange-global",
      headers = {
        'Authorization': f'Bearer {admin_token}'
      }
    )
  elif not global_client_policy_resp.ok:
    logger.error(global_client_policy_resp.text)
    exit(1)

  if isinstance(global_client_policy_resp.json(), dict):
    global_policy_id = global_client_policy_resp.json()["id"]
  else:
    global_policy_id = global_client_policy_resp.json()[0]["id"]

  logger.info("Updating permissions")
    # Getting auto-created permission for token-exchange
  token_exch_name = f"token-exchange.permission.client.{client_id}"
  token_exch_permission_resp = requests.get(
    f"{settings.keycloak_url}/admin/realms/{settings.keycloak_realm}/clients/{rm_client_id}/authz/resource-server/permission/scope?name={token_exch_name}",
    headers = {
        'Authorization': f'Bearer {admin_token}'
    }
  )
  if not token_exch_permission_resp.ok:
    logger.error(token_exch_permission_resp.text)
    exit(1)

  token_exch_permission_id = token_exch_permission_resp.json()[0]["id"]

  # Updating the permission
  client_permission_resp = requests.put(
    f"{settings.keycloak_url}/admin/realms/{settings.keycloak_realm}/clients/{rm_client_id}/authz/resource-server/permission/scope/{token_exch_permission_id}",
    json={
        "name": token_exch_name,
        "logic": "POSITIVE",
        "decisionStrategy": "UNANIMOUS",
        "resources": [resource_id],
        "policies": [global_policy_id],
        "scopes": [token_exch_scope]
    },
    headers = {
      'Content-Type': 'application/json',
      'Authorization': f'Bearer {admin_token}'
    }
  )
  is_response_good(client_permission_resp)

def set_users_required_fields(admin_token:str):
  # Setting the users' required field to not require firstName and lastName
  user_profiles_resp = requests.get(
    f"{settings.keycloak_url}/admin/realms/{settings.keycloak_realm}/users/profile",
    headers={'Authorization': f'Bearer {admin_token}'}
  )
  if is_response_good(user_profiles_resp):
    logger.error(user_profiles_resp.text)
    exit(1)

  edit_upd = user_profiles_resp.json()
  for attribute in edit_upd["attributes"]:
    if attribute["name"] in ["firstName", "lastName"]:
      attribute.pop("required", None)

  user_edit_profiles_resp = requests.put(
    f"{settings.keycloak_url}/admin/realms/{settings.keycloak_realm}/users/profile",
    json=edit_upd,
    headers={
      'Content-Type': 'application/json',
      'Authorization': f'Bearer {admin_token}'
    }
  )
  if is_response_good(user_edit_profiles_resp):
    logger.error(user_edit_profiles_resp.text)
    exit(1)

def enable_user_profile_at_realm_level(admin_token:str):
  # Enable user profiles on a realm level
  realm_settings = requests.get(
    f"{settings.keycloak_url}/admin/realms/{settings.keycloak_realm}",
    headers={'Authorization': f'Bearer {admin_token}'}
  )
  if is_response_good(realm_settings):
    logger.error(realm_settings.text)
    exit(1)

  r_settings = realm_settings.json()
  r_settings["attributes"]["userProfileEnabled"] = True

  update_settings = requests.put(
    f"{settings.keycloak_url}/admin/realms/{settings.keycloak_realm}",
    json=r_settings,
    headers={'Authorization': f'Bearer {admin_token}'}
  )
  if is_response_good(update_settings):
    logger.error(update_settings.text)
    exit(1)

def delete_bootstrap_user(admin_token:str):
  # Delete temp admin user
  logger.info("Deleting temp user")
  user_id_resp = requests.get(
    f"{settings.keycloak_url}/admin/realms/master/users/",
    headers={'Authorization': f'Bearer {admin_token}'}
  )
  if is_response_good(user_id_resp):
    logger.error(user_id_resp.text)
    exit(1)

  user_id = list(filter(lambda x: x["username"] == settings.kc_bootstrap_admin_username, user_id_resp.json()))[0]['id']
  user_delete_resp = requests.delete(
    f"{settings.keycloak_url}/admin/realms/master/users/{user_id}",
    headers={'Authorization': f'Bearer {admin_token}'}
  )
  if is_response_good(user_delete_resp):
    logger.error(user_delete_resp.text)
    exit(1)
