from typing import Literal

from pydantic import BaseModel

from app.dtos.base import DTO
from app.models.node_role import NodeRole


class NewUserRequest(BaseModel):
    """POST /global/users. The username defaults to the email; the role is Users or Administrator."""
    email: str
    username: str | None = None
    firstName: str | None = None
    lastName: str | None = None
    role: Literal[NodeRole.USERS, NodeRole.ADMINISTRATOR] = NodeRole.USERS


class UserDTO(DTO):
    """A simplified Keycloak user, as listed. firstName and lastName are Keycloak's names."""
    username: str
    email: str
    firstName: str
    lastName: str
    # The user's realm roles
    role: list[str]
    needs_to_reset_password: bool


class NewUserDTO(DTO):
    """The response of creating a user: the temporary password is shown once."""
    email: str
    username: str
    tempPassword: str
    info: str


class UserRefDTO(DTO):
    """A nexus-api user as a record names it, as its creator or owner (ADR 0037)."""
    id: str
    username: str

    @classmethod
    def of(cls, user) -> "UserRefDTO | None":
        """The user as a reference, None for no user."""
        return None if user is None else cls.model_validate(user)
