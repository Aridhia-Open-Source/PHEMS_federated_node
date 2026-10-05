from enum import Enum


class SecretProviderType(str, Enum):
    """Which secret store holds a secret, as the webserver defines it."""

    K8S = "K8S"
