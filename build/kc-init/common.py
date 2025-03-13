import requests
import time


MAX_RETRIES = 20


def health_check(kc_url:str):
    """
    Simple kecyloak health check
    """
    print("Health check on keycloak pod before starting")
    for i in range(1, MAX_RETRIES):
        print(f"Health check {i}/{MAX_RETRIES}")
        try:
            hc_resp = requests.get(f"{kc_url}/realms/master")
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
