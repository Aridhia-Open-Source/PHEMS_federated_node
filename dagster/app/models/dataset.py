from pydantic import BaseModel, ConfigDict

from app.models.secret import Secret


class Dataset(BaseModel):
    """
    Dataset data from backend API.

    - id: the dataset's id.
    - secret: the secret holding the database credentials (USERNAME and PASSWORD).
    - name: the database name.
    - host: the database host.
    - port: the database port.
    - read_schema: the schema the task reads from (the CDM), if set.
    - write_schema: the schema the task writes its results to, if set.
    - type: the database engine, e.g. postgres.
    - extra_connection_args: extra arguments for the connection string, if any.
    - enabled: turned on or off for the whole node.
    - created_at: when the dataset was created.
    - updated_at: when the dataset was last updated.
    - slug: the dataset name as used in URLs.
    - url: the dataset's public URL.
    """
    model_config = ConfigDict(extra="allow")

    id: int
    secret: Secret
    name: str
    host: str
    port: int
    read_schema: str | None = None
    write_schema: str | None = None
    type: str
    extra_connection_args: str | None = None
    enabled: bool
    created_at: str | None = None
    updated_at: str | None = None
    slug: str
    url: str


class ProjectDataset(BaseModel):
    """
    A project's resource for a global dataset, from backend API. Addressed by the dataset's id,
    dataset.id.

    - project_id: the project the dataset is assigned to.
    - dataset: the global dataset.
    - enabled: a person turned the dataset on for the project.
    - revoked: the controller withdrew the project's access.
    - active: the global dataset is enabled, and the project resource is enabled and not revoked, the only state a task may run in.
    """
    model_config = ConfigDict(extra="allow")

    project_id: int
    dataset: Dataset
    enabled: bool
    revoked: bool
    active: bool


class Catalogue(BaseModel):
    """Dataset catalogue data from backend API."""
    model_config = ConfigDict(extra="allow")

    id: int
    dataset_id: int | None = None
    version: str | None = None
    title: str
    description: str
    created_at: str | None = None
    updated_at: str | None = None


class Dictionary(BaseModel):
    """Dataset dictionary entry from backend API."""
    model_config = ConfigDict(extra="allow")

    id: int
    dataset_id: int | None = None
    table_name: str
    field_name: str
    label: str | None = None
    description: str
    created_at: str | None = None
    updated_at: str | None = None
