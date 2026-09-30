"""Git hosting providers a trigger repository can live on."""

from dataclasses import dataclass
from enum import Enum


class GitProvider(str, Enum):
    """
    Which git host a repository is on, so the sensors know which API client to build.
    Each value is a provider the Dagster side has an API client for.
    """

    GITHUB = "github"
    GITEA = "gitea"

    def __str__(self):
        return self.value


class ConnectionStatus(str, Enum):
    """The outcome of checking that a trigger repository can be reached with its token."""

    OK = "ok"
    UNAUTHORIZED = "unauthorized"
    NOT_FOUND = "not_found"
    UNREACHABLE = "unreachable"
    SECRET_MISSING = "secret_missing"
    ERROR = "error"

    def __str__(self):
        return self.value


@dataclass
class ConnectionCheck:
    """
    What checking a trigger repository's connection found. The status code and latency are
    only known when a request was made.
    """

    status: ConnectionStatus
    message: str
    status_code: int | None = None
    latency_ms: int | None = None
