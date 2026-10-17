from pydantic import BaseModel, ConfigDict

from fncli.dagster.models.secret_provider_type import SecretProviderType


class Secret(BaseModel):
    """
    A secret as the backend API nests it in a dataset or repository.

    - id: the secret's id.
    - label: the secret's unique name, which the CLI addresses it by.
    - description: what the secret is for, if given.
    - provider: which secret store holds it.
    - key: what the secret is called in that store. The backend generates it; nothing here
      derives it.
    - namespace: where the store keeps it, for stores that have such a notion.
    - enabled: turned on or off for the whole node.
    - created_at: when the secret was created.
    - updated_at: when the secret was last updated.
    """
    model_config = ConfigDict(extra="allow")

    id: int
    label: str | None = None
    description: str | None = None
    provider: SecretProviderType
    key: str
    namespace: str | None = None
    enabled: bool
    created_at: str | None = None
    updated_at: str | None = None
