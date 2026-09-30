from pydantic import BaseModel, ConfigDict


class WhitelistedImage(BaseModel):
    """Whitelisted image data from backend API."""
    model_config = ConfigDict(extra="allow")

    id: int
    registry_id: int | None = None
    project_id: int
    name: str
    tag: str | None = None
    sha: str | None = None
