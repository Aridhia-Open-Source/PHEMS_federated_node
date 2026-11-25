import logging
import os
import random
import re
import string
import time

from fednode.clients.kubernetes.mounted import MountedSecret

from fednode.clients.keycloak.admin import KeycloakAdmin
from fednode.clients.keycloak.login import KeycloakLogin

from app.helpers.exceptions import AuthenticationError, UnauthorizedError, KeycloakError

logger = logging.getLogger('keycloak_helper')
logger.setLevel(logging.INFO)

PASS_GENERATOR_SET = string.ascii_letters + string.digits + "!$@#.-_"

KEYCLOAK_NAMESPACE = os.getenv("KEYCLOAK_NAMESPACE")
KEYCLOAK_URL = os.getenv("KEYCLOAK_URL", f"http://keycloak.{KEYCLOAK_NAMESPACE}.svc.cluster.local")
REALM = os.getenv("KEYCLOAK_REALM", "FederatedNode")
KEYCLOAK_CLIENT = os.getenv("KEYCLOAK_CLIENT", "global")
# `admin` is the operator's Keycloak console account. It is kept here only so the user list can
# filter it out -- nothing authenticates as it. Its password is operator-owned and may change at
# any time, so relying on it would make the backend break whenever an operator rotated it.
KEYCLOAK_ADMIN = os.getenv("KEYCLOAK_ADMIN")
# The platform's service account. Holds Super Administrator in the FederatedNode realm, which is
# exactly what the `admin` realm user used to hold, so the permissions are unchanged.
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
    return MountedSecret(KC_SECRETS_PATH).read(name, default)


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


class Keycloak:
    """
    The platform's Keycloak rules: users, roles, projects' clients, permissions and what a refused answer means. The
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

    @classmethod
    def get_token_from_headers(cls, headers) -> str:
        """
        Public method for generalize the token fetching from an HTTP header
        """
        return headers['Authorization'].replace('Bearer ', '')

    def exchange_global_token(self, token:str, type:str="access_token") -> str:
        """
        Token exchange across clients. From global to the instanced one
        """
        ac_resp = self.login.refresh_grant(KEYCLOAK_CLIENT, keycloak_secret(), token)
        if not ac_resp.ok:
            logger.error(ac_resp.text)
            raise KeycloakError("Cannot get an access token")
        access_token = ac_resp.json()["access_token"]

        exchange_resp = self.login.exchange_grant(
            KEYCLOAK_CLIENT, keycloak_secret(), access_token, self.client_name, "access_token"
        )
        if not exchange_resp.ok:
            logger.error(exchange_resp.text)
            raise KeycloakError("Cannot exchange token")
        return exchange_resp.json()[type]

    def get_impersonation_token(self, user_id:str) -> str:
        """
        Method to request a token on behalf of another user
        : user_id : The keycloak user's id to impersonate
        """
        exchange_resp = self.login.exchange_grant(
            KEYCLOAK_CLIENT,  # Target client
            keycloak_secret(),  # Target client
            self.get_admin_token_global(),
            KEYCLOAK_CLIENT,
            "refresh_token",
            requested_subject=user_id
        )
        if not exchange_resp.ok:
            logger.info(exchange_resp.content.decode())
            raise KeycloakError("Cannot exchange impersonation token")
        return exchange_resp.json()["refresh_token"]

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

    def is_user_admin(self, token:str) -> bool:
        """
        Given a token checks if the owner is an Admin or SuperAdmin
        """
        response_auth = self.login.introspect(self.client_name, self.client_secret, token)
        if not response_auth.ok:
            logger.info(response_auth.content.decode())
            raise AuthenticationError("Failed to login")
        return "Administrator" in response_auth.json()["realm_access"]["roles"]

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

    def get_admin_token_global(self) -> str:
        """
        Get administrative level token
        """
        logger.info("get_admin_token_global")
        return self._service_login("global", KEYCLOAK_CLIENT, keycloak_secret)

    def get_admin_token(self) -> str:
        """
        Get administrative level token
        """
        return self._service_login("admin-cli", 'admin-cli')

    def is_token_valid(self, token:str, scope:str, resource:str, tok_type='refresh_token', with_permissions:bool=True) -> bool:
        """
        Ping KC to check if the token is valid or not
        """
        is_access_token = tok_type == 'access_token'
        if is_access_token:
            response_auth = self.login.introspect(self.client_name, self.client_secret, token)
        else:
            response_auth = self.login.refresh_grant(self.client_name, self.client_secret, token)

        # FIXME: Temporary workaround for system users
        if with_permissions and not self.is_system_user(token):
            return response_auth.ok and self.check_permissions(token, scope, resource, is_access_token)

        return response_auth.ok

    def is_system_user(self, token: str) -> bool:
        token_dict = self.decode_token(token)
        roles = token_dict.get("realm_access", {}).get("roles", [])
        return 'system' in [r.lower() for r in roles]

    def decode_token(self, token: str) -> dict:
        """
        Simple token decode, mostly to fetch user general info or exp date
        """
        token = self._access_from_refresh(token)
        response_validate = self.login.introspect(self.client_name, self.client_secret, token)
        if response_validate.json().get('active'):
            return response_validate.json()
        raise AuthenticationError("Token expired. Validation failed")

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

    def _access_from_refresh(self, token:str) -> str:
        """
        Simply exchanges the refresh token for an access token
        """
        logger.info("%s) get_token", self.client_name)
        return self._token_from(
            self.login.refresh_grant(self.client_name, self.client_secret, token), 'access_token'
        )

    def check_permissions(self, token:str, scope:str, resource:str, is_access_token=False) -> bool:
        if not is_access_token:
            token = self._access_from_refresh(token)

        request_perm = self.login.permission_decision(
            token, self.client_name, f"{self.get_resource(resource)["_id"]}#{scope}"
        )
        if not request_perm.ok:
            logger.info(request_perm.content.decode())
            raise UnauthorizedError("User is not authorized")
        return True

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

    def get_resource(self, resource_name:str) -> dict:
        response_res = self.admin.resources(self.client_id, name=resource_name)
        if not response_res.ok:
            logger.info(response_res.content.decode())
            raise KeycloakError("Failed to fetch the resource")
        if len(response_res.json()) > 0:
            return response_res.json()[0]

        raise KeycloakError("Failed to fetch the resource")

    def patch_resource(self, resource_name:str, **kwargs) -> dict:
        """
        Given a resource name submits a PUT request by using the
        current resource body merged with what's been passed trough
        kwargs.
        Most likely we're interested in:
            - name
            - displayName
        as values to be merged and patched into the current resource
        """
        resource = self.get_resource(resource_name)
        resource.update(kwargs)

        response_res = self.admin.update_resource(self.client_id, resource["_id"], resource)
        if not response_res.ok:
            logger.info(response_res.content.decode())
            raise KeycloakError("Failed to patch the resource")

    def get_policy(self, name:str) -> dict:
        """
        Given a name and (optional) reosource (global or dataset specific)
        return a policy dict
        """
        policy_response = self.admin.policies(self.client_id, name=name, permission=False)
        if not policy_response.ok:
            logger.info(policy_response.content.decode())
            raise KeycloakError("Error when fetching the policies from Keycloak")

        return policy_response.json()[0]

    def get_scope(self, name:str) -> dict:
        """
        Given a name and (optional) reosource (global or dataset specific)
        return a policy dict
        """
        scope_response = self.admin.scopes(self.client_id, permission=False, name=name)
        if not scope_response.ok:
            logger.info(scope_response.content.decode())
            raise KeycloakError("Error when fetching the scopes from Keycloak")

        return scope_response.json()[0]

    def delete_resource(self, resource_name:str):
        """
        Given a resource name, delete the resource from Keycloak
        """
        # TODO: not implemented yet
        raise NotImplementedError("TODO: delete a Keycloak resource")

    def delete_permission(self, permission_name:str):
        """
        Given a permission name, delete the permission from Keycloak
        """
        # TODO: not implemented yet
        raise NotImplementedError("TODO: delete a Keycloak permission")

    def delete_policy(self, name:str):
        """
        Given a policy name, delete the policy from Keycloak
        """
        # TODO: not implemented yet
        raise NotImplementedError("TODO: delete a Keycloak policy")

    def create_client(self, client_name:str, token_lifetime:int) -> dict:
        """
        Create a new client for a given project. If it exist already,
            return that one
        : token_lifetime : time in seconds for the
        """
        client_post_rest = self.admin.create_client({
            "clientId": client_name,
            "authorizationServicesEnabled": True,
            "directAccessGrantsEnabled": True,
            "serviceAccountsEnabled": True,
            "publicClient": False,
            "redirectUris": ["/"],
            "attributes": {
                "client.offline.session.max.lifespan": token_lifetime
            }
        })

        # Client exists. Return that one
        if not client_post_rest.ok and client_post_rest.status_code != 409:
            logger.info(client_post_rest.content.decode())
            raise KeycloakError("Failed to create a project")

        update_req = self.admin.update_resource_server(
            self.get_client_id(client_name), {"decisionStrategy": "AFFIRMATIVE"}
        )
        if not update_req.ok:
            logger.info(update_req.content.decode())
            raise KeycloakError("Failed to create a project")

        return self.get_client_id(client_name)

    def create_scope(self, scope_name) -> dict:
        """
        Create a custom scope for the instanced client
        """
        scope_post_rest = self.admin.create_scope(self.client_id, {"name": scope_name})
        if scope_post_rest.status_code == 409:
            return self.get_scope(scope_name)
        elif not scope_post_rest.ok:
            logger.info(scope_post_rest.content.decode())
            raise KeycloakError("Failed to create a project's scope")

        return scope_post_rest.json()

    def create_policy(self, payload:dict, policy_type:str) -> dict:
        """
        Creates a custom policy for a resource
        """
        policy_response = self.admin.create_policy(self.client_id, policy_type, payload)
        # If it exists already
        if policy_response.status_code == 409:
            return self.get_policy(payload["name"])
        elif not policy_response.ok:
            logger.info(policy_response.content.decode())
            raise KeycloakError("Failed to create a project's policy")

        return policy_response.json()

    def create_or_update_time_policy(self, payload:dict, policy_type:str) -> dict:
        """
        Time policies need a separate treatement. This is the only policy that we will
        allow to be updated, in cases of token renewals via DAR
        """
        current_policy = self.create_policy(payload, policy_type)
        # Only update the time policy. If it's a brand new, it will return
        # the payload as response, otherwise the "config" field will be there
        if current_policy.get("config"):
            current_policy["config"]["noa"] = payload['notOnOrAfter']
            current_policy["config"]["nbf"] = payload['notBefore']
            policy_response = self.admin.update_policy(self.client_id, current_policy["id"], current_policy)
            if not policy_response.ok:
                logger.info(policy_response.content.decode())
                raise KeycloakError("Failed to create a project's policy")

        return current_policy

    def create_resource(self, payload:dict, client_name='global') -> dict:
        payload["owner"] = {
            "id": self.client_id, "name": client_name
        }
        resource_response = self.admin.create_resource(self.client_id, payload)
        if resource_response.status_code == 409:
            return self.get_resource(payload["name"])
        elif not resource_response.ok:
            logger.info(resource_response.content.decode())
            raise KeycloakError("Failed to create a project's resource")

        return resource_response.json()

    def create_permission(self, payload:dict) -> dict:
        permission_response = self.admin.create_permission(self.client_id, payload)
        if not self.check_if_keycloak_resp_executable(permission_response):
            logger.info(permission_response.content.decode())
            raise KeycloakError("Failed to create a project's permission")

        return permission_response.json()

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

    def enable_token_exchange(self):
        """
        Method to automate the setup for this client to
        allow token exchange on behalf of a user for admin-level
        """
        client_permission_resp = self.admin.set_client_permissions(self.client_id, {"enabled": True})
        if not client_permission_resp.ok:
            raise KeycloakError("Failed to set exchange permissions")

        rm_client_id = self.get_client_id('realm-management')
        global_client_id = self.get_client_id('global')

        # Fetching the token exchange scope
        client_te_scope_resp = self.admin.scopes(rm_client_id, permission=False, name="token-exchange")
        if not client_te_scope_resp.ok:
            raise KeycloakError("Error on keycloak")

        token_exch_scope = client_te_scope_resp.json()[0]["id"]
        resource_scope_resp = self.admin.resources(rm_client_id, name=f"client.resource.{self.client_id}")
        resource_id = resource_scope_resp.json()[0]["_id"]

        # Create a custom client exchange policy
        global_client_policy_resp = self.admin.create_policy(rm_client_id, "/client", {
            "name": f"token-exchange-{self.client_name}",
            "logic": "POSITIVE",
            "clients": [global_client_id, self.client_id]
        })
        if global_client_policy_resp.status_code == 409:
            global_policy_id = self.admin.policies(
                rm_client_id, "/client", name=f"token-exchange-{self.client_name}"
            ).json()[0]["id"]
        elif not global_client_policy_resp.ok:
            logger.error(global_client_policy_resp.json())
            raise KeycloakError("Something went wrong in creating the set of permissions on Keycloak")
        else:
            global_policy_id = global_client_policy_resp.json()["id"]

        token_exch_name = f"token-exchange.permission.client.{self.client_id}"
        token_exch_permission_resp = self.admin.permissions(rm_client_id, name=token_exch_name)
        token_exch_permission_id = token_exch_permission_resp.json()[0]["id"]
        # Updating the permission
        client_permission_resp = self.admin.update_permission(rm_client_id, token_exch_permission_id, {
            "name": token_exch_name,
            "logic": "POSITIVE",
            "decisionStrategy": "UNANIMOUS",
            "resources": [resource_id],
            "policies": [global_policy_id],
            "scopes": [token_exch_scope]
        })
        if not client_permission_resp.ok:
            raise KeycloakError("Failed to update the exchange permission")
