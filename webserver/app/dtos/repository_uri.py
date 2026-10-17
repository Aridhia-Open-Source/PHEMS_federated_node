from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from app.helpers.exceptions import InvalidRequest
from app.helpers.git_uri import normalise_repo_uri


class RepositoryUriRequest(BaseModel):
    """
    The uri of a trigger or results repository named by a task, normalised.
    """
    model_config = ConfigDict(extra="forbid")

    uri: str

    @field_validator("uri")
    @classmethod
    def normalise(cls, uri: str) -> str:
        return normalise_repo_uri(uri)

    @classmethod
    def normalised(cls, uri) -> str:
        try:
            return cls(uri=uri).uri
        except ValidationError as ve:
            raise InvalidRequest(f"Invalid repository uri: {ve}") from ve


class RepositoryRequest(BaseModel):
    """A trigger or results repository in a create request."""
    model_config = ConfigDict(extra="forbid", strict=True)

    provider_id: int
    repo_path: str = Field(min_length=1, max_length=512)
    secret_label: str = Field(min_length=1)
    enabled: bool = True

    @classmethod
    def parse(cls, body) -> "RepositoryRequest":
        try:
            return cls.model_validate(body)
        except ValidationError as ve:
            raise InvalidRequest(f"Invalid repository: {ve}") from ve


class RepositoryPatchRequest(BaseModel):
    """The fields of a trigger or results repository that can be updated, all optional but never null."""
    model_config = ConfigDict(extra="forbid", strict=True)

    provider_id: int | None = None
    secret_label: str | None = Field(default=None, min_length=1)
    enabled: bool | None = None

    @model_validator(mode="after")
    def not_null(self):
        nulls = sorted(f for f in self.model_fields_set if getattr(self, f) is None)
        if nulls:
            raise ValueError(f"{', '.join(nulls)} cannot be null")
        return self

    @classmethod
    def parse(cls, body) -> "RepositoryPatchRequest":
        try:
            return cls.model_validate(body)
        except ValidationError as ve:
            raise InvalidRequest(f"Invalid repository update: {ve}") from ve
