"""
Who created a record (ADR 0035). Every record a caller creates carries the caller's users row as owner_id.
"""
from app.helpers.exceptions import UnauthorizedError
from app.helpers.wrappers import Caller
from app.models.node_role import NodeRole
from app.models.task import Task
from app.models.user import OwnedMixin


def set_owner(record: OwnedMixin, caller: Caller) -> None:
    """Records the caller as the user that created the record."""
    record.owner_id = caller.user.id


def does_user_own_task(task: Task, caller: Caller):
    """
    Simple wrapper to check if the user is the one who
    triggered the task, or is admin, or is the system user (Dagster, which reads tasks it
    did not request).

    If they don't, an exception is raised with 403 status code
    """
    # Stopgap owner/role check: Cedar read enforcement (auth/8 #688, T-076) replaces it.
    if task.requested_by != caller.user_id and not caller.is_admin and caller.role != NodeRole.DAGSTER:
        raise UnauthorizedError("User does not have enough permissions")
