# This file acts as a Keycloak settings Migration file
# Basically all the changes in the realms.json will not be
# applied on existing realms, so we need a way to apply
# those changes, hence this file

import logging
import requests
from kubernetes import client
from kubernetes.watch import Watch
from kubernetes.client.exceptions import ApiException

from common import (
  create_user, delete_bootstrap_user,
  enable_user_profile_at_realm_level, init_k8s,
  login, health_check, set_token_exchange_for_global_client,
  set_users_required_fields
)
from settings import settings

logger = logging.getLogger('realm_init')
logger.setLevel(logging.INFO)

init_k8s()

while True:
  watcher = Watch()
  for kc_stat_set in watcher.stream(
    client.AppsV1Api().list_namespaced_stateful_set,
    settings.keycloak_namespace,
    label_selector="app=keycloak"
  ):
    try:
      logger.info("%s out of %s ready.", kc_stat_set["object"].status.ready_replicas, settings.max_replicas)
      if kc_stat_set["object"].status.ready_replicas != settings.max_replicas:
        logger.info("%s out of %s ready. Waiting..", kc_stat_set["object"].status.ready_replicas, settings.max_replicas)
        continue

      # Double check the pods, as the ready replicas do include the termminating ones
      pods = client.CoreV1Api().list_namespaced_pod(
        settings.keycloak_namespace,
        label_selector="app=keycloak"
      )
      if len([pod.metadata.deletion_timestamp for pod in pods.items if pod.metadata.deletion_timestamp is None]) != settings.max_replicas:
        logger.info("One of the expected replicas is being terminated. Waiting..")
        continue

      health_check()

      logger.info(f"Accessing to keycloak {settings.realm} realm")

      admin_token = login(settings.keycloak_url, settings.kc_bootstrap_admin_username, settings.kc_bootstrap_admin_password)

      logger.info("Got the token...Creating user in new Realm")

      headers = {
        'Cache-Control': 'no-cache',
        'Content-Type': 'application/json',
        'Authorization': f'Bearer {admin_token}'
      }

      # Create backend user
      create_user(
        settings.keycloak_admin,
        settings.keycloak_admin_password,
        email="admin@federatednode.com",
        admin_token=admin_token,
        realm="master", with_role=False
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
    except ApiException as apie:
      logger.error(apie)
    except requests.exceptions.ConnectionError as ce:
      logger.error(ce)
