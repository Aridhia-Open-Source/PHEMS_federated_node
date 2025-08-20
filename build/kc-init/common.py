import requests
from requests import Response
import time

from settings import settings

MAX_RETRIES = 20


def health_check():
    """
    Simple kecyloak health check
    """
    print("Health check on keycloak pod before starting")
    for i in range(1, MAX_RETRIES):
        print(f"Health check {i}/{MAX_RETRIES}")
        try:
            hc_resp = requests.get(f"{settings.keycloak_url}/realms/master")
            if hc_resp.ok:
                print("Keycloak is alive")
                break
        except requests.exceptions.ConnectionError:
            pass
        print("Health check failed...retrying in 10 seconds")
        time.sleep(10)

    if i == MAX_RETRIES:
        print("Keycloak cannot be reached")
        exit(1)

def is_response_good(response:Response) -> None:
  if not response.ok and response.status_code != 409:
    print(f"{response.status_code} - {response.text}")
    exit(1)


def login(kc_url:str, kc_pass:str) -> str:
    """
    Common login function, gets the url and the password as the user is always the same.
    Returns the access_token
    """
    print("Logging in...")
    url = f"{kc_url}/realms/master/protocol/openid-connect/token"
    headers = {
        'Content-Type': 'application/x-www-form-urlencoded'
    }

    response = requests.post(url, headers=headers, data={
        'client_id': 'admin-cli',
        'grant_type': 'password',
        'username': 'admin',
        'password': kc_pass
    })
    if not response.ok:
        print(response.json())
        exit(1)

    print("Successful")
    return response.json()["access_token"]

def get_role(role_name:str, admin_token:str):
    print(f"Getting realms role {role_name} id")
    headers = {
        'Authorization': f'Bearer {admin_token}'
    }

    response = requests.get(
        f"{settings.keycloak_url}/admin/realms/{settings.keycloak_realm}/roles",
        headers=headers
    )
    is_response_good(response)
    role_id = [role for role in response.json() if role["name"] == role_name][0]["id"]
    print("Got role")
    return role_id

def create_user_with_role(
        username:str,
        password:str,
        email:str="",
        first_name:str="Admin",
        last_name:str="Admin",
        role_name:str="Super Administrator"
    ):
    """
    Given a set of info about the user, create in the settings.keycloak_realm and
    assigns it the role as it can't be done all in one call.

    The default role, is Super Administrator, which is basically to ensure the backend
    has full access to it
    """
    admin_token = login(settings.keycloak_url, settings.keycloak_admin_password)
    headers= {
            'Authorization': f'Bearer {admin_token}'
        }
    response_create_user = requests.post(
        f"{settings.keycloak_url}/admin/realms/{settings.keycloak_realm}/users",
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

    response_user_id = requests.get(
        f"{settings.keycloak_url}/admin/realms/{settings.keycloak_realm}/users?username={email}",
        headers=headers
    )
    is_response_good(response_user_id)
    user_id = response_user_id.json()[0]["id"]

    print(f"Assigning role {role_name} to {username}")

    response_assign_role = requests.post(
        f"{settings.keycloak_url}/admin/realms/{settings.keycloak_realm}/users/{user_id}/role-mappings/realm",
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
