from pydantic import BaseModel, ConfigDict


class Audit(BaseModel):
    """Audit entry from backend API."""
    model_config = ConfigDict(extra="allow")

    id: int
    ip_address: str
    http_method: str
    endpoint: str
    requested_by: str
    status_code: int | None = None
    api_function: str | None = None
    details: str | None = None
    event_time: str | None = None
