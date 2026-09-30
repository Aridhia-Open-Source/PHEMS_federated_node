from app.dtos.base import DTO, WireDatetime


class K8sSecretDTO(DTO):
    id: int
    name: str
    created_at: WireDatetime
    updated_at: WireDatetime
