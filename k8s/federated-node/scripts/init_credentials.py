import os
import json
import requests

KC_OLD_PASS = os.getenv("KEYCLOAK_ADMIN_PASSWORD")
KC_OLD_SECRET = os.getenv("KEYCLOAK_GLOBAL_CLIENT_SECRET")
KC_NEW_PASS = os.getenv("NEW_KEYCLOAK_ADMIN_PASSWORD")
KC_NEW_SECRET = os.getenv("NEW_KEYCLOAK_GLOBAL_CLIENT_SECRET")
KC_URL = "http://keycloak:8080"

def login():
    print("Logging in...")
    url = f"{KC_URL}/realms/FederatedNode/protocol/openid-connect/token"
    headers = {
    'Content-Type': 'application/x-www-form-urlencoded'
    }

    response = requests.post(url, headers=headers, data={
        'client_id': 'global',
        'grant_type': 'password',
        'username': 'admin',
        'password': KC_OLD_PASS,
        'client_secret': KC_OLD_SECRET
    })
    if not response.ok:
        print(response.json())
        exit(1)

    print("Successful")
    return response.json()["access_token"]

def get_user_id(headers):
    print("Fetching user id")
    url = f"{KC_URL}/admin/realms/FederatedNode/users?username=admin"

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
    return [cl["id"] for cl in response.json() if cl["name"].lower() == "global"][0]

def set_new_client_secret(client_id, headers):
    url = f"{KC_URL}/admin/realms/FederatedNode/clients/{client_id}"
    payload = json.dumps({
        "secret": KC_NEW_SECRET
    })

    response = requests.put(url, headers=headers, data=payload)
    if not response.ok:
        print(response.json())
        exit(1)

def set_user_new_pass(user_id, headers):
    url = f"{KC_URL}/admin/realms/FederatedNode/users/{user_id}/reset-password"

    payload = json.dumps({
        "type": "password",
        "temporary": False,
        "value": KC_NEW_PASS
    })
    response = requests.put(url, headers=headers, data=payload)
    if not response.ok:
        print(response.json())
        exit(1)


token = login()
headers = {'Authorization': f"Bearer {token}"}

user_id = get_user_id(headers)
client_id = get_client_id(headers)

headers["Content-Type"] = "application/json"
set_new_client_secret(client_id, headers)
print("Completed!")
