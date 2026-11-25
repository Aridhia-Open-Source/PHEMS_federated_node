"""
Who created and who owns a record (ADR 0037). Every record a caller creates carries the caller's users row as
created_by. A project or a global record (OwnedMixin) is also owned_by the caller, who gets a manage grant on it in
the same transaction; for the operator (role Service) the grant goes to group /roles/service, so a second operator
client manages it too.
"""
from app.database.base_model import db
from app.dtos.caller import Caller
from app.models.grant import GROUP, MANAGE, USER, Grant
from app.models.node_role import NodeRole
from app.models.user import CreatedByMixin, OwnedMixin

SERVICE_GROUP = "/roles/service"


def set_owner(record: CreatedByMixin, caller: Caller) -> None:
    """
    Records the caller as the user that created the record. For a record with grants, also its owner, with a
    manage grant; that adds and flushes the record, for its id.
    """
    record.created_by_id = caller.user.id
    if not isinstance(record, OwnedMixin):
        return
    record.owned_by_id = caller.user.id
    db.session.add(record)
    db.session.flush()
    if caller.role == NodeRole.SERVICE:
        add_manage(record, GROUP, SERVICE_GROUP, caller)
    else:
        add_manage(record, USER, caller.user.id, caller)


def add_manage(record: OwnedMixin, subject_type: str, subject_id: str, caller: Caller) -> None:
    """Gives the subject manage on the record with no expiry; one it already has loses its expiry."""
    exists = db.session.scalars(
        Grant.of(record).where(
            Grant.relation == MANAGE, Grant.subject_type == subject_type, Grant.subject_id == subject_id
        )
    ).first()
    if exists is not None:
        exists.expires_at = None
    else:
        db.session.add(Grant(
            object_type=record.authz_type, object_id=record.id, relation=MANAGE,
            subject_type=subject_type, subject_id=subject_id, created_by_id=caller.user.id,
        ))
