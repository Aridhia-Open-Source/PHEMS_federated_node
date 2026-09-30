from app.dtos.base import DTO, WireDatetime


class K8sSecretDTO(DTO):
    id: int
    project_id: int
    name: str
    k8s_name: str
    created_at: WireDatetime
    updated_at: WireDatetime
