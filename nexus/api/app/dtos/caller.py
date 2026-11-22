"""The verified caller of a request (ADR 0036)."""
from pydantic import BaseModel, ConfigDict

from app.helpers.exceptions import AuthenticationError
from app.models.node_role import ADMIN_ROLES, NodeRole
from app.models.user import User


class Caller(BaseModel):
    """Who is calling, from a verified access token (ADR 0036)."""
    model_config = ConfigDict(arbitrary_types_allowed=True)

    # Keycloak's user id (sub)
    user_id: str
    role: NodeRole
    groups: list[str]
    # The caller's row in users, created or refreshed on this call
    user: User

    @property
    def is_admin(self) -> bool:
        """One of the roles that manage the node."""
        return self.role in ADMIN_ROLES

    @classmethod
    def from_claims(cls, claims: dict) -> "Caller":
        """The caller a token's claims name: exactly one node role, or AuthenticationError."""
        node_roles = {role.value for role in NodeRole}
        roles = [role for role in claims.get("realm_access", {}).get("roles", []) if role in node_roles]
        if len(roles) != 1:
            raise AuthenticationError("The user must hold exactly one node role")
        return cls(
            user_id=claims["sub"],
            role=NodeRole(roles[0]),
            groups=claims.get("groups", []),
            user=User.seen(claims["sub"], claims.get("preferred_username", claims["sub"])),
        )
