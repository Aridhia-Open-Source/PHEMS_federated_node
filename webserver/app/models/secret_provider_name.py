"""Secret provider enum."""

from enum import Enum


class SecretProviderName(str, Enum):
    """Which secret store holds the value of a secret."""

    K8S = "K8S"
