"""
Who owns a record, and who may change it (ADR 0036). The creator owns a record. When the creator is in one
of OWNER_GROUPS (a service account), the record is locked to that group: only its members may change it,
anyone else gets a 409. A member of an owner group that writes a record takes it over.

The check is explicit: every write route loads its record through get_for_write. Reads use the normal
lookups.
"""
from collections.abc import Callable
from http import HTTPStatus

from sqlalchemy.orm import Session

from app.helpers.exceptions import DBRecordNotFoundError, InvalidRequest
from app.helpers.wrappers import Caller
from app.models.user import OwnedMixin


def set_owner(record: OwnedMixin, caller: Caller) -> None:
    """Makes the caller the owner of a record it creates, locked to its owner group if it is in one."""
    record.owner_id = caller.user.id
    record.owner_group = caller.owner_group


def get_for_write[M: OwnedMixin](
    session: Session,
    model: type[M],
    ident: int | dict,
    caller: Caller,
    fields: set[str] | None = None,
    missing: str | None = None,
    optional: bool = False,
) -> M | None:
    """
    The record a write will change: by primary key, or by the columns in ident. A missing record is a
    404 (with the message missing), or None when optional (a PUT that creates it). A record locked to an
    owner group the caller is not in is a 409. fields are the fields the write changes, None for the whole
    record; only those in the model's owner_locked_fields are locked (all of them when that is None).
    A caller in an owner group becomes the record's owner.
    """
    criteria = ident if isinstance(ident, dict) else {"id": ident}
    record = session.query(model).filter_by(**criteria).one_or_none()
    if record is None:
        if optional:
            return None
        raise DBRecordNotFoundError(missing or f"{model.__name__.capitalize()} with id {ident} does not exist")

    group = record.owner_group
    member = _member(group, caller)
    if not member and _locks(model, fields):
        raise InvalidRequest(
            f"{record!r} is owned by {group}: only its members can change it", HTTPStatus.CONFLICT
        )
    if member and caller.owner_group:
        record.owner_id = caller.user.id
        record.owner_group = group or caller.owner_group
    return record


def require_member[M: OwnedMixin](record: M, caller: Caller) -> M:
    """
    For a write under a record that does not change the record itself (a project's datasets, secrets and
    repositories): a 409 when the record is owned by a group the caller is not in. The caller does not take
    the record over.
    """
    group = record.owner_group
    if not _member(group, caller):
        raise InvalidRequest(
            f"{record!r} is owned by {group}: only its members can change what is under it", HTTPStatus.CONFLICT
        )
    return record


def require_members[M: OwnedMixin](records: list[M], caller: Caller, describe: Callable[[M], dict]) -> None:
    """
    For a delete that cascades to records it did not load through get_for_write (the project resources
    under a dataset, repository, secret or project): a 409 naming each record owned by a group the caller
    is not in, described by describe, before anything is changed. The same rule as get_for_write for a
    write to the whole record.
    """
    refused = [record for record in records if not _member(record.owner_group, caller)]
    if refused:
        error = InvalidRequest(
            f"{len(refused)} record(s) it would delete are owned by a group you are not in: nothing was deleted",
            HTTPStatus.CONFLICT,
        )
        error.extra_fields = [{**describe(record), "owner_group": record.owner_group} for record in refused]
        raise error


def _member(group: str | None, caller: Caller) -> bool:
    """Whether the caller may change a record owned by group (None: no owner group)."""
    return group is None or group in caller.groups


def _locks(model: type[OwnedMixin], fields: set[str] | None) -> bool:
    locked = model.owner_locked_fields
    return fields is None or locked is None or bool(fields & locked)
