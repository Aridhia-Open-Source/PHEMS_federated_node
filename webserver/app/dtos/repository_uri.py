from pydantic import BaseModel, ConfigDict, ValidationError, field_validator

from app.helpers.exceptions import InvalidRequest
from app.helpers.git_uri import normalise_repo_uri


class RepositoryUriRequest(BaseModel):
    """
    The uri of a trigger or results repository in a create or patch request, normalised.
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
