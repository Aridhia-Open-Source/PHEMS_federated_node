## This file should just include a keycloak method that cleans up
# users, clients and other permissions. We could simply mock all calls
# but this way we can also test keycloak's configuration
import requests

from app.helpers.keycloak import Keycloak, URLS

def clean_kc():
    """
    Removes all users but admin
    """
    token = Keycloak().get_admin_token_global()
    response = requests.get(
        URLS["user"],
        headers={"Authorization": f"Bearer {token}"}
    )
    for user in response.json():
        if user["username"] != "admin":
            requests.delete(
                URLS["user"] + f"/{user["id"]}",
                headers={"Authorization": f"Bearer {token}"}
            )
