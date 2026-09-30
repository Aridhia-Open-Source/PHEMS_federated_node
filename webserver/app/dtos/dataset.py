from app.dtos.base import DTO, WireDatetime
from app.helpers.const import PUBLIC_URL
from app.models.dataset import Dataset


class DatasetDTO(DTO):
    id: int
    project_id: int
    k8s_secret_name: str
    k8s_secret_k8s_name: str
    name: str
    host: str
    port: int | None
    read_schema: str | None
    write_schema: str | None
    type: str
    extra_connection_args: str | None
    created_at: WireDatetime
    updated_at: WireDatetime
    slug: str
    url: str

    @classmethod
    def from_model(cls, obj: Dataset):
        slug = obj.slugify_name()
        return cls(
            id=obj.id,
            project_id=obj.project_id,
            k8s_secret_name=obj.k8s_secret_name,
            k8s_secret_k8s_name=obj.k8s_secret_k8s_name,
            name=obj.name,
            host=obj.host,
            port=obj.port,
            read_schema=obj.read_schema,
            write_schema=obj.write_schema,
            type=obj.type,
            extra_connection_args=obj.extra_connection_args,
            created_at=obj.created_at,
            updated_at=obj.updated_at,
            slug=slug,
            url=f"https://{PUBLIC_URL}/datasets/{slug}",
        )


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
