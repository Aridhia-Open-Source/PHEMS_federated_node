import logging
import random
import re
import string
import time
from pathlib import Path

from fednode.clients.keycloak.admin import KeycloakAdmin
from fednode.clients.keycloak.login import KeycloakLogin

from app.settings import settings
from app.helpers.exceptions import AuthenticationError, KeycloakError

logger = logging.getLogger('keycloak_helper')
logger.setLevel(logging.INFO)

PASS_GENERATOR_SET = string.ascii_letters + string.digits + "!$@#.-_"

KEYCLOAK_URL = settings.services.keycloak.url
REALM = settings.services.keycloak.realm
KEYCLOAK_CLIENT = settings.services.keycloak.client
# `admin` is the operator's Keycloak console account. It is kept here only so the user list can
# filter it out -- nothing authenticates as it. Its password is operator-owned and may change at
# any time, so relying on it would make the backend break whenever an operator rotated it.
KEYCLOAK_ADMIN = settings.services.keycloak.admin
# The platform's service account. Holds realm-management's realm-admin in the node's realm and no
# node role (ADR 0036): it manages Keycloak users and groups and never calls nexus-api.
KEYCLOAK_SERVICE_USER = settings.services.keycloak.service_user


def read_secret(name: str, fallback: str | None) -> str:
    """
    Read a credential, preferring the mounted file over the environment.

    kc-secrets is mounted as a directory (see the chart's kcSecretsMountPath helper) rather than injected via envFrom,
    so that a credential rotation reaches this process without a restart.

    Kubernetes refreshes a mounted secret within roughly two minutes, and only when it is mounted as
    a directory; a `subPath` mount is never updated. Reads are from tmpfs, so doing this per call is
    cheap.

    Local runs may supply a fallback; a missing credential or an unreadable file is an error.
    """
    path = Path(settings.services.keycloak.secrets_path) / name
    try:
        return path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        if fallback is None:
            raise KeycloakError(f"Credential {name} is neither mounted at {path} nor set in the environment") from None
        return fallback


def keycloak_secret() -> str:
    """The `global` client secret."""
    return read_secret("KEYCLOAK_SECRET", settings.services.keycloak.secret)


def keycloak_service_password() -> str:
    return read_secret("KEYCLOAK_SERVICE_PASSWORD", settings.services.keycloak.service_password)


# How long a service-account token may be reused, in seconds. 0 disables caching.
#
# Without this, every Keycloak() instantiation performs a fresh password grant, and a single request
# builds several Keycloak objects -- so a brief authentication outage during a credential rotation
# turns into a total outage rather than a few failed calls. Defaults to off so the existing test
# suite, which mocks the token endpoint per test, is unaffected; the chart enables it in production.
TOKEN_CACHE_TTL = settings.services.keycloak.token_cache_ttl

# How many times to retry a service-account login before giving up, and how long to wait between
# attempts. Passwords have no dual-credential grace period in Keycloak (unlike client secrets), so
# during a rotation there is a brief cutover where the credential on disk and the one Keycloak holds
# disagree. Re-reading and retrying rides over the instant of changeover.
SERVICE_LOGIN_ATTEMPTS = settings.services.keycloak.login_attempts
SERVICE_LOGIN_BACKOFF = settings.services.keycloak.login_backoff

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


def user_tokens(**grant) -> dict:
    """
    A password or refresh_token grant for the global client, without the admin calls Keycloak() makes:
    {"token": <access token>, "refresh_token": ...}. Clients send the access token (ADR 0035).
    """
    response = KeycloakLogin(KEYCLOAK_URL, REALM).token(
        {"client_id": KEYCLOAK_CLIENT, "client_secret": keycloak_secret(), **grant}
    )
    if not response.ok:
        logger.info(response.text)
        if re.match("Account is not fully set up", response.json().get("error_description", "")):
            raise AuthenticationError("Temporary password must be changed before logging in")
        raise AuthenticationError("Failed to login")
    body = response.json()
    return {"token": body["access_token"], "refresh_token": body["refresh_token"]}


class Keycloak:
    """
    The platform's Keycloak rules: users and roles, and what a refused answer means. The
    calls are fednode's (`KeycloakLogin` for tokens, `KeycloakAdmin` for the admin API, ADR 0039); an answer that is
    not ok is turned into this API's errors here.
    """
    def __init__(self, client='global') -> None:
        self.client_name = client
        self.login = KeycloakLogin(KEYCLOAK_URL, REALM)
        self.admin_token = self.get_admin_token()
        self.admin = KeycloakAdmin(KEYCLOAK_URL, REALM, self.admin_token)
        self.client_id = self.get_client_id()
        self.client_secret = self._get_client_secret()

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

        secret_resp = self.admin.client_secret(client_id)
        if not secret_resp.ok:
            logger.info(secret_resp.content.decode())
            raise KeycloakError(f"Failed to fetch {client_id}'s secret")

        return secret_resp.json()["value"]

    def get_token(self, username=None, password=None, token_type='refresh_token', raise_on_temp_pass:bool=True) -> str:
        """
        Get a token for a given set of credentials

        :params token_type: one of "refresh_token" and "access_token"
        :params raise_on_temp_pass: if set to False, it will exit early and
            return the whole response object, otherwise it will raise exceptions
            on status code != 200
        """
        logger.info("%s) get_token", self.client_name)
        response_auth = self.login.password_grant(self.client_name, username, password, self.client_secret)

        if not raise_on_temp_pass:
            return response_auth

        return self._token_from(response_auth, token_type)

    def _token_from(self, response_auth, token_type:str) -> str:
        """
        The token of a login answer, or the error it means
        """
        if not response_auth.ok:
            logger.info(response_auth.content.decode())

            if re.match("Account is not fully set up", response_auth.json().get("error_description")):
                raise AuthenticationError("Temporary password must be changed before logging in")

            raise AuthenticationError("Failed to login")
        return response_auth.json()[token_type]

    def _service_login(self, cache_name: str, client_id: str, client_secret=None) -> str:
        """
        Authenticate as the service account, tolerating a credential rotation in progress.

        Credentials are re-read from disk on every attempt (client_secret is a callable for exactly
        that reason), so a retry picks up a value that has just been synced into the pod rather than
        replaying the stale one. Keycloak has no dual-password concept, so unlike the client secret
        there is no grace period to fall back on -- retrying across the cutover instant is the only
        mitigation available.
        """
        def read_credentials():
            return keycloak_service_password(), client_secret() if client_secret else None

        password, secret = read_credentials()
        cached = _cached_token((cache_name, password, secret))
        if cached:
            return cached

        last_error = None
        for attempt in range(1, SERVICE_LOGIN_ATTEMPTS + 1):
            # Read per attempt so the credential is genuinely re-read from the mounted file.
            password, secret = read_credentials()
            try:
                logger.info("%s) get_token", self.client_name)
                token = self._token_from(
                    self.login.password_grant(client_id, KEYCLOAK_SERVICE_USER, password, secret), 'access_token'
                )
                _store_token((cache_name, password, secret), token)
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
        return self._service_login("admin-cli", 'admin-cli')

    def get_client_id(self, client_name=None) -> str:
        """
        Get a give Keycloak client id, if not provided, the instanced
        one will be returned
        """
        if client_name is None:
            client_name = self.client_name

        client_id_resp = self.admin.find_clients(client_name)
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
        realm_resp = self.admin.get_role(role_name)
        match realm_resp.status_code:
            case 200:
                return realm_resp.json()
            case 404:
                logger.info(realm_resp.content.decode())
                raise KeycloakError(f"Role {role_name} does not exist", 400)
            case _:
                logger.info(realm_resp.content.decode())
                raise KeycloakError("Failed to fetch roles")

    ### USERS' section
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

        user_response = self.admin.create_user({
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
        })

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
        user_role_response = self.admin.assign_roles(user_id, [role])
        if not user_role_response.ok and user_role_response.status_code != 409:
            logger.info(user_role_response.text)
            raise KeycloakError("Failed to create the user")

    def list_users(self) -> list[dict]:
        """
        Method to return a dictionary representing a Keycloak user
        """
        user_response = self.admin.users()
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
        user_response = self.admin.users(username=username, exact=True)
        if not user_response.ok:
            raise KeycloakError("Failed to fetch the user")

        return user_response.json()[0] if user_response.json() else None

    def get_user_by_email(self, email: str) -> dict:
        """
        Method to return a dictionary representing a Keycloak user,
        using their email
        """
        user_response = self.admin.users(email=email, exact=True)
        if not user_response.ok:
            raise KeycloakError("Failed to fetch the user")

        return user_response.json()[0] if user_response.json() else None

    def get_user_role(self, user_id:str) -> list[str]:
        """
        From a user id, get all of their realm roles
        """
        role_response = self.admin.user_roles(user_id)
        if not role_response.ok:
            raise KeycloakError("Failed to get the user's role")

        return [role["name"] for role in role_response.json()]

    def reset_user_pass(self, user_id:str, username:str, old_pass:str, new_pass:str):
        """
        Simply change the temp password for the user.
        The old_pass will be used to check if a change is needed,
            if that's the case, we'll update the password
        """
        auth_user = self.get_token(username=username, password=old_pass, raise_on_temp_pass=False)

        if not re.match("Account is not fully set up", auth_user.json().get("error_description", "")):
            raise AuthenticationError("Incorrect credentials")

        res_pass_resp = self.admin.reset_password(user_id, {
            "type": "password",
            "temporary": False,
            "value": new_pass
        })
        if not self.check_if_keycloak_resp_executable(res_pass_resp):
            logging.error(res_pass_resp.json())
            raise KeycloakError("Could not update the password.")

