from pydantic import BaseModel, ConfigDict

from app.models.secret_provider_type import SecretProviderType


class Secret(BaseModel):
    """
    A secret as the backend API nests it in a dataset or repository.

    - label: the project-local identifier of the secret.
    - provider: which secret store holds it.
    - key: what the secret is called in that store: the label is local to the project, the
      store's name is not. The backend generates it; nothing here derives it.
    """
    model_config = ConfigDict(extra="allow")

    label: str
    provider: SecretProviderType
    key: str
