"""
Kopf handlers: each custom resource of fn.aridhia.com/v1alpha1 -> its nexus-api record (ADR 0032).

create, update and resume call the kind's sync (sync.py); delete calls its delete without force, and a 409 keeps the
resource Terminating with nexus-api's reason in status until the delete goes through. No timer puts back API edits
yet. Only NodeSecrets have a timer, to see a rotated source Secret. Kopf keeps its own
state in annotations, so status holds only what the operator writes: synced, nexusId, message, observedGeneration.

Run with `kopf run -m nexus_operator.main --standalone --namespace <ns> ...` (the chart's Deployment).
"""

from functools import partial

import kopf
import requests
from kubernetes import client, config
from kubernetes.client.exceptions import ApiException

from nexus_client.api import BackendAPI
from nexus_client.http import BackendSession, PasswordFileAdapter
from nexus_operator import sync
from nexus_operator.settings import Settings

GROUP = "fn.aridhia.com"
VERSION = "v1alpha1"
FINALIZER = "fn.aridhia.com/nexus-sync"

env = Settings()


# Reads the mounted password at every login, so a credential rotation needs no restart. Shared by every handler
# thread: the adapter locks its token refresh.
api = BackendAPI(BackendSession(
    PasswordFileAdapter(base_url=env.nexus_api_url, username=env.user, password_file=env.password_file)
))


def read_secret(namespace: str, name: str) -> tuple[dict[str, str], str]:
    """
    A source Secret in the resource's own namespace (made by hand, SOPS or External Secrets): its decoded data and
    resourceVersion. No error carries a value: the ApiException body and the decode error are never chained.
    """
    try:
        secret = client.CoreV1Api().read_namespaced_secret(name, namespace)
    except ApiException as error:
        if error.status == 404:
            raise kopf.TemporaryError(f"waiting for Secret {name}") from None
        if error.status == 403:
            raise kopf.TemporaryError(
                f"may not read Secret {name}: add it to the chart's operator.sourceSecrets"
            ) from None
        raise kopf.TemporaryError(f"reading Secret {name}: {error.status} {error.reason}") from None
    return sync.decode_secret(name, secret.data), secret.metadata.resource_version


# plural -> (sync(api, name, spec), delete(api, name, spec)); a NodeSecret's sync also reads its source Secrets
KINDS = {
    "gitproviders": (sync.sync_provider, sync.delete_provider),
    "nodesecrets": (None, sync.delete_secret),
    "repositories": (sync.sync_repository, sync.delete_repository),
    "datasets": (sync.sync_dataset, sync.delete_dataset),
    "projects": (sync.sync_project, sync.delete_project),
}


def sync_one(plural, name, spec, namespace, status, meta) -> sync.Synced:
    if plural == "nodesecrets":
        spec_changed = meta.get("generation") != status.get("observedGeneration")
        return sync.sync_secret(
            api, name, spec, namespace, read_secret, status.get("sourceVersions") or {}, spec_changed,
        )
    if plural == "projects":
        return sync.sync_project(api, name, spec, status.get("enabled"))
    return KINDS[plural][0](api, name, spec)


@kopf.on.startup()
def configure(settings: kopf.OperatorSettings, **_):
    settings.persistence.finalizer = FINALIZER
    settings.persistence.progress_storage = kopf.AnnotationsProgressStorage(prefix=GROUP)
    settings.persistence.diffbase_storage = kopf.AnnotationsDiffBaseStorage(prefix=GROUP)
    settings.peering.standalone = True
    # The Role is per namespace, so kopf may not list namespaces or CRDs; without this it retries for ~50s at start
    settings.scanning.disabled = True
    config.load_config()


def describe(error: requests.HTTPError) -> str:
    return f"{error} - {error.response.text[:300]}"


def flux_annotations(meta) -> dict:
    """Who applied it: the Flux annotations on the resource, for the log and the Event"""
    return {key: value for key, value in meta.get("annotations", {}).items() if "fluxcd.io" in key}


def reconcile(plural, body, name, namespace, spec, status, meta, patch, logger, **_):
    """Sync one resource and write its status; a wait or an API error is retried after retry_delay_seconds"""
    try:
        result = sync_one(plural, name, spec, namespace, status, meta)
        access_changed, access = sync.sync_access(
            api, sync.record_path(plural, name, spec, result.nexus_id), spec.get("access", []),
            status.get("access") or [],
        )
    except kopf.TemporaryError as error:
        patch.status.update(synced=False, message=str(error))
        raise kopf.TemporaryError(str(error), delay=env.retry_delay_seconds) from error
    except requests.HTTPError as error:
        patch.status.update(synced=False, message=describe(error))
        raise kopf.TemporaryError(describe(error), delay=env.retry_delay_seconds) from error
    patch.status.update(
        synced=True, nexusId=result.nexus_id, message="", observedGeneration=meta.get("generation"), access=access,
        **result.status,
    )
    if result.changed or access_changed:
        attribution = flux_annotations(meta)
        logger.info(f"Synced {plural}/{name} to nexus-api {attribution}")
        kopf.info(body, reason="Synced", message=f"Synced to nexus-api {attribution}".strip())


def remove(plural, name, spec, patch, logger, **_):
    """Soft-delete the record, never forced: a 409 (still in use) keeps the resource Terminating and retries"""
    try:
        KINDS[plural][1](api, name, spec)
    except requests.HTTPError as error:
        patch.status.update(synced=False, message=describe(error))
        raise kopf.TemporaryError(describe(error), delay=env.retry_delay_seconds) from error
    logger.info(f"Deleted {plural}/{name} in nexus-api")


for kind in KINDS:
    handler = partial(reconcile, kind)
    kopf.on.create(GROUP, VERSION, kind, id="sync")(handler)
    kopf.on.update(GROUP, VERSION, kind, id="sync")(handler)
    kopf.on.resume(GROUP, VERSION, kind, id="sync")(handler)
    kopf.on.delete(GROUP, VERSION, kind, id="delete")(partial(remove, kind))
# A rotated source Secret changes no NodeSecret, so only a timer sees it. The first tick waits one interval, so it never
# races the create handler into a duplicate POST (409).
kopf.timer(
    GROUP, VERSION, "nodesecrets", id="resync", interval=env.sync_interval_seconds,
    initial_delay=env.sync_interval_seconds,
)(partial(reconcile, "nodesecrets"))
