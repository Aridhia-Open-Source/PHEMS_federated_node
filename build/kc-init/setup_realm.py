# This file acts as a Keycloak settings Migration file
# Basically all the changes in the realms.json will not be
# applied on existing realms, so we need a way to apply
# those changes, hence this file

import json
import requests

from common import create_user_with_role, is_response_good, login, health_check
from settings import settings


health_check(settings.keycloak_url)

print(f"Accessing to keycloak {settings.realm} realm")

admin_token = login(settings.keycloak_url, settings.keycloak_admin_password)

print("Got the token...Creating user in new Realm")

headers = {
  'Cache-Control': 'no-cache',
  'Content-Type': 'application/json',
  'Authorization': f'Bearer {admin_token}'
}

create_user_with_role(settings.keycloak_admin, settings.keycloak_admin_password)
create_user_with_role(
    settings.first_user_email, settings.first_user_pass,
    settings.first_user_email, settings.first_user_first_name,
    settings.first_user_last_name, "Administrator"
  )

print("Setting up the token exchange for global client")
all_clients = requests.get(
  f"{settings.keycloak_url}/admin/realms/{settings.keycloak_realm}/clients",
  headers = {
    'Authorization': f'Bearer {admin_token}'
  }
)
is_response_good(all_clients)
all_clients = all_clients.json()
client_id = list(filter(lambda x: x["clientId"] == 'global', all_clients))[0]['id']
rm_client_id = list(filter(lambda x: x["clientId"] == 'realm-management', all_clients))[0]['id']

print("Enabling the Permissions on the global client")
client_permission_resp = requests.put(
  f"{settings.keycloak_url}/admin/realms/{settings.keycloak_realm}/clients/{client_id}/management/permissions",
  json={"enabled": True},
  headers = {
    'Content-Type': 'application/json',
    'Authorization': f'Bearer {admin_token}'
  }
)
if not client_permission_resp.ok:
    print(client_permission_resp.text)
    exit(1)

print("Fetching the token exchange scope")
# Fetching the token exchange scope
client_te_scope_resp = requests.get(
  f"{settings.keycloak_url}/admin/realms/{settings.keycloak_realm}/clients/{rm_client_id}/authz/resource-server/scope?permission=false&name=token-exchange",
  headers = {
    'Authorization': f'Bearer {admin_token}'
  }
)
is_response_good(client_te_scope_resp)
token_exch_scope = client_te_scope_resp.json()[0]["id"]

print("Fetching the global resource reference")
# Fetching the global resource reference in the realm-management client
resource_scope_resp = requests.get(
  f"{settings.keycloak_url}/admin/realms/{settings.keycloak_realm}/clients/{rm_client_id}/authz/resource-server/resource?name=client.resource.{client_id}",
  headers = {
    'Authorization': f'Bearer {admin_token}'
  }
)
is_response_good(resource_scope_resp)
resource_id = resource_scope_resp.json()[0]["_id"]

print("Creating the client policy")
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
    print(global_client_policy_resp.text)
    exit(1)

if isinstance(global_client_policy_resp.json(), dict):
  global_policy_id = global_client_policy_resp.json()["id"]
else:
  global_policy_id = global_client_policy_resp.json()[0]["id"]

print("Updating permissions")
# Getting auto-created permission for token-exchange
token_exch_name = f"token-exchange.permission.client.{client_id}"
token_exch_permission_resp = requests.get(
  f"{settings.keycloak_url}/admin/realms/{settings.keycloak_realm}/clients/{rm_client_id}/authz/resource-server/permission/scope?name={token_exch_name}",
  headers = {
    'Authorization': f'Bearer {admin_token}'
  }
)
if not token_exch_permission_resp.ok:
  print(token_exch_permission_resp.text)
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

# Setting the users' required field to not require firstName and lastName
user_profiles_resp = requests.get(
  f"{settings.keycloak_url}/admin/realms/{settings.keycloak_realm}/users/profile",
  headers={'Authorization': f'Bearer {admin_token}'}
)
if is_response_good(user_profiles_resp):
  print(user_profiles_resp.text)
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
  print(user_edit_profiles_resp.text)
  exit(1)

# Enable user profiles on a realm level
realm_settings = requests.get(
  f"{settings.keycloak_url}/admin/realms/{settings.keycloak_realm}",
  headers={'Authorization': f'Bearer {admin_token}'}
)
if is_response_good(realm_settings):
  print(realm_settings.text)
  exit(1)

r_settings = realm_settings.json()
r_settings["attributes"]["userProfileEnabled"] = True

update_settings = requests.put(
  f"{settings.keycloak_url}/admin/realms/{settings.keycloak_realm}",
  json=r_settings,
  headers={'Authorization': f'Bearer {admin_token}'}
)
if is_response_good(update_settings):
  print(update_settings.text)
  exit(1)

# Updating client secret
print("Updating client secret")
response_get = requests.get(f"{settings.keycloak_url}/admin/realms/{settings.keycloak_realm}/clients/{client_id}", headers=headers)
body = response_get.json()
body["secret"] = settings.keycloak_global_client_secret
response_secret = requests.put(
    f"{settings.keycloak_url}/admin/realms/{settings.keycloak_realm}/clients/{client_id}",
    headers=headers,
    data=json.dumps(body)
  )
if not response_secret.ok:
    print(response_secret.json())
    exit(1)

print("Done!")
exit(0)
