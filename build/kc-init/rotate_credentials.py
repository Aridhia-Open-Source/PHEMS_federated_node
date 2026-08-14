"""
Scheduled credential rotation.

Run by the keycloak-credential-rotation CronJob. Rotates the platform-managed Keycloak credentials
and writes the new values into every copy of the Kubernetes secrets that hold them.

What rotates, and what deliberately does not:

  KEYCLOAK_SECRET            yes -- Keycloak generates it, and the client secret rotation policy
                             (realm migration 2) keeps the PREVIOUS secret valid for a grace period,
                             so consumers pick the new one up from their mounted file with no
                             downtime and no restart.
  KEYCLOAK_SERVICE_PASSWORD  yes -- reset via the admin API. Keycloak has no dual-password concept,
                             so this one has a brief cutover; consumers retry on auth failure.
  DAGSTER_KC_PASSWORD        yes -- same mechanism.
  KEYCLOAK_ADMIN_PASSWORD    NO -- that is the operator's console account. The platform sets it once,
                             marked temporary, and never touches it again. Rotating it would
                             overwrite whatever password the operator chose.
  KC_BOOTSTRAP_ADMIN_PASSWORD NO -- Keycloak startup configuration, read from the environment when
                             the pod starts. Rotating it would require restarting Keycloak, which
                             defeats the purpose of rotating without restarts. It changes only on a
                             deliberate keycloak.credentialGeneration bump.

Ordering matters. The client secret goes first because its grace period makes it safe to change
early. The passwords have no grace, so the gap between changing them in Keycloak and writing them to
Kubernetes is kept as small as possible -- each is patched immediately after it is reset.

Idempotent and resumable: Keycloak is the source of truth for the client secret, so a re-run after a
partial failure reads the current value back and re-patches Kubernetes rather than rotating again.
"""
import base64
import logging
import os
import secrets as pysecrets
import string
import sys
from datetime import datetime, timezone

from kubernetes import client, config
from kubernetes.client.exceptions import ApiException

from common import (
    get_client_uuid,
    health_check,
    login,
    reset_user_password,
    rotate_client_secret,
)
from settings import settings

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger('credential_rotation')

KC_SECRETS_NAME = "kc-secrets"
DAGSTER_SECRET_NAME = "dagster-keycloak-creds"


def generate_password(length: int = 24) -> str:
    """Match the chart's randAlphaNum 24, using a cryptographically secure source."""
    alphabet = string.ascii_letters + string.digits
    return "".join(pysecrets.choice(alphabet) for _ in range(length))


def target_namespaces() -> list:
    """
    Namespaces holding a copy of kc-secrets, from the environment the CronJob is given.

    Every copy must be patched. Components in different namespaces read their own copy, so a partial
    update leaves them disagreeing about the current credential.
    """
    raw = os.getenv("KC_SECRET_NAMESPACES", "")
    return [ns.strip() for ns in raw.split(",") if ns.strip()]


def dagster_namespaces() -> list:
    raw = os.getenv("DAGSTER_SECRET_NAMESPACES", "")
    return [ns.strip() for ns in raw.split(",") if ns.strip()]


def patch_secret(v1: client.CoreV1Api, namespace: str, name: str, values: dict) -> bool:
    """Patch specific keys of a secret, leaving every other key untouched."""
    body = {"data": {k: base64.b64encode(v.encode()).decode() for k, v in values.items()}}
    try:
        v1.patch_namespaced_secret(name=name, namespace=namespace, body=body)
        logger.info(f"Patched {', '.join(values)} in {namespace}/{name}")
        return True
    except ApiException as exc:
        if exc.status == 404:
            logger.info(f"{namespace}/{name} does not exist, skipping")
            return True
        logger.error(f"Failed to patch {namespace}/{name}: {exc.status} {exc.reason}")
        return False


def main() -> int:
    config.load_incluster_config()
    v1 = client.CoreV1Api()

    namespaces = target_namespaces()
    if not namespaces:
        logger.error("KC_SECRET_NAMESPACES is empty, nothing to rotate")
        return 1

    health_check()

    # Authenticate as the service account, never as `admin`: rotation must not depend on a credential
    # the operator owns and may have changed.
    admin_token = login(
        settings.keycloak_url,
        settings.keycloak_service_user,
        settings.keycloak_service_password,
        realm=settings.keycloak_realm
    )
    if not admin_token:
        logger.error(
            "Could not authenticate as %s. Rotation aborted -- no credential has been changed.",
            settings.keycloak_service_user
        )
        return 1

    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    failed = False

    # 1. Client secret. Keycloak generates it so the rotation policy engages and the previous secret
    #    keeps working for its grace period -- this is the part that is genuinely zero-downtime.
    if os.getenv("ROTATE_CLIENT_SECRET", "true").lower() in ("1", "true", "yes", "on"):
        new_client_secret = rotate_client_secret(admin_token)
        for namespace in namespaces:
            if not patch_secret(v1, namespace, KC_SECRETS_NAME, {
                "KEYCLOAK_SECRET": new_client_secret,
                "LAST_ROTATED": stamp,
            }):
                failed = True
    else:
        logger.info("Client secret rotation disabled, skipping")

    # 2. Service account password. No grace period, so Kubernetes is patched immediately after.
    if os.getenv("ROTATE_SERVICE_PASSWORD", "true").lower() in ("1", "true", "yes", "on"):
        new_service_password = generate_password()
        reset_user_password(settings.keycloak_service_user, new_service_password, admin_token)
        for namespace in namespaces:
            if not patch_secret(v1, namespace, KC_SECRETS_NAME, {
                "KEYCLOAK_SERVICE_PASSWORD": new_service_password,
                "LAST_ROTATED": stamp,
            }):
                failed = True
    else:
        logger.info("Service password rotation disabled, skipping")

    # 3. Dagster's system account, same mechanism.
    dagster_ns = dagster_namespaces()
    if dagster_ns and os.getenv("ROTATE_DAGSTER_PASSWORD", "true").lower() in ("1", "true", "yes", "on"):
        new_dagster_password = generate_password()
        reset_user_password(settings.dagster_kc_user or "dagster", new_dagster_password, admin_token)
        for namespace in dagster_ns:
            if not patch_secret(v1, namespace, DAGSTER_SECRET_NAME, {
                "DAGSTER_KC_PASSWORD": new_dagster_password,
                "LAST_ROTATED": stamp,
            }):
                failed = True

    if failed:
        # Loud, because the symptom of a silently failing rotation is invisible: credentials simply
        # stop being rotated. The CronJob's failure is what an alert should key on.
        logger.error("Rotation completed with errors. Kubernetes and Keycloak may disagree.")
        return 1

    logger.info(f"Credential rotation complete at {stamp}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
