from pydantic import BaseModel, ConfigDict

from app.dtos.base import DTO, WireDatetime


class GitTokenRequest(BaseModel):
    """A request for a repository's git token: the project it is for, if any."""
    model_config = ConfigDict(extra="forbid", strict=True)

    project_id: int | None = None


class GitTokenDTO(DTO):
    """A short-lived access token for a repository, and its expiry (UTC). Kept only in the secret's cache."""
    token: str
    expires_at: WireDatetime
