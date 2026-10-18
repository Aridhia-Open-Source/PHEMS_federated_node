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
    name: str
    type: str
    uri: str
    api_uri: str
    enabled: bool
