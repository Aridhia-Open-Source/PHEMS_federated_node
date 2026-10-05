from pydantic import BaseModel, ConfigDict

from app.models.secret_provider_type import SecretProviderType


class Secret(BaseModel):
    """
    A secret as the backend API nests it in a dataset or repository.

    - id: the secret's id.
    - project_id: the project the secret belongs to.
    - label: the project-local identifier of the secret.
    - description: what the secret is for, if given.
    - provider: which secret store holds it.
    - key: what the secret is called in that store: the label is local to the project, the
      store's name is not. The backend generates it; nothing here derives it.
    - namespace: where the store keeps it, for stores that have such a notion.
    - created_at: when the secret was created.
    - updated_at: when the secret was last updated.
    """
    model_config = ConfigDict(extra="allow")

    id: int
    project_id: int
    label: str
    description: str | None = None
    provider: SecretProviderType
    key: str
    namespace: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
