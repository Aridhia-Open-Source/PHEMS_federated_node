# This file acts as a Keycloak settings Migration file
# Basically all the changes in the realms.json will not be
# applied on existing realms, so we need a way to apply
# those changes, hence this file

import os
import logging
import requests
from requests.exceptions import ConnectionError

from kubernetes import client
from kubernetes import config
from kubernetes.watch import Watch
from kubernetes.client.exceptions import ApiException

from common import (
    create_user, delete_bootstrap_user,
    login, health_check, set_token_exchange_for_global_client,
    setup_master_user, create_system_user,
    set_global_client_secret, partial_import
)
from migrations import run_migrations
from settings import settings

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger('realm_init')


def init_k8s():
    if os.getenv('KUBERNETES_SERVICE_HOST'):
        # Get configuration for an in-cluster setup
        config.load_incluster_config()
    elif os.path.exists(config.KUBE_CONFIG_DEFAULT_LOCATION):
        # Get config from outside the cluster. Mostly DEV
        config.load_kube_config()
    else:
        setup_keycloak()
        exit(0)


def authenticate():
    """
    Get an admin token, returning (token, used_bootstrap).

    Order matters. The durable service account is tried FIRST, and this is the change that makes
    realm migrations work at all.

    """
    if settings.keycloak_service_password:
        token = login(
            settings.keycloak_url,
            settings.keycloak_service_user,
            settings.keycloak_service_password,
            realm=settings.keycloak_realm,
            # Expected on a first install (the account does not exist yet) and immediately after a
            # credential rotation (its stored password is now stale), so it must not log as an error.
            expected_to_fail=True
        )
        if token:
            return token, False
        logger.info("Service account unavailable, falling back to the bootstrap user")

    # The bootstrap user is a master-realm admin, so it can do the things fn-service deliberately
    # cannot: create the master admin account and repair fn-service's own password.
    token = login(
        settings.keycloak_url,
        settings.kc_bootstrap_admin_username,
        settings.kc_bootstrap_admin_password,
        realm="master"
    )
    return token, True


def bootstrap_platform_accounts(admin_token:str):
    """
    Runs only when authenticated as the bootstrap user: first install, or a credential rotation.

    Everything here either needs master-realm access or is the thing that repairs fn-service, so it
    cannot run under fn-service itself.
    """
    # The operator's Keycloak console account.
    #
    # temporary=True so Keycloak forces a password change at first login, and deliberately NOT
    # reset_password_if_exists: once an operator has set their own password, the platform must never
    # overwrite it.
    master_admin_id = create_user(
        settings.keycloak_admin,
        settings.keycloak_admin_password,
        email="admin@federatednode.com",
        admin_token=admin_token,
        realm="master", with_role=False,
        temporary=True
    )
    setup_master_user(
        master_admin_id, admin_token, ["admin", "create-realm"]
    )

    # The platform's service account
    #
    # Scoped to the FederatedNode realm only: it has no master-realm access, so a compromise cannot
    # reach the Keycloak server configuration or any other realm.
    logger.info(f"Ensuring the {settings.keycloak_service_user} service account")
    create_user(
        settings.keycloak_service_user,
        settings.keycloak_service_password,
        email="fn-service@federatednode.com",
        first_name="Federated Node",
        last_name="Service",
        admin_token=admin_token,
        reset_password_if_exists=True
    )

    # Only asserted on this path, i.e. on a first install or a deliberate generation bump.
    set_global_client_secret(admin_token)


def ensure_realm_accounts(admin_token:str):
    """
    Accounts inside the FederatedNode realm. Runs under either credential, since fn-service has
    Super Administrator and can manage realm users.
    """
    # Create first user, if chosen to do so. Create-only: this is a human's account, so its password
    # must never be reset from the chart.
    if settings.first_user_email:
        create_user(
            settings.first_user_email, settings.first_user_pass,
            settings.first_user_email, settings.first_user_first_name,
            settings.first_user_last_name, "Administrator",
            admin_token=admin_token
        )

    # Create Dagster system user for all Dagster operations, if credentials provided
    if settings.dagster_kc_user and settings.dagster_kc_password and settings.dagster_kc_email:
        logger.info("Creating Dagster system user")
        create_system_user(
            username=settings.dagster_kc_user,
            password=settings.dagster_kc_password,
            email=settings.dagster_kc_email,
            admin_token=admin_token
        )


def setup_keycloak():
    logger.info("Setting up Keycloak")

    admin_token, used_bootstrap = authenticate()
    if not admin_token:
        logger.error(
            "Could not authenticate with either the service account or the bootstrap user. "
            "The bootstrap user only exists just after a Keycloak pod start, so if the service "
            "account's password no longer matches Keycloak, recover with: "
            "kubectl rollout restart statefulset/keycloak -n %s",
            settings.keycloak_namespace or "<keycloak namespace>"
        )
        return

    if used_bootstrap:
        bootstrap_platform_accounts(admin_token)

    ensure_realm_accounts(admin_token)

    if settings.manage_realm:
        # Additive realms.json changes, then anything that must mutate existing configuration.
        partial_import(admin_token)
        run_migrations(admin_token)
        set_token_exchange_for_global_client(admin_token)
    else:
        logger.info("keycloak.manageRealm is false, skipping realm configuration")

    if used_bootstrap:
        # Always last: this is the credential the run authenticated with.
        delete_bootstrap_user(admin_token)

    logger.info("Done!")


init_k8s()
logger.info("Running realm setup at startup")
health_check()
setup_keycloak()


while True:
    watcher = Watch()
    for kc_pod in watcher.stream(
        client.CoreV1Api().list_namespaced_pod,
        settings.keycloak_namespace,
        label_selector="app=keycloak"
    ):
        try:
            # Double check the pods, as the ready replicas do include the terminating ones
            pods = client.CoreV1Api().list_namespaced_pod(
                settings.keycloak_namespace,
                label_selector="app=keycloak"
            )
            readiness = []
            # Ready state is not reliable, we will check all of the replicas and
            # make sure they are ready
            for pod in pods.items:
                readiness += [condi for condi in pod.status.conditions if condi.type == "Ready" and condi.status == "True"]

            if len(readiness) < settings.kc_replicas:
                logger.info("One of the expected replicas is being terminated. Waiting..")
                continue

            logging.info("All pods ready! Performing health check")
            health_check()
            logging.info("Setting up credentials")
            setup_keycloak()

        except (ApiException, ConnectionError) as e:
            logger.error(e)
