import os
import json
import requests

from common import health_check, login


KC_OLD_PASS = os.getenv("KEYCLOAK_ADMIN_PASSWORD")
KC_OLD_SECRET = os.getenv("KEYCLOAK_GLOBAL_CLIENT_SECRET")
KC_NEW_PASS = os.getenv("NEW_KEYCLOAK_ADMIN_PASSWORD")
KC_NEW_SECRET = os.getenv("NEW_KEYCLOAK_GLOBAL_CLIENT_SECRET")
KEYCLOAK_NAMESPACE = os.getenv("KEYCLOAK_NAMESPACE")
KC_URL = os.getenv("KEYCLOAK_URL", f"http://keycloak.{KEYCLOAK_NAMESPACE}.svc.cluster.local")


def get_user_id(headers, realm='master'):
    print("Fetching user id")
    url = f"{KC_URL}/admin/realms/{realm}/users?username=admin"

    response = requests.get(url, headers=headers)
    if not response.ok:
        print(response.json())
        exit(1)
    print("Successful")
    return response.json()[0]["id"]

def get_client_id(headers):
    url = f"{KC_URL}/admin/realms/FederatedNode/clients"
    response = requests.get(url, headers=headers)
    if not response.ok:
        print(response.json())
        exit(1)
    return [cl["id"] for cl in response.json() if cl.get("name", '').lower() == "global"][0]

def set_new_client_secret(client_id, headers):
    url = f"{KC_URL}/admin/realms/FederatedNode/clients/{client_id}"

    response_get = requests.get(url, headers=headers)
    body = response_get.json()
    body["secret"] = KC_NEW_SECRET
    response = requests.put(url, headers=headers, data=json.dumps(body))
    if not response.ok:
        print(response.json())
        exit(1)

def set_user_new_pass(user_id, headers, realm='master'):
    print(f"Updating on {realm} realm")
    url = f"{KC_URL}/admin/realms/{realm}/users/{user_id}/reset-password"

    payload = json.dumps({
        "type": "password",
        "temporary": False,
        "value": KC_NEW_PASS
    })
    response = requests.put(url, headers=headers, data=payload)
    if not response.ok:
        print(response.json())
        exit(1)

health_check(KC_URL)

token = login(KC_URL, KC_OLD_PASS)
headers = {'Authorization': f"Bearer {token}"}

user_id_master = get_user_id(headers)
user_id_fn = get_user_id(headers, 'FederatedNode')
client_id = get_client_id(headers)
set_user_new_pass(user_id_master, headers)
set_user_new_pass(user_id_fn, headers, 'FederatedNode')

headers["Content-Type"] = "application/json"
set_new_client_secret(client_id, headers)
print("Completed!")
