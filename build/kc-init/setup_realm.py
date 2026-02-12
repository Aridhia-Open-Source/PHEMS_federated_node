# This file acts as a Keycloak settings Migration file
# Basically all the changes in the realms.json will not be
# applied on existing realms, so we need a way to apply
# those changes, hence this file
import os
import logging
import requests
from kubernetes import client
from kubernetes import config
from kubernetes.watch import Watch
from kubernetes.client.exceptions import ApiException

from common import (
  create_user, delete_bootstrap_user,
  enable_user_profile_at_realm_level,
  login, health_check, set_token_exchange_for_global_client,
  set_users_required_fields, setup_master_user
)
from settings import settings

logger = logging.getLogger('realm_init')
logger.setLevel(logging.INFO)
handler = logging.StreamHandler()
logger.addHandler(handler)

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


def setup_keycloak():
  logger.info(f"Accessing to keycloak {settings.realm} realm")

  admin_token = login(settings.keycloak_url, settings.kc_bootstrap_admin_username, settings.kc_bootstrap_admin_password)
  if not admin_token:
    logging.info("Skipping")
    return

  logger.info("Got the token...Creating user in new Realm")

  # Create backend user
  master_admin_id = create_user(
    settings.keycloak_admin,
    settings.keycloak_admin_password,
    email="admin@federatednode.com",
    admin_token=admin_token,
    realm="master", with_role=False
  )
  setup_master_user(
    master_admin_id, admin_token, ["admin", "create-realm"]
  )
  create_user(
    settings.keycloak_admin,
    settings.keycloak_admin_password,
    email="admin@federatednode.com",
    admin_token=admin_token
  )
  # Create first user, if chosen to do so
  if settings.first_user_email:
    create_user(
      settings.first_user_email, settings.first_user_pass,
      settings.first_user_email, settings.first_user_first_name,
      settings.first_user_last_name, "Administrator",
      admin_token=admin_token
    )

  set_token_exchange_for_global_client(admin_token)

  set_users_required_fields(admin_token)

  enable_user_profile_at_realm_level(admin_token)

  delete_bootstrap_user(admin_token)

  logger.info("Done!")

init_k8s()

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

      # We expect only one event per pod to have Ready type and True status
      if len(readiness) != settings.kc_replicas:
        logger.info("One of the expected replicas is being terminated. Waiting..")
        continue

      logging.info("All pods ready! Performing health check")
      health_check()
      logging.info("Setting up credentials")
      setup_keycloak()

    except ApiException as apie:
      logger.error(apie)
    except requests.exceptions.ConnectionError as ce:
      logger.error(ce)
