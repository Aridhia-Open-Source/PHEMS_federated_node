"""
Kopf handlers: each custom resource of fn.aridhia.com/v1alpha1 -> its nexus-api record (ADR 0032).

create, update, resume and a timer call the kind's sync (sync.py); delete calls its delete without force, and a 409
keeps the resource Terminating with nexus-api's reason in status until the delete goes through. Kopf keeps its own
state in annotations, so status holds only what the operator writes: synced, nexusId, message, observedGeneration.

Run with `kopf run -m nexus_operator.main --standalone --namespace <ns> ...` (the chart's Deployment).
"""

import base64
from functools import partial

import kopf
import requests
from kubernetes import client, config
from kubernetes.client.exceptions import ApiException

from nexus_client.api import BackendAPI
from nexus_client.http import BackendAdapter, BackendSession
from nexus_operator import sync
from nexus_operator.settings import Settings

GROUP = "fn.aridhia.com"
VERSION = "v1alpha1"
FINALIZER = "fn.aridhia.com/nexus-sync"

env = Settings()
api = BackendAPI(BackendSession(BackendAdapter(base_url=env.nexus_api_url, username=env.user, password=env.password)))


def read_secret(namespace: str, name: str) -> tuple[dict[str, str], str]:
    """A source Secret in the resource's own namespace: its decoded data and resourceVersion"""
    try:
        secret = client.CoreV1Api().read_namespaced_secret(name, namespace)
    except ApiException as error:
        if error.status == 404:
            raise kopf.TemporaryError(f"waiting for Secret {name}") from error
        raise
    data = {key: base64.b64decode(value).decode() for key, value in (secret.data or {}).items()}
    return data, secret.metadata.resource_version


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
    return KINDS[plural][0](api, name, spec)


@kopf.on.startup()
def configure(settings: kopf.OperatorSettings, **_):
    settings.persistence.finalizer = FINALIZER
    settings.persistence.progress_storage = kopf.AnnotationsProgressStorage(prefix=GROUP)
    settings.persistence.diffbase_storage = kopf.AnnotationsDiffBaseStorage(prefix=GROUP)
    settings.peering.standalone = True
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
    except kopf.TemporaryError as error:
        patch.status.update(synced=False, message=str(error))
        raise kopf.TemporaryError(str(error), delay=env.retry_delay_seconds) from error
    except requests.HTTPError as error:
        patch.status.update(synced=False, message=describe(error))
        raise kopf.TemporaryError(describe(error), delay=env.retry_delay_seconds) from error
    patch.status.update(
        synced=True, nexusId=result.nexus_id, message="", observedGeneration=meta.get("generation"), **result.status,
    )
    if result.changed:
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
    kopf.timer(GROUP, VERSION, kind, id="resync", interval=env.sync_interval_seconds)(handler)
    kopf.on.delete(GROUP, VERSION, kind, id="delete")(partial(remove, kind))
