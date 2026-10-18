import urllib.parse
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, ValidationError, field_validator

from app.dtos.base import DTO, WireDatetime
from app.helpers.const import PUBLIC_URL
from app.helpers.exceptions import InvalidRequest
from app.dtos.secret import SecretDTO
from app.models.dataset import SUPPORTED_ENGINES, Dataset
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


class DatasetPatchRequest(BaseModel):
    """The fields a dataset PATCH may change, all optional. Anything else is refused."""
    model_config = ConfigDict(extra="forbid", strict=True)

    name: str | None = Field(default=None, min_length=1, max_length=256)
    host: str | None = Field(default=None, min_length=1, max_length=256)
    port: Annotated[StrictInt, Field(ge=1, le=65535)] | None = None
    read_schema: str | None = Field(default=None, max_length=256)
    write_schema: str | None = Field(default=None, max_length=256)
    type: str | None = None
    extra_connection_args: str | None = Field(default=None, max_length=4096)
    enabled: StrictBool | None = None
    secret_label: str | None = Field(default=None, min_length=1)
    catalogue: dict | None = None
    dictionaries: list | None = None

    @field_validator("name")
    @classmethod
    def normalised_name(cls, value):
        """Stored unquoted and lowercase, like the Dataset constructor does."""
        if value is not None:
            if not value.strip():
                raise ValueError("name must not be blank")
            value = urllib.parse.unquote(value).lower()
        return value

    @field_validator("type")
    @classmethod
    def supported_engine(cls, value):
        """Only the engines the node can talk to."""
        if value is not None and value.lower() not in SUPPORTED_ENGINES:
            raise ValueError(f"DB type {value} is not supported.")
        return value

    @field_validator("port", "host", "name", "secret_label", "enabled", "type")
    @classmethod
    def not_null(cls, value, info):
        """These columns are non-nullable, so an explicit null is a mistake."""
        if value is None:
            raise ValueError(f"{info.field_name} must not be null")
        return value

    @classmethod
    def parse(cls, body):
        """Validates a request body, mapping a pydantic error to a 400."""
        try:
            return cls.model_validate(body)
        except ValidationError as ve:
            raise InvalidRequest(f"Invalid dataset: {ve}") from ve


class DatasetRequest(DatasetPatchRequest):
    """A dataset to create: name, host, port and secret_label are required."""
    model_config = ConfigDict(extra="ignore", strict=True)

    name: str = Field(min_length=1, max_length=256)
    host: str = Field(min_length=1, max_length=256)
    port: Annotated[StrictInt, Field(ge=1, le=65535)]
    type: str = "postgres"
    enabled: StrictBool = True
    secret_label: str = Field(min_length=1)
    catalogue: dict = Field(default_factory=dict)
    dictionaries: list = Field(default_factory=list)
