"""
Who created a record (ADR 0035). Every record a caller creates carries the caller's users row as owner_id.
"""
from app.helpers.wrappers import Caller
from app.models.user import OwnedMixin


def set_owner(record: OwnedMixin, caller: Caller) -> None:
    """Records the caller as the user that created the record."""
    record.owner_id = caller.user.id
