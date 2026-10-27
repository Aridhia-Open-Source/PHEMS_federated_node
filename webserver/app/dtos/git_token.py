from pydantic import BaseModel, ConfigDict, ValidationError

from app.dtos.base import DTO, WireDatetime
from app.helpers.exceptions import InvalidRequest


class GitTokenRequest(BaseModel):
    """A request for a repository's git token: the project it is for, if any."""
    model_config = ConfigDict(extra="forbid", strict=True)

    project_id: int | None = None

    @classmethod
    def parse(cls, body) -> "GitTokenRequest":
        try:
            return cls.model_validate(body)
        except ValidationError as ve:
            raise InvalidRequest(f"Invalid token request: {ve}") from ve


class GitTokenDTO(DTO):
    """A short-lived access token for a repository, and its expiry (UTC). Kept only in the secret's cache."""
    token: str
    expires_at: WireDatetime
