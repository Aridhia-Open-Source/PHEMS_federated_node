import logging
import os
import random
import re
import time
import requests

from app.helpers.exceptions import AuthenticationError, KeycloakError
from app.helpers.const import PASS_GENERATOR_SET

logger = logging.getLogger('keycloak_helper')
logger.setLevel(logging.INFO)

KEYCLOAK_NAMESPACE = os.getenv("KEYCLOAK_NAMESPACE")
KEYCLOAK_URL = os.getenv("KEYCLOAK_URL", f"http://keycloak.{KEYCLOAK_NAMESPACE}.svc.cluster.local")
REALM = os.getenv("KEYCLOAK_REALM", "FederatedNode")
KEYCLOAK_CLIENT = os.getenv("KEYCLOAK_CLIENT", "global")
# `admin` is the operator's Keycloak console account. It is kept here only so the user list can
# filter it out -- nothing authenticates as it. Its password is operator-owned and may change at
# any time, so relying on it would make the backend break whenever an operator rotated it.
KEYCLOAK_ADMIN = os.getenv("KEYCLOAK_ADMIN")
# The platform's service account. Holds realm-management's realm-admin in the node's realm and no
# node role (ADR 0037): it manages Keycloak users and groups and never calls nexus-api.
KEYCLOAK_SERVICE_USER = os.getenv("KEYCLOAK_SERVICE_USER", "fn-service")

# kc-secrets is mounted as a directory (see the chart's kcSecretsMountPath helper) rather than
# injected via envFrom, so that a credential rotation reaches this process without a restart.
KC_SECRETS_PATH = os.getenv("KC_SECRETS_PATH", "/etc/secrets/kc")


def read_secret(name: str, default: str = "") -> str:
    """
    Read a credential, preferring the mounted file over the environment.

    Kubernetes refreshes a mounted secret within roughly two minutes, and only when it is mounted as
    a directory; a `subPath` mount is never updated. Reads are from tmpfs, so doing this per call is
    cheap.

    Falls back to the environment so local runs and docker-compose, which have no mount, keep
    working unchanged.
    """
    try:
        with open(os.path.join(KC_SECRETS_PATH, name), encoding="utf-8") as handle:
            return handle.read().strip()
    except FileNotFoundError:
        return os.getenv(name, default)
    except OSError as exc:
        logger.warning("Could not read secret %s (%s), falling back to the environment", name, exc)
        return os.getenv(name, default)


def keycloak_secret() -> str:
    """The `global` client secret."""
    return read_secret("KEYCLOAK_SECRET")


def keycloak_service_password() -> str:
    return read_secret("KEYCLOAK_SERVICE_PASSWORD")


# How long a service-account token may be reused, in seconds. 0 disables caching.
#
# Without this, every Keycloak() instantiation performs a fresh password grant, and a single request
# builds several Keycloak objects -- so a brief authentication outage during a credential rotation
# turns into a total outage rather than a few failed calls. Defaults to off so the existing test
# suite, which mocks the token endpoint per test, is unaffected; the chart enables it in production.
TOKEN_CACHE_TTL = int(os.getenv("KEYCLOAK_TOKEN_CACHE_TTL", "0"))

# How many times to retry a service-account login before giving up, and how long to wait between
# attempts. Passwords have no dual-credential grace period in Keycloak (unlike client secrets), so
# during a rotation there is a brief cutover where the credential on disk and the one Keycloak holds
# disagree. Re-reading and retrying rides over the instant of changeover.
SERVICE_LOGIN_ATTEMPTS = int(os.getenv("KEYCLOAK_SERVICE_LOGIN_ATTEMPTS", "3"))
SERVICE_LOGIN_BACKOFF = float(os.getenv("KEYCLOAK_SERVICE_LOGIN_BACKOFF", "1.5"))

# Keyed by the credential itself, so a rotated password can never hit a token minted with the old
# one -- the key simply stops matching.
_token_cache: dict = {}


def clear_token_cache():
    """Drop any cached service-account tokens. Used by tests and after a failed authentication."""
    _token_cache.clear()


def _cached_token(cache_key: tuple):
    if TOKEN_CACHE_TTL <= 0:
        return None
    entry = _token_cache.get(cache_key)
    if entry and entry["expires_at"] > time.monotonic():
        return entry["token"]
    return None


def _store_token(cache_key: tuple, token: str):
    if TOKEN_CACHE_TTL > 0:
        _token_cache[cache_key] = {
            "token": token,
            "expires_at": time.monotonic() + TOKEN_CACHE_TTL,
        }


URLS = {
    "health_check": f"{KEYCLOAK_URL}/realms/master",
    "get_token": f"{KEYCLOAK_URL}/realms/{REALM}/protocol/openid-connect/token",
    "client": f"{KEYCLOAK_URL}/admin/realms/{REALM}/clients",
    "client_secret": f"{KEYCLOAK_URL}/admin/realms/{REALM}/clients/%s/client-secret",
    "roles": f"{KEYCLOAK_URL}/admin/realms/{REALM}/roles",
    "user": f"{KEYCLOAK_URL}/admin/realms/{REALM}/users",
    "user_role": f"{KEYCLOAK_URL}/admin/realms/{REALM}/users/%s/role-mappings/realm",
    "user_reset": f"{KEYCLOAK_URL}/admin/realms/{REALM}/users/%s/reset-password"
}


def user_tokens(**grant) -> dict:
    """
    A password or refresh_token grant for the global client, without the admin calls Keycloak() makes:
    {"token": <access token>, "refresh_token": ...}. Clients send the access token (ADR 0036).
    """
    response = requests.post(
        URLS["get_token"], data={"client_id": KEYCLOAK_CLIENT, "client_secret": keycloak_secret(), **grant}, timeout=30
    )
    if not response.ok:
        logger.info(response.text)
        if re.match("Account is not fully set up", response.json().get("error_description", "")):
            raise AuthenticationError("Temporary password must be changed before logging in")
        raise AuthenticationError("Failed to login")
    body = response.json()
    return {"token": body["access_token"], "refresh_token": body["refresh_token"]}


class Keycloak:
    def __init__(self, client='global') -> None:
        self.client_name = client
        self.admin_token = self.get_admin_token()
        self.client_id = self.get_client_id()
        self.client_secret = self._get_client_secret()

    def _post_json_headers(self) -> dict:
        """
        Default value for a json request header
        """
        return {
            "Authorization": f"Bearer {self.admin_token}",
            "Content-Type": "application/json"
        }

    def check_if_keycloak_resp_executable(self, response) -> bool:
        """
        If the response status code is:
            - 2xx (ok) or
            - 409 (conflict, resource already exists)
        return true, meaning we don't need to recreate them and we can continue
        """
        return response.status_code == 409 or response.ok

    def _get_client_secret(self, client_id:str=None) -> str:
        """
        Given the client id, fetches the client's secret if has one.
        """
        if not client_id:
            client_id = self.client_id

        secret_resp = requests.get(
            URLS["client_secret"] % client_id,
            headers={
                "Authorization": f"Bearer {self.admin_token}"
            }
        )
        if not secret_resp.ok:
            logger.info(secret_resp.content.decode())
            raise KeycloakError(f"Failed to fetch {client_id}'s secret")

        return secret_resp.json()["value"]

    def get_token(self, username=None, password=None, token_type='refresh_token', payload:dict=None, raise_on_temp_pass:bool=True) -> str:
        """
        Get a token for a given set of credentials

        :params token_type: one of "refresh_token" and "access_token"
        :params payload: the body for the post request to keycloak
        :params raise_on_temp_pass: if set to False, it will exit early and
            return the whole response object, otherwise it will raise exceptions
            on status code != 200
        """
        logger.info("%s) get_token", self.client_name)
        if payload is None:
            payload = {
                'client_id': self.client_name,
                'client_secret': self.client_secret,
                'grant_type': 'password',
                'username': username,
                'password': password
            }

        response_auth = requests.post(
            URLS["get_token"],
            data=payload,
            headers={
                'Content-Type': 'application/x-www-form-urlencoded'
            }
        )

        if not raise_on_temp_pass:
            return response_auth

        if not response_auth.ok:
            logger.info(response_auth.content.decode())

            if re.match("Account is not fully set up", response_auth.json().get("error_description")):
                raise AuthenticationError("Temporary password must be changed before logging in")

            raise AuthenticationError("Failed to login")
        return response_auth.json()[token_type]

    def _service_login(self, cache_name: str, build_payload) -> str:
        """
        Authenticate as the service account, tolerating a credential rotation in progress.

        Credentials are re-read from disk on every attempt (build_payload is a callable for exactly
        that reason), so a retry picks up a value that has just been synced into the pod rather than
        replaying the stale one. Keycloak has no dual-password concept, so unlike the client secret
        there is no grace period to fall back on -- retrying across the cutover instant is the only
        mitigation available.
        """
        payload = build_payload()
        cache_key = (cache_name, payload.get('password'), payload.get('client_secret'))
        cached = _cached_token(cache_key)
        if cached:
            return cached

        last_error = None
        for attempt in range(1, SERVICE_LOGIN_ATTEMPTS + 1):
            # Rebuilt per attempt so the credential is genuinely re-read from the mounted file.
            payload = build_payload()
            try:
                token = self.get_token(token_type='access_token', payload=payload)
                _store_token(
                    (cache_name, payload.get('password'), payload.get('client_secret')), token
                )
                return token
            except AuthenticationError as exc:
                last_error = exc
                clear_token_cache()
                if attempt < SERVICE_LOGIN_ATTEMPTS:
                    logger.warning(
                        "Service account login failed (attempt %s/%s). Retrying in %ss -- a "
                        "credential rotation may be in progress.",
                        attempt, SERVICE_LOGIN_ATTEMPTS, SERVICE_LOGIN_BACKOFF
                    )
                    time.sleep(SERVICE_LOGIN_BACKOFF)
        raise last_error

    def get_admin_token(self) -> str:
        """
        Get administrative level token
        """
        return self._service_login("admin-cli", lambda: {
            'client_id': 'admin-cli',
            'grant_type': 'password',
            'username': KEYCLOAK_SERVICE_USER,
            'password': keycloak_service_password()
        })

    def get_client_id(self, client_name=None) -> str:
        """
        Get a give Keycloak client id, if not provided, the instanced
        one will be returned
        """
        headers={
            'Authorization': f'Bearer {self.admin_token}'
        }
        if client_name is None:
            client_name = self.client_name

        client_id_resp = requests.get(
            URLS["client"],
            params = {"clientId": client_name},
            headers=headers
        )
        if not client_id_resp.ok:
            logger.info(client_id_resp.content.decode())
            raise KeycloakError("Could not find client")
        if not len(client_id_resp.json()):
            raise KeycloakError("Could not find project", 400)

        return client_id_resp.json()[0]["id"]

    def get_role(self, role_name:str) -> dict[str, str]:
        """
        Get the realm roles.

        Returns a dictionary {name: str, id: str}

        Raises a specific exception if not found
        """
        realm_resp = requests.get(
            URLS["roles"] + f"/{role_name}",
            headers={
                'Authorization': f'Bearer {self.admin_token}',
            }
        )
        match realm_resp.status_code:
            case 200:
                return realm_resp.json()
            case 404:
                logger.info(realm_resp.content.decode())
                raise KeycloakError(f"Role {role_name} does not exist", 400)
            case _:
                logger.info(realm_resp.content.decode())
                raise KeycloakError("Failed to fetch roles")

    def create_user(self, set_temp_pass=False, **kwargs) -> dict:
        """
        Method that handles the user creation. Keycloak will need username as
        mandatory field, but we would set a temporary password so the user
        can reset it on the first login.
        **kwargs are optional parameters i.e. email, firstName, lastName, etc.
        """
        random_password = ''.join(random.choice(PASS_GENERATOR_SET) for _ in range(12))
        username = kwargs.get("username", kwargs.get("email"))

        # Make sure the role exists before creating the user
        role = self.get_role(kwargs.get("role", "Users"))

        user_response = requests.post(
            URLS["user"],
            json={
                "firstName": kwargs.get("firstName", ""),
                "lastName": kwargs.get("lastName", ""),
                "email": kwargs.get("email"),
                "enabled": True,
                "emailVerified": True,
                "username": username,
                "credentials": [{
                    "type": "password",
                    "temporary": set_temp_pass,
                    "value": random_password
                }]
            },
            headers=self._post_json_headers()
        )

        if not user_response.ok and user_response.status_code != 409:
            logger.info(user_response.text)
            raise KeycloakError("Failed to create the user")

        user_info = self.get_user(username)

        # Assign a role
        self.assign_role_to_user(user_info["id"], role)

        user_info["password"] = random_password

        return user_info

    def assign_role_to_user(self, user_id:str, role:str|dict ="Users"):
        """
        Keycloak REST API can't handle role assignation to a user on creation
        has to be a separate call.

        :param user_id: a string representing the user_id from keycloak
        :param role: either a string with the role name, or a dictionary that contains role's name and id
        """
        if isinstance(role, str):
            role = self.get_role(role)
        user_role_response = requests.post(
            URLS["user_role"] % user_id,
            json=[role],
            headers=self._post_json_headers()
        )
        if not user_role_response.ok and user_role_response.status_code != 409:
            logger.info(user_role_response.text)
            raise KeycloakError("Failed to create the user")

    def list_users(self) -> list[dict]:
        """
        Method to return a dictionary representing a Keycloak user
        """
        user_response = requests.get(
            URLS["user"],
            headers={"Authorization": f"Bearer {self.admin_token}"}
        )
        if not user_response.ok:
            raise KeycloakError("Failed to fetch the users")

        return user_response.json()

    def get_user(self, username:str) -> dict:
        """
        Method to return a dictionary representing a Keycloak user,
        checks for both username and email
        """
        by_un = self.get_user_by_username(username)
        if by_un:
            return by_un

        by_em = self.get_user_by_email(username)
        if by_em:
            return by_em

        raise KeycloakError("Failed to fetch the created user")

    def get_user_by_username(self, username:str) -> dict:
        """
        Method to return a dictionary representing a Keycloak user
        """
        user_response = requests.get(
            URLS["user"],
            params= {
                "username": username,
                "exact": True
            },
            headers={"Authorization": f"Bearer {self.admin_token}"}
        )
        if not user_response.ok:
            raise KeycloakError("Failed to fetch the user")

        return user_response.json()[0] if user_response.json() else None

    def get_user_by_email(self, email: str) -> dict:
        """
        Method to return a dictionary representing a Keycloak user,
        using their email
        """
        user_response = requests.get(
            URLS["user"],
            params= {
                "email": email,
                "exact": True
            },
            headers={"Authorization": f"Bearer {self.admin_token}"}
        )
        if not user_response.ok:
            raise KeycloakError("Failed to fetch the user")

        return user_response.json()[0] if user_response.json() else None

    def get_user_by_id(self, user_id:str) -> dict:
        """
        Method to return a dictionary representing a Keycloak user,
        using their id
        """
        user_response = requests.get(
            f"{URLS["user"]}/{user_id}",
            headers={"Authorization": f"Bearer {self.admin_token}"}
        )
        if not user_response.ok:
            raise KeycloakError("Failed to fetch the user")

        return user_response.json() if user_response.json() else None

    def get_user_role(self, user_id:str) -> list[str]:
        """
        From a user id, get all of their realm roles
        """
        role_response = requests.get(
            URLS["user_role"] % user_id,
            headers={"Authorization": f"Bearer {self.admin_token}"}
        )
        if not role_response.ok:
            raise KeycloakError("Failed to get the user's role")

        return [role["name"] for role in role_response.json()]

    def has_user_roles(self, user_id:str, roles:set) -> bool:
        """
        With the user id checks if it has certain realm roles
        """
        return roles.intersection(self.get_user_role(user_id))

    def reset_user_pass(self, user_id:str, username:str, old_pass:str, new_pass:str):
        """
        Simply change the temp password for the user.
        The old_pass will be used to check if a change is needed,
            if that's the case, we'll update the password
        """
        auth_user = self.get_token(username=username, password=old_pass, raise_on_temp_pass=False)

        if not re.match("Account is not fully set up", auth_user.json().get("error_description", "")):
            raise AuthenticationError("Incorrect credentials")

        res_pass_resp = requests.put(
            URLS["user_reset"] % user_id,
            json={
                "type": "password",
                "temporary": False,
                "value": new_pass
            },
            headers={"Authorization": f"Bearer {self.admin_token}"}
        )
        if not self.check_if_keycloak_resp_executable(res_pass_resp):
            logging.error(res_pass_resp.json())
            raise KeycloakError("Could not update the password.")
