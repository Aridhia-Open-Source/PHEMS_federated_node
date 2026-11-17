from pydantic import BaseModel, ConfigDict


class GitProvider(BaseModel):
    """
    The git host a repository is on, from backend API.

    - type: which API client to build, github or gitea.
    - uri: the host's web address, which the repositories' clone URLs are under.
    - api_uri: the host's API base URL.
    - enabled: turned on or off for the whole node. The backend's active filters apply it.
    """
    model_config = ConfigDict(extra="allow")

    id: int
    # The nexus operator's user when its custom resource declares the record (ADR 0032)
    managed_by: str | None = None
    name: str
    type: str
    uri: str
    api_uri: str
    enabled: bool
