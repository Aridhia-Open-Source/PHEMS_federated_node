from pydantic import BaseModel, ConfigDict


class GitToken(BaseModel):
    """
    A short-lived access token for a git repository, as the backend mints it for
    POST /global/repositories/triggers/<id>/token and POST /global/repositories/results/<id>/token.

    - token: the access token, to use at once and never store.
    - expires_at: when the token stops working.
    """
    model_config = ConfigDict(extra="allow")

    token: str
    expires_at: str
