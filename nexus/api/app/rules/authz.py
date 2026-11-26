"""
The Cedar access check (ADR 0037). The rules are nexus/api/authz/policies.cedar, checked against
schema.cedarschema; this module builds each request from the caller, the record and the caller's grants on it,
and asks Cedar. Nothing calls can() from the routes yet; the Access dependency comes next.

cedarpy is only called from this module, so swapping the wrapper stays local.
"""
import hashlib
import time
from datetime import timezone
from dataclasses import dataclass, field
from enum import StrEnum
from functools import cache
from pathlib import Path

import cedarpy
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert

from app.database.base_model import db, engine
from app.dtos.caller import Caller
from app.models.grant import GROUP, USER, Grant
from app.models.policy_version import PolicyVersion

AUTHZ_DIR = Path(__file__).resolve().parents[2] / "authz"
POLICY_FILES = ("policies.cedar", "schema.cedarschema", "cases.yaml")
# The expiry passed for a grant with none: year 9999, far past any context.now
NEVER = 253402300799
# The record types under Global::"0"; projects are created under it but are not its children
GLOBAL_TYPES = frozenset({"Dataset", "GitProvider", "Secret", "TriggerRepository", "ResultsRepository"})


class Action(StrEnum):
    """What a route asks to do with its record; every one but UNCHECKED is a Cedar action."""
    READ = "read"
    WRITE = "write"
    EXECUTE = "execute"
    ASSIGN = "assign"
    OPERATE = "operate"       # turning a project and its parts on or off, and backfill
    MANAGE = "manage"         # changing the record's grants
    UNCHECKED = "unchecked"   # no record check; the route has no record


class Global:  # pylint: disable=too-few-public-methods
    """The container of global records, Global::"0" in Cedar. Not a table and has no grants."""
    authz_type = "Global"
    id = 0


GLOBAL = Global()


class PolicyError(RuntimeError):
    """The policy files fail validation; nexus-api does not start."""


@dataclass(frozen=True)
class Principal:
    """The caller as Cedar sees it: User::"<user_id>", in Role::"<role>" and each Group::"<path>"."""
    user_id: str
    role: str
    groups: tuple[str, ...] = ()


@dataclass(frozen=True)
class Resource:
    """The record as Cedar sees it: <type>::"<id>" with its attributes."""
    type: str
    id: str
    attrs: dict = field(default_factory=dict)


@dataclass(frozen=True)
class Policies:
    """The policy files as read at startup."""
    policies: str
    schema: str
    # sha256 of the three policy files, hex
    hash: str
    contents: str


@cache
def load_policies() -> Policies:
    """Reads the policy files once."""
    texts = {name: (AUTHZ_DIR / name).read_text() for name in POLICY_FILES}
    contents = "".join(f"// {name}\n{text}" for name, text in texts.items())
    return Policies(
        policies=texts["policies.cedar"], schema=texts["schema.cedarschema"],
        hash=hashlib.sha256(contents.encode()).hexdigest(), contents=contents,
    )


def validate(policies: str, schema: str) -> None:
    """Raises PolicyError if the policies fail the schema or an Action but UNCHECKED is not in it."""
    result = cedarpy.validate_policies(policies, schema)
    if not result.validation_passed:
        raise PolicyError(f"Cedar policies are not valid: {[error.error for error in result.errors]}")
    for action in Action:
        if action == Action.UNCHECKED:
            continue
        probe = cedarpy.validate_policies(f'permit (principal, action == Action::"{action}", resource);', schema)
        if not probe.validation_passed:
            raise PolicyError(f"Action {action} is not in the Cedar schema")


def check_policies() -> None:
    """The startup check: the repo's policy files are valid."""
    policies = load_policies()
    validate(policies.policies, policies.schema)


def record_policy_version() -> None:
    """Writes a policy_versions row if the policy files' hash is new. Outside a request, so on the engine."""
    policies = load_policies()
    with engine.begin() as conn:
        conn.execute(
            insert(PolicyVersion.__table__).values(hash=policies.hash, contents=policies.contents)
            .on_conflict_do_nothing(index_elements=["hash"])
        )


def _uid(type_: str, id_: str) -> dict:
    return {"type": type_, "id": str(id_)}


def is_allowed(principal: Principal, action: Action, resource: Resource, grants: dict[str, int], now: int) -> bool:
    """
    Cedar's answer for one request. grants is the caller's latest expiry per relation, epoch seconds; the
    user's parents are its node role and its groups, and a global record's parent is Global::"0".
    """
    policies = load_policies()
    parents = [_uid("Role", principal.role), *(_uid("Group", group) for group in principal.groups)]
    entities = [
        {"uid": _uid("User", principal.user_id), "attrs": {}, "parents": parents},
        *({"uid": parent, "attrs": {}, "parents": []} for parent in parents),
        {"uid": _uid("Global", GLOBAL.id), "attrs": {}, "parents": []},
    ]
    if resource.type != Global.authz_type:
        entities.append({
            "uid": _uid(resource.type, resource.id), "attrs": resource.attrs,
            "parents": [_uid("Global", GLOBAL.id)] if resource.type in GLOBAL_TYPES else [],
        })
    request = {
        "principal": f'User::"{principal.user_id}"',
        "action": f'Action::"{action}"',
        "resource": f'{resource.type}::"{resource.id}"',
        "context": {"now": now, "grants": grants},
    }
    result = cedarpy.is_authorized(request, policies.policies, entities, schema=policies.schema)
    # A malformed request comes back as a deny with errors: fail loudly instead of denying quietly
    if result.diagnostics.errors:
        raise PolicyError(f"Cedar could not evaluate {request}: {result.diagnostics.errors}")
    return result.allowed


def grants_for(caller: Caller, record) -> dict[str, int]:
    """
    The caller's unexpired grants on the record, as the latest expiry per relation (epoch seconds, NEVER for no
    expiry). One query, on the user and any of its groups. Global has no grants.
    """
    if isinstance(record, Global):
        return {}
    subject = sa.or_(
        sa.and_(Grant.subject_type == USER, Grant.subject_id == caller.user_id),
        sa.and_(Grant.subject_type == GROUP, Grant.subject_id.in_(caller.groups)),
    )
    unexpired = sa.or_(Grant.expires_at.is_(None), Grant.expires_at > sa.func.timezone('utc', sa.func.now()))
    rows = db.session.execute(
        sa.select(Grant.relation, Grant.expires_at)
        .where(Grant.object_type == record.authz_type, Grant.object_id == record.id, subject, unexpired)
    )
    grants: dict[str, int] = {}
    for relation, expires_at in rows:
        # expires_at is naive UTC
        expiry = NEVER if expires_at is None else int(expires_at.replace(tzinfo=timezone.utc).timestamp())
        grants[relation] = max(grants.get(relation, 0), expiry)
    return grants


def resource_of(record) -> Resource:
    """The record as a Cedar resource, with its attributes."""
    attrs = {"revoked": bool(record.revoked)} if record.authz_type == "Dataset" else {}
    return Resource(type=record.authz_type, id=str(record.id), attrs=attrs)


def can(caller: Caller, action: Action, record) -> bool:
    """Whether the caller may do the action on the record (a project, a global record or GLOBAL)."""
    principal = Principal(user_id=caller.user_id, role=caller.role, groups=tuple(caller.groups))
    return is_allowed(principal, action, resource_of(record), grants_for(caller, record), int(time.time()))
