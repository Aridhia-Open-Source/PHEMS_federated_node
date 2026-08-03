import subprocess
import base64
import re


def get_k8s_secret(secret_name: str, namespace: str, key: str) -> str:
    """Fetch a secret value from Kubernetes."""
    result = subprocess.run(
        ["kubectl", "get", "secret", secret_name, f"-n{namespace}",
            "-o", f"jsonpath={{.data.{key}}}"],
        capture_output=True,
        text=True,
        check=True,
    )
    return base64.b64decode(result.stdout).decode()


def load_dataset_secret(dataset_name: str, host: str):
    """Check if dataset K8s secret exists and return credentials."""
    cleaned_host = re.sub('http(s)*://', '', host)
    secret_name = f"{cleaned_host}-{re.sub('\\s|_|#', '-', dataset_name.lower())}-creds"

    user = get_k8s_secret(secret_name, "fn", "PGUSER")
    password = get_k8s_secret(secret_name, "fn", "PGPASSWORD")
    return {'username': user, 'password': password}


def load_dagster_system_creds():
    """Load system user credentials from K8s secret or .env."""
    user = get_k8s_secret("dagster-keycloak-creds", "keycloak", "DAGSTER_KC_USER")
    password = get_k8s_secret("dagster-keycloak-creds", "keycloak", "DAGSTER_KC_PASSWORD")
    return {'username': user, 'password': password}
