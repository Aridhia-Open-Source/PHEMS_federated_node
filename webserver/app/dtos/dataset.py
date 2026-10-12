from app.dtos.base import DTO, WireDatetime


class CatalogueDTO(DTO):
    id: int
    dataset_id: int | None
    version: str | None
    title: str
    description: str
    created_at: WireDatetime
    updated_at: WireDatetime


class DictionaryDTO(DTO):
    id: int
    dataset_id: int | None
    table_name: str
    field_name: str
    label: str | None
    description: str
    created_at: WireDatetime
    updated_at: WireDatetime
