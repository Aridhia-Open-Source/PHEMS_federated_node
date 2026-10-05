from pydantic import BaseModel, ConfigDict

from .secret_provider import SecretProvider


class Secret(BaseModel):
    """
    A secret as the backend API nests it in a dataset or repository.

    - name: the project-local name of the secret.
    - provider: which secret store holds it.
    - key: what the secret is called in that store: the name is local to the project, the
      store's is not.
    """
    model_config = ConfigDict(extra="allow")

    name: str
    provider: SecretProvider
    key: str
