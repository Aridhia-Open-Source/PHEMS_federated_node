from app.dtos.base import DTO, WireDatetime
from app.helpers.const import PUBLIC_URL
from app.dtos.secret import SecretDTO
from app.models.dataset import Dataset
from app.models.project_dataset import ProjectDataset


class DatasetDTO(DTO):
    id: int
    secret: SecretDTO
    name: str
    host: str
    port: int
    read_schema: str | None
    write_schema: str | None
    type: str
    extra_connection_args: str | None
    enabled: bool
    created_at: WireDatetime
    updated_at: WireDatetime
    slug: str
    url: str

    @classmethod
    def from_model(cls, obj: Dataset):
        slug = obj.slugify_name()
        return cls(
            id=obj.id,
            secret=SecretDTO.from_model(obj.secret),
            name=obj.name,
            host=obj.host,
            port=obj.port,
            read_schema=obj.read_schema,
            write_schema=obj.write_schema,
            type=obj.type,
            extra_connection_args=obj.extra_connection_args,
            enabled=obj.enabled,
            created_at=obj.created_at,
            updated_at=obj.updated_at,
            slug=slug,
            url=f"https://{PUBLIC_URL}/global/datasets/{obj.id}",
        )


class ProjectDatasetDTO(DTO):
    """A project's link to a global dataset, the dataset nested. Addressed by the dataset's id."""
    project_id: int
    dataset: DatasetDTO
    enabled: bool
    revoked: bool
    active: bool

    @classmethod
    def from_model(cls, obj: ProjectDataset):
        return cls(
            project_id=obj.project_id,
            dataset=DatasetDTO.from_model(obj.dataset),
            enabled=obj.enabled,
            revoked=obj.revoked,
            active=obj.active,
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
