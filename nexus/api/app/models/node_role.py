"""The node roles (ADR 0037). A caller holds exactly one; other realm roles (default-roles-*, offline_access, ...)
are ignored."""

from enum import Enum


class NodeRole(str, Enum):
    """A realm role nexus-api acts on, as a token's realm_access.roles names it."""
    SUPERUSER = "SuperUser"
    ADMINISTRATOR = "Administrator"
    SERVICE = "Service"
    USERS = "Users"
    DAGSTER = "Dagster"

    def __str__(self):
        return self.value


# The roles that manage the node: they may set `revoked` and see every task
ADMIN_ROLES = frozenset({NodeRole.SUPERUSER, NodeRole.ADMINISTRATOR, NodeRole.SERVICE})
