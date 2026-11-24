"""
The node config files in config/: fn.aridhia.com resources (ADR 0032) that kubectl applies and the nexus operator
syncs to nexus-api. fncli reads them (for `fncli gitea setup`), and applies, deletes and waits on them with kubectl
for `fncli experiment` and the e2e suites.
"""

import json
import subprocess
import time
from pathlib import Path

import click
import yaml

GROUP_VERSION = "fn.aridhia.com/v1alpha1"
SYNC_TIMEOUT = "180s"
SYNC_TIMEOUT_SECONDS = 180
POLL_SECONDS = 2


def files_of(paths: list[Path]) -> list[Path]:
    """The files given, a directory's *.yaml as kubectl -f takes it (not recursive)"""
    return [file for path in paths for file in (sorted(path.glob("*.yaml")) if path.is_dir() else [path])]


def load_resources(paths: list[Path]) -> list[dict]:
    """Every fn.aridhia.com resource in the files"""
    return [
        doc for file in files_of(paths) for doc in yaml.safe_load_all(file.read_text())
        if doc and doc["apiVersion"] == GROUP_VERSION
    ]


def of_kind(resources: list[dict], kind: str) -> list[dict]:
    return [resource for resource in resources if resource["kind"] == kind]


def kubectl(*args: str):
    """Run kubectl and exit with its status if it fails"""
    result = subprocess.run(["kubectl", *args])
    if result.returncode:
        raise click.exceptions.Exit(result.returncode)


def file_args(paths: list[Path]) -> list[str]:
    return [arg for path in paths for arg in ("-f", str(path))]


def apply(paths: list[Path]):
    kubectl("apply", *file_args(paths))


def delete(paths: list[Path]):
    """
    Delete the resources and wait until they are gone: the operator soft-deletes each in nexus-api first, and keeps one
    that nexus-api refuses Terminating with the reason in its status, so the wait times out on it
    """
    kubectl("delete", "--ignore-not-found", f"--timeout={SYNC_TIMEOUT}", *file_args(paths))


def synced(resource: dict) -> bool:
    """The operator has synced the resource as it is now: synced, and for this generation, not an earlier one"""
    status = resource.get("status") or {}
    return bool(status.get("synced")) and status.get("observedGeneration", 0) >= resource["metadata"]["generation"]


def get_resources(*targets: str) -> list[dict]:
    """The fn.aridhia.com resources kubectl gets for the targets, none while they are not there yet"""
    result = subprocess.run(["kubectl", "get", "-o", "json", *targets], capture_output=True, text=True)
    if result.returncode:
        return []
    doc = json.loads(result.stdout)
    return [item for item in doc.get("items", [doc]) if item["apiVersion"] == GROUP_VERSION]


def wait_synced(*targets: str):
    """
    Wait until the operator has synced every resource as it is now: targets as kubectl get takes them, the -f FILE
    pairs of file_args, or -n NAMESPACE and KIND/NAME. A re-applied resource still carries synced=true from its last
    generation, so observedGeneration has to catch up too.
    """
    deadline = time.monotonic() + SYNC_TIMEOUT_SECONDS
    while True:
        resources = get_resources(*targets)
        pending = [resource for resource in resources if not synced(resource)]
        if resources and not pending:
            return
        if time.monotonic() > deadline:
            raise click.ClickException("Not synced after {}s: {}".format(SYNC_TIMEOUT_SECONDS, ", ".join(
                f"{r['kind']}/{r['metadata']['name']} ({(r.get('status') or {}).get('message') or 'no status'})"
                for r in pending
            ) or "no resources found"))
        time.sleep(POLL_SECONDS)
