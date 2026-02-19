from typing import Optional
from pydantic import BaseModel, ConfigDict
from datetime import datetime as dt


class AuditBase(BaseModel):
    id: int
    ip_address: str
    http_method: str
    endpoint: str
    requested_by: str
    status_code: int|None
    api_function: str|None
    details: str|None
    event_time: dt

    model_config = ConfigDict(from_attributes=True)


class AuditFilters(BaseModel):
    http_method: Optional[str] = None
    ip_address: Optional[str] = None
    endpoint: Optional[str] = None
    api_function: Optional[str] = None
    event_time: Optional[str] = None
    event_time__lte: Optional[str] = None
    event_time__gte: Optional[str] = None
    event_time__ne: Optional[str] = None
    event_time__eq: Optional[str] = None
    event_time__lt: Optional[str] = None
    event_time__gt: Optional[str] = None

    page: int = 1
    per_page: int = 25
