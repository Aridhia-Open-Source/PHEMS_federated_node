from pydantic import BaseModel, ConfigDict


class Dataset(BaseModel):
    """Dataset data from backend API."""
    model_config = ConfigDict(extra="allow")

    id: int
    project_id: int
    # The Kubernetes secret holding the database credentials (USERNAME and PASSWORD).
    k8s_secret_name: str
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

    def dump_task_fields(self) -> dict:
        """Return only the fields needed for task configuration with dataset_ prefix."""
        keys = {"name", "host", "port", "type", "read_schema", "write_schema", "k8s_secret_name"}
        fields = self.model_dump(include=keys)
        return {f"dataset_{k}": v for k, v in fields.items()}


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
