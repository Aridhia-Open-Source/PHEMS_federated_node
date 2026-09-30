from app.dtos.base import DTO, WireDatetime


class AuditDTO(DTO):
    id: int
    ip_address: str
    http_method: str
    endpoint: str
    requested_by: str
    status_code: int | None
    api_function: str | None
    details: str | None
    event_time: WireDatetime | None
