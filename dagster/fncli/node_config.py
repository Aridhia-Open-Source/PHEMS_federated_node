"""
The node config files in config/: fn.aridhia.com resources (ADR 0032) that kubectl applies and the nexus operator
syncs to nexus-api. fncli reads them (for `fncli gitea setup`), and applies, deletes and waits on them with kubectl
for `fncli experiment` and the e2e suites.
"""

import subprocess
from pathlib import Path

import click
import yaml

GROUP_VERSION = "fn.aridhia.com/v1alpha1"
SYNC_TIMEOUT = "180s"


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


def wait_synced(*targets: str):
    """
    Wait until the operator says every resource is synced to nexus-api: targets as kubectl wait takes them, the -f
    FILE pairs of file_args, or -n NAMESPACE and KIND/NAME
    """
    kubectl("wait", "--for=jsonpath={.status.synced}=true", f"--timeout={SYNC_TIMEOUT}", *targets)
