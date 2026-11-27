from pydantic import BaseModel, ConfigDict, Field

from app.dtos.base import DTO


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
    """A nexus-api user as a record names it, as its owner (ADR 0036)."""
    id: str
    username: str

    @classmethod
    def of(cls, user) -> "UserRefDTO | None":
        """The user as a reference, None for no user."""
        return None if user is None else cls.model_validate(user)


class UserRequest(BaseModel):
    """A Keycloak user to create. The username is the email unless given, the role is Users."""
    model_config = ConfigDict(extra="forbid", strict=True)

    email: str = Field(min_length=1)
    username: str | None = Field(default=None, min_length=1)
    firstName: str | None = None
    lastName: str | None = None
    role: str | None = Field(default=None, min_length=1)


class PasswordResetRequest(BaseModel):
    """A new user swapping the temporary password they were given for their own."""
    model_config = ConfigDict(extra="forbid", strict=True)

    email: str = Field(min_length=1)
    tempPassword: str = Field(min_length=1)
    newPassword: str = Field(min_length=1)
