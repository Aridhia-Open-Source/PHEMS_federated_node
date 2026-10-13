"""
Credential reading, file-first.

Named secrets_reader rather than secrets: a local `secrets.py` shadows Python's standard-library
`secrets` module for every import in the process, which breaks dependencies that rely on it.

kc-secrets is mounted as a directory rather than injected via envFrom, because environment variables
are fixed when a container starts. Reading from the mounted files means a credential rotation reaches
long-running processes without restarting them, which is what makes automated rotation possible at
all -- restarts across several components cannot be synchronised, so there is always a window where
some pods hold the old credential and some the new.

Kubernetes updates a mounted secret within roughly two minutes (the kubelet sync period plus its
cache TTL), and only when the secret is mounted as a DIRECTORY. A `subPath` mount is never refreshed.

Falls back to the environment so docker-compose and local runs, which have no mount, keep working
unchanged.
"""
import logging
import os

logger = logging.getLogger('realm_secrets')

# Matches the `kcSecretsMountPath` helper in the chart.
SECRETS_MOUNT_PATH = os.getenv("KC_SECRETS_PATH", "/etc/secrets/kc")


def read_secret(name: str, default: str = "") -> str:
    """
    Read a credential, preferring the mounted file so rotations are picked up.

    Deliberately not cached: the whole point is to observe a value that changes underneath us. These
    are small local reads from tmpfs, so re-reading is cheap.
    """
    path = os.path.join(SECRETS_MOUNT_PATH, name)
    try:
        with open(path, encoding="utf-8") as handle:
            # Trailing newlines are common when a secret is created by hand with kubectl.
            return handle.read().strip()
    except FileNotFoundError:
        return os.getenv(name, default)
    except OSError as exc:
        logger.warning(f"Could not read {path} ({exc}), falling back to the environment")
        return os.getenv(name, default)
