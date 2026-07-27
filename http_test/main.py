#!/usr/bin/env python

"""Backend API client example."""

import logging
import subprocess
import base64

from clients import BackendSession, BackendAdapter, BackendAPI

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def _load_creds():
    """Load credentials from K8s secret."""
    user = _get_k8s_secret("dagster-keycloak-creds", "keycloak", "DAGSTER_KC_USER")
    password = _get_k8s_secret("dagster-keycloak-creds", "keycloak", "DAGSTER_KC_PASSWORD")
    if not user or not password:
        raise ValueError("Could not load credentials from K8s")
    return {'username': user, 'password': password}


def _get_k8s_secret(secret_name: str, namespace: str, key: str) -> str:
    """Fetch a secret value from Kubernetes."""
    result = subprocess.run(
        ["kubectl", "get", "secret", secret_name, f"-n{namespace}",
            "-o", f"jsonpath={{.data.{key}}}"],
        capture_output=True,
        text=True,
        check=True,
    )
    return base64.b64decode(result.stdout).decode()


def main():
    backend_url = "http://localhost:5000"

    creds = _load_creds()
    print(creds)

    adapter = BackendAdapter(
        base_url=backend_url,
        username=creds['username'],
        password=creds['password'],
    )
    session = BackendSession(adapter)
    api = BackendAPI(session)
    repos = api.get_repositories() or []

    for repo in repos:
        logger.info(repo.path)


if __name__ == "__main__":
    main()
