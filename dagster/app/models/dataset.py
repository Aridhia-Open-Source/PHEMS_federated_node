from pydantic import BaseModel, ConfigDict

from app.models.secret_type import SecretType


class Dataset(BaseModel):
    """
    Dataset data from backend API.

    - id: the dataset's id.
    - project_id: the project the dataset belongs to.
    - secret_name: the project-local name of the secret holding the database credentials
      (USERNAME and PASSWORD).
    - secret_type: which secret store holds that secret.
    - secret_store_name: what the secret is called in that store: the name is local to the
      project, the store's is not.
    - name: the database name.
    - host: the database host.
    - port: the database port.
    - read_schema: the schema the task reads from (the CDM), if set.
    - write_schema: the schema the task writes its results to, if set.
    - type: the database engine, e.g. postgres.
    - extra_connection_args: extra arguments for the connection string, if any.
    - created_at: when the dataset was created.
    - updated_at: when the dataset was last updated.
    - slug: the dataset name as used in URLs.
    - url: the dataset's public URL.
    """
    model_config = ConfigDict(extra="allow")

    id: int
    project_id: int
    secret_name: str
    secret_type: SecretType
    secret_store_name: str
    name: str
    host: str
    port: int
    read_schema: str | None = None
    write_schema: str | None = None
    type: str
    extra_connection_args: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    slug: str
    url: str


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
