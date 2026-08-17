import json
import os
import logging
from typing import List
from urllib.parse import quote
import requests
import time
from requests import Response


from settings import settings

logger = logging.getLogger('realm_common')
logger.setLevel(logging.INFO)

# Bootstrap admin usernames are generation-scoped (tmpadmin-1, tmpadmin-2, ...) so that a rotation
# always asks Keycloak for a username that cannot already exist. See keycloak-configmap.yaml.
BOOTSTRAP_USER_PREFIX = "tmpadmin"


def health_check():
    """
    Checks Keycloak's pod ready state, as the normal health_check
    is not enough, and 1+ replicas can reset progress.
    """
    logger.info("Checking on keycloak's pod's ready state")

    for i in range(1, settings.max_retries + 1):
        logger.info(f"Health check {i}/{settings.max_retries}")
        try:
            hc_resp = requests.get(f"{settings.keycloak_url}/realms/master")
            if hc_resp.ok:
                logger.info("Keycloak is alive")
                return
        except requests.exceptions.ConnectionError:
            pass

        logger.info("Retrying status in 10 seconds")
        time.sleep(10)

    logger.error("Max retries reached. Keycloak pods not ready")
    exit(1)

def is_response_good(response:Response) -> None:
    if not response.ok and response.status_code != 409:
        logger.error(f"{response.status_code} - {response.text}")
        exit(1)


def login(kc_url: str, kc_user: str, kc_pass: str, realm: str = "master",
          expected_to_fail: bool = False) -> str:
    """
    Common login function. Returns the access_token, or None on failure.

    The realm is a parameter because the platform's service account (fn-service) lives in the
    FederatedNode realm, not master. Authenticating there gives it admin-API access scoped to that
    one realm, which is the whole point: it never needs master-realm privileges, so a compromise
    cannot reach the Keycloak server configuration or any other realm.
    """
    logger.info(f"Logging in as '{kc_user}' against the {realm} realm...")
    url = f"{kc_url}/realms/{realm}/protocol/openid-connect/token"
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
        if expected_to_fail:
            # A failure here is a normal, expected outcome (see _authenticate): on a first install
            # the service account does not exist yet, and after a credential rotation its stored
            # password no longer matches. Logging it as an error would send operators chasing a
            # non-problem.
            logger.info(f"Could not log in as '{kc_user}' ({response.status_code})")
        elif kc_user == settings.kc_bootstrap_admin_username:
            logger.error("Error while logging in with bootstrap user. Most likely due to the keycloak pods not having " \
            "created one yet as part of init containers. This daemonset will retry. " \
            "If you can't login still, restart the keycloak statefulset")
        else:
            logger.error(response.json())
        return

    logger.info("Successful")
    return response.json()["access_token"]

def setup_master_user(user_id:str, admin_token:str, roles:List[str]):
    """
    Mostly to restore Keycloak UI access to the main super admin
    """
    for role in roles:
        role_id = get_role(role, admin_token, realm='master')
        assign_role(role, role_id, admin_token, 'master', user_id)

def get_role(role_name:str, admin_token:str, realm:str=settings.keycloak_realm):
    logger.info(f"Getting realms role {role_name} id")
    headers = {
        'Authorization': f'Bearer {admin_token}'
    }

    # Fetch the role by name rather than listing every role and filtering client-side: /roles is
    # paginated (Keycloak defaults to 100), so a realm with enough roles could return a page that
    # does not contain the one being looked for, and the old `[0]` index then raised IndexError.
    response = requests.get(
        f"{settings.keycloak_url}/admin/realms/{realm}/roles/{quote(role_name, safe='')}",
        headers=headers
    )
    if not response.ok:
        logger.error(f"Role '{role_name}' not found in realm {realm}: {response.status_code}")
        exit(1)
    logger.info("Got role")
    return response.json()["id"]

def create_user(
        username:str,
        password:str,
        email:str="",
        first_name:str="Admin",
        last_name:str="Admin",
        role_name:str="Super Administrator",
        with_role:bool=True,
        admin_token:str=None,
        realm:str=settings.keycloak_realm,
        reset_password_if_exists:bool=False,
        temporary:bool=False
    ) -> str:
    """
    Given a set of info about the user, create in the settings.keycloak_realm and
    assigns it the role as it can't be done all in one call.

    The default role, is Super Administrator, which is basically to ensure the backend
    has full access to it

    reset_password_if_exists controls what happens when the user is already present. Keycloak
    returns 409 and the supplied password is otherwise ignored, so a deliberate credential
    rotation would update Kubernetes but never reach Keycloak. Set it True for accounts whose
    password is owned by the platform and leave it False for accounts a human owns because
    resetting those would silently revert a password they chose.

    temporary marks the password as requiring a change at first login. Used for the `admin` console
    account, so Keycloak prompts the operator to set their own password and the generated one in
    kc-secrets stops being meaningful.
    """
    if not admin_token:
        admin_token = login(
            settings.keycloak_url,
            settings.kc_bootstrap_admin_username,
            settings.kc_bootstrap_admin_password
        )

    headers = {
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
                    "temporary": temporary,
                    "value": password
                }
            ]
        }
    )
    is_response_good(response_create_user)

    response_user_id = requests.get(
        f"{settings.keycloak_url}/admin/realms/{realm}/users",
        # exact=true: Keycloak does infix matching by default, so without this a username that is
        # a substring of another user's could resolve to the wrong account.
        params={"username": username, "exact": "true"},
        headers=headers
    )
    is_response_good(response_user_id)
    users = response_user_id.json()
    if not users:
        logger.error(f"User '{username}' not found in realm {realm} after create")
        exit(1)
    user_id = users[0]["id"]

    if response_create_user.status_code == 409 and reset_password_if_exists:
        logger.info(f"User '{username}' already exists, resetting its password")
        response_reset = requests.put(
            f"{settings.keycloak_url}/admin/realms/{realm}/users/{user_id}/reset-password",
            headers={**headers, 'Content-Type': 'application/json'},
            json={
                "type": "password",
                "temporary": False,
                "value": password
            }
        )
        is_response_good(response_reset)

    if with_role:
        logger.info(f"Assigning role {role_name} to {username}")
        assign_role(role_name, get_role(role_name, admin_token), admin_token, realm, user_id)

    return user_id

def assign_role(role_name, role_id, admin_token, realm, user_id):
    response_assign_role = requests.post(
        f"{settings.keycloak_url}/admin/realms/{realm}/users/{user_id}/role-mappings/realm",
        headers={
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {admin_token}'
        },
        json=[
            {
                "id": role_id,
                "name": role_name
            }
        ]
    )
    is_response_good(response_assign_role)

def get_client_uuid(client_name:str, admin_token:str, realm:str=settings.keycloak_realm) -> str:
    """
    Resolve a clientId (e.g. "global") to Keycloak's internal client UUID.

    Queries by clientId so Keycloak does the matching, rather than listing every client and
    filtering client-side.
    """
    response = requests.get(
        f"{settings.keycloak_url}/admin/realms/{realm}/clients",
        params={"clientId": client_name},
        headers={'Authorization': f'Bearer {admin_token}'}
    )
    is_response_good(response)
    clients = response.json()
    if not clients:
        logger.error(f"Client '{client_name}' not found in realm {realm}")
        exit(1)
    return clients[0]["id"]


def set_global_client_secret(admin_token:str):
    """
    Push KEYCLOAK_SECRET onto the `global` client.

    GET-modify-PUT rather than a bare PUT, so fields this code does not know about are preserved.
    Idempotent: re-applying an unchanged secret is a no-op.
    """
    if not settings.keycloak_secret:
        logger.warning("KEYCLOAK_SECRET is not set, skipping global client secret sync")
        return

    logger.info("Syncing the global client secret")
    client_id = get_client_uuid('global', admin_token)
    headers = {
        'Content-Type': 'application/json',
        'Authorization': f'Bearer {admin_token}'
    }

    client_resp = requests.get(
        f"{settings.keycloak_url}/admin/realms/{settings.keycloak_realm}/clients/{client_id}",
        headers=headers
    )
    is_response_good(client_resp)

    client_properties = client_resp.json()
    if client_properties.get("secret") == settings.keycloak_secret:
        logger.info("Global client secret already up to date")
        return

    client_properties["secret"] = settings.keycloak_secret
    put_resp = requests.put(
        f"{settings.keycloak_url}/admin/realms/{settings.keycloak_realm}/clients/{client_id}",
        json=client_properties,
        headers=headers
    )
    is_response_good(put_resp)
    logger.info("Global client secret updated")


def set_token_exchange_for_global_client(admin_token:str):
    logger.info("Setting up the token exchange for global client")
    all_clients = requests.get(
        f"{settings.keycloak_url}/admin/realms/{settings.keycloak_realm}/clients",
        headers={
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
        headers={
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
        headers={
            'Authorization': f'Bearer {admin_token}'
        }
    )
    is_response_good(client_te_scope_resp)
    token_exch_scope = client_te_scope_resp.json()[0]["id"]

    logger.info("Fetching the global resource reference")
    # Fetching the global resource reference in the realm-management client
    resource_scope_resp = requests.get(
        f"{settings.keycloak_url}/admin/realms/{settings.keycloak_realm}/clients/{rm_client_id}/authz/resource-server/resource?name=client.resource.{client_id}",
        headers={
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
        headers={
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {admin_token}'
        }
    )
    if global_client_policy_resp.status_code == 409:
        global_client_policy_resp = requests.get(
            f"{settings.keycloak_url}/admin/realms/{settings.keycloak_realm}/clients/{rm_client_id}/authz/resource-server/policy/client?name=token-exchange-global",
            headers={
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
        headers={
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
        headers={
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
    is_response_good(user_profiles_resp)

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
    is_response_good(user_edit_profiles_resp)

def enable_user_profile_at_realm_level(admin_token:str):
    # Enable user profiles on a realm level
    realm_settings = requests.get(
        f"{settings.keycloak_url}/admin/realms/{settings.keycloak_realm}",
        headers={'Authorization': f'Bearer {admin_token}'}
    )
    is_response_good(realm_settings)

    r_settings = realm_settings.json()
    r_settings["attributes"]["userProfileEnabled"] = True

    update_settings = requests.put(
        f"{settings.keycloak_url}/admin/realms/{settings.keycloak_realm}",
        json=r_settings,
        headers={'Authorization': f'Bearer {admin_token}'}
    )
    is_response_good(update_settings)

def delete_bootstrap_user(admin_token:str):
    # Delete temp admin user
    logger.info("Deleting temp user")
    # Sweep every bootstrap user rather than only the one this run was configured with.
    #
    # The username is generation-scoped (tmpadmin-<n>), so a run that failed part-way through can
    # leave an older one behind. Those are privileged master-realm accounts, so leaving them is a
    # real security problem, and a leftover matching a future generation would also block
    # `kc.sh bootstrap-admin user` and wedge that rotation.
    #
    # Queried by prefix -- Keycloak's `username` search is an infix match by default, which is
    # exactly what is wanted here (unlike the exact lookups elsewhere).
    user_id_resp = requests.get(
        f"{settings.keycloak_url}/admin/realms/master/users",
        params={"username": BOOTSTRAP_USER_PREFIX, "max": 1000},
        headers={'Authorization': f'Bearer {admin_token}'}
    )
    is_response_good(user_id_resp)

    candidates = [
        user for user in user_id_resp.json()
        if user.get("username", "").startswith(BOOTSTRAP_USER_PREFIX)
    ]
    if not candidates:
        # Only reachable if something else removed them between the login and this call
        logger.info("No bootstrap users present, nothing to delete")
        return

    for user in candidates:
        logger.info(f"Deleting bootstrap user '{user['username']}'")
        user_delete_resp = requests.delete(
            f"{settings.keycloak_url}/admin/realms/master/users/{user['id']}",
            headers={'Authorization': f'Bearer {admin_token}'}
        )
        is_response_good(user_delete_resp)


def create_system_user(
        username: str,
        password: str,
        email: str = "",
        admin_token: str = None, # type: ignore
        realm: str = settings.keycloak_realm
    ) -> str:
    """
    Create a system service account user with the System role.
    These are used for services like Dagster that need to authenticate
    and perform privileged operations.
    """
    if not admin_token:
        admin_token = login(
            settings.keycloak_url,
            settings.keycloak_admin,
            settings.keycloak_admin_password
        )

    if not admin_token:
        logger.error("Failed to get admin token for system user creation")
        exit(1)

    logger.info(f"Creating system user: {username}")

    user_id = create_user(
        username=username,
        password=password,
        email=email or f"{username}@phems.local",
        first_name="System",
        last_name="Account",
        role_name="System",
        with_role=True,
        admin_token=admin_token,
        realm=realm,
        # System accounts are platform-owned, so their password must follow kc-secrets on a
        # deliberate rotation rather than being left stale in Keycloak.
        reset_password_if_exists=True
    )

    logger.info(f"System user {username} created successfully with System role")
    return user_id


##############################################################################
# Realm configuration convergence
#
# realms.json is only ever applied by `kc.sh start --import-realm`, which SKIPS a realm that
# already exists (Keycloak logs "Strategy: IGNORE_EXISTING"). So on any existing deployment,
# editing realms.json has no effect whatsoever. These helpers are what make it converge.
#
# Two complementary mechanisms:
#
#   partial_import()  -- additive. New top-level roles, groups, clients and identity providers in
#                        realms.json land automatically, with no code change.
#   run_migrations()  -- mutating. Anything that must CHANGE something already present, which
#                        partial_import deliberately will not do.
#
# The split matters because `ifResourceExists: SKIP` is what protects operator-made configuration
# (an external IdP added through the console, extra clients, realm settings) from being reverted on
# every upgrade. It is never OVERWRITE.
##############################################################################

REALM_VERSION_ATTRIBUTE = "fn_realm_version"


def get_realm(admin_token:str) -> dict:
    response = requests.get(
        f"{settings.keycloak_url}/admin/realms/{settings.keycloak_realm}",
        headers={'Authorization': f'Bearer {admin_token}'}
    )
    is_response_good(response)
    return response.json()


def update_realm(realm_representation:dict, admin_token:str):
    """
    PUT a realm representation back.

    Always pass a representation obtained from get_realm() and modified, never one built from
    scratch: a partial PUT drops fields the platform does not know about, which would silently
    revert operator configuration.
    """
    response = requests.put(
        f"{settings.keycloak_url}/admin/realms/{settings.keycloak_realm}",
        json=realm_representation,
        headers={
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {admin_token}'
        }
    )
    is_response_good(response)


def get_realm_version(admin_token:str) -> int:
    """
    Which migrations have already been applied.

    Stored as a realm attribute rather than a Kubernetes ConfigMap or annotation because
    realm-init's Role is read-only (get/watch/list on pods and statefulsets), so a Kubernetes-side
    marker would require granting it write access.
    """
    attributes = get_realm(admin_token).get("attributes") or {}
    raw = attributes.get(REALM_VERSION_ATTRIBUTE)
    if raw in (None, ""):
        return 0
    try:
        return int(raw)
    except (TypeError, ValueError):
        logger.warning(f"Unparseable {REALM_VERSION_ATTRIBUTE}={raw!r}, treating as 0")
        return 0


def set_realm_version(version:int, admin_token:str):
    realm = get_realm(admin_token)
    attributes = realm.get("attributes") or {}
    attributes[REALM_VERSION_ATTRIBUTE] = str(version)
    realm["attributes"] = attributes
    update_realm(realm, admin_token)
    logger.info(f"Realm migration version is now {version}")


def _substitute_placeholders(raw:str) -> str:
    """
    realms.json carries ${KEYCLOAK_SECRET}, ${KEYCLOAK_TOKEN_LIFE} and ${KEYCLOAK_HOSTNAME}.
    Keycloak substitutes those itself when importing the file at startup, but the admin REST API
    does not, so it has to be done here before POSTing.
    """
    replacements = {
        "${KEYCLOAK_SECRET}": settings.keycloak_secret,
        "${KEYCLOAK_TOKEN_LIFE}": os.getenv("KEYCLOAK_TOKEN_LIFE", "2592000"),
        "${KEYCLOAK_HOSTNAME}": os.getenv("KEYCLOAK_HOSTNAME", ""),
    }
    for placeholder, value in replacements.items():
        raw = raw.replace(placeholder, value)
    return raw


def partial_import(admin_token:str, realm_file:str="/realm-config/realms.json"):
    """
    Apply additive realms.json changes to an existing realm.

    ifResourceExists=SKIP: existing resources are left exactly as they are, and anything not
    mentioned in realms.json is never touched. That is what makes it safe to run on every
    invocation without reverting configuration an operator made through the console.

    Note what this does NOT reach: the `global` client already exists, so SKIP skips it wholesale,
    and everything inside its authorizationSettings (the can_* authz scopes, the role policies and
    the scope permissions) is therefore NOT applied from realms.json. Adding a new authz scope
    needs a new migration in the migrations package, not just a realms.json edit.
    """
    if not os.path.exists(realm_file):
        logger.info(f"{realm_file} not mounted, skipping partial import")
        return

    with open(realm_file, encoding="utf-8") as handle:
        realm_definition = json.loads(_substitute_placeholders(handle.read()))

    # Only the collections partialImport accepts. Realm-level settings are deliberately excluded:
    # replaying those on every run would revert operator changes to session lifetimes, login
    # theme, brute-force detection and -- the one that breaks external IdP setups --
    # firstBrokerLoginFlow. Those belong in a run-once migration.
    payload = {"ifResourceExists": "SKIP"}
    for collection in ("roles", "groups", "clients", "identityProviders"):
        if realm_definition.get(collection):
            payload[collection] = realm_definition[collection]

    if len(payload) == 1:
        logger.info("Nothing to partial-import")
        return

    logger.info(f"Applying partial import for: {', '.join(k for k in payload if k != 'ifResourceExists')}")
    response = requests.post(
        f"{settings.keycloak_url}/admin/realms/{settings.keycloak_realm}/partialImport",
        json=payload,
        headers={
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {admin_token}'
        }
    )
    is_response_good(response)
    if response.ok:
        result = response.json()
        logger.info(
            f"Partial import: {result.get('added', 0)} added, "
            f"{result.get('skipped', 0)} skipped, {result.get('overwritten', 0)} overwritten"
        )


# Client-policy names the platform owns. Kept distinct so a GET-modify-PUT can replace just these
# entries and leave any operator-defined profiles and policies alone.
SECRET_ROTATION_PROFILE = "fn-client-secret-rotation"
SECRET_ROTATION_POLICY = "fn-client-secret-rotation-policy"


def set_client_secret_rotation_policy(
        admin_token:str,
        expiration_period:int=7776000,
        rotated_expiration_period:int=43200,
        remaining_rotation_period:int=604800):
    """
    Configure Keycloak's client secret rotation so that regenerating the `global` client secret
    keeps the PREVIOUS secret valid for a grace period. This is what makes rotation a no-downtime
    operation; without it every pod holding the old secret fails until it picks up the new one.

    Requires the `client-secret-rotation` feature, which is off by default in Keycloak -- otherwise
    the `secret-rotation` executor is not registered and Keycloak rejects the profile. It is enabled
    in build/keycloak/kc-features.txt.

    Property names are Keycloak's own; note `remaining-rotation-period`, not
    `remain-expiration-period`, which 500s with a NullPointerException.

    Both endpoints replace the whole list, so this reads the current state and substitutes only the
    platform's own entries.
    """
    logger.info("Configuring the client secret rotation policy")
    headers = {
        'Content-Type': 'application/json',
        'Authorization': f'Bearer {admin_token}'
    }
    base = f"{settings.keycloak_url}/admin/realms/{settings.keycloak_realm}/client-policies"

    profiles_resp = requests.get(f"{base}/profiles", headers=headers)
    is_response_good(profiles_resp)
    # globalProfiles are Keycloak's own built-ins and are read-only; PUT accepts only `profiles`.
    profiles = [
        profile for profile in (profiles_resp.json().get("profiles") or [])
        if profile.get("name") != SECRET_ROTATION_PROFILE
    ]
    profiles.append({
        "name": SECRET_ROTATION_PROFILE,
        "description": "Managed by the Federated Node. Gives rotated client secrets a grace period.",
        "executors": [
            {
                "executor": "secret-rotation",
                "configuration": {
                    "expiration-period": str(expiration_period),
                    "rotated-expiration-period": str(rotated_expiration_period),
                    "remaining-rotation-period": str(remaining_rotation_period)
                }
            }
        ]
    })
    put_profiles = requests.put(f"{base}/profiles", json={"profiles": profiles}, headers=headers)
    is_response_good(put_profiles)

    policies_resp = requests.get(f"{base}/policies", headers=headers)
    is_response_good(policies_resp)
    policies = [
        policy for policy in (policies_resp.json().get("policies") or [])
        if policy.get("name") != SECRET_ROTATION_POLICY
    ]
    policies.append({
        "name": SECRET_ROTATION_POLICY,
        "description": "Managed by the Federated Node. Applies secret rotation to the global client.",
        "enabled": True,
        # Scoped to confidential clients, which is what `global` is. Keycloak's own documented
        # example for secret rotation uses this condition.
        #
        # Deliberately NOT client-updater-context: its only valid values are ByAuthenticatedUser,
        # ByAnonymous, ByInitialAccessToken and ByRegistrationAccessToken -- there is no "admin API"
        # option, so it does not express what is wanted here.
        "conditions": [
            {
                "condition": "client-access-type",
                "configuration": {"type": ["confidential"]}
            }
        ],
        "profiles": [SECRET_ROTATION_PROFILE]
    })
    put_policies = requests.put(f"{base}/policies", json={"policies": policies}, headers=headers)
    is_response_good(put_policies)
    logger.info("Client secret rotation policy applied")


def rotate_client_secret(admin_token:str, client_name:str='global') -> str:
    """
    Ask Keycloak to generate a new secret for a client, and return it.

    Keycloak generates the value rather than the chart supplying one, because that is what engages
    the rotation policy above and keeps the previous secret alive for its grace period. The caller
    is responsible for writing the returned value into Kubernetes.
    """
    client_id = get_client_uuid(client_name, admin_token)
    logger.info(f"Rotating the '{client_name}' client secret")
    response = requests.post(
        f"{settings.keycloak_url}/admin/realms/{settings.keycloak_realm}/clients/{client_id}/client-secret",
        headers={'Authorization': f'Bearer {admin_token}'}
    )
    is_response_good(response)
    new_secret = response.json().get("value")
    if not new_secret:
        logger.error("Keycloak did not return a new client secret")
        exit(1)
    return new_secret


def reset_user_password(username:str, password:str, admin_token:str,
                        realm:str=settings.keycloak_realm):
    """
    Reset an existing user's password. Used by the rotation job.

    Unlike a client secret, Keycloak has no dual-password concept, so this takes effect
    immediately and consumers must retry on auth failure after re-reading their credential.
    """
    response = requests.get(
        f"{settings.keycloak_url}/admin/realms/{realm}/users",
        params={"username": username, "exact": "true"},
        headers={'Authorization': f'Bearer {admin_token}'}
    )
    is_response_good(response)
    users = response.json()
    if not users:
        logger.error(f"User '{username}' not found in realm {realm}, cannot reset password")
        exit(1)

    logger.info(f"Resetting password for '{username}'")
    reset = requests.put(
        f"{settings.keycloak_url}/admin/realms/{realm}/users/{users[0]['id']}/reset-password",
        json={"type": "password", "temporary": False, "value": password},
        headers={
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {admin_token}'
        }
    )
    is_response_good(reset)
