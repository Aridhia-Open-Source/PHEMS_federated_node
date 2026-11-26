"""
The Cedar access check (ADR 0037). The rules are nexus/api/authz/policies.cedar, checked against
schema.cedarschema; this module builds each request from the caller, the record and the caller's grants on it,
and asks Cedar. Routes declare an Access dependency, which loads their record, checks it and hands it over; other
code calls can() or require(). A deny is a 409 naming the record's owned_by user.

cedarpy is only called from this module, so swapping the wrapper stays local.
"""
import hashlib
import inspect
import time
from datetime import timezone
from dataclasses import dataclass, field
from enum import StrEnum
from functools import cache
from http import HTTPStatus
from pathlib import Path

import cedarpy
import sqlalchemy as sa
from fastapi import Depends
from sqlalchemy.dialects.postgresql import insert

from app.database.base_model import db, engine
from app.dtos.caller import Caller
from app.helpers.exceptions import DBRecordNotFoundError, InvalidRequest
from app.helpers.wrappers import get_caller, system_only
from app.models.grant import GROUP, USER, Grant
from app.models.policy_version import PolicyVersion
from app.models.secret import Secret

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


def require(caller: Caller, action: Action, record) -> None:
    """can(), or a 409 naming the record's owned_by user."""
    if can(caller, action, record):
        return
    if isinstance(record, Global):
        raise InvalidRequest(
            f"Only admins and the operator can {action} global records", HTTPStatus.CONFLICT
        )
    owner = record.owned_by.username if getattr(record, "owned_by", None) else "nobody"
    raise InvalidRequest(f"You cannot {action} {record!r}; it is owned by {owner}", HTTPStatus.CONFLICT)


# The path parameter each checked model is loaded by, and its type
PATH_PARAMS = {
    "Project": ("project_id", int),
    "Dataset": ("dataset_id", int),
    "GitProvider": ("provider_id", int),
    "Secret": ("label", str),
    "TriggerRepository": ("repo_id", int),
    "ResultsRepository": ("repo_id", int),
}


def _load(model, key):
    """The record the path names, 404 if missing. Secrets are addressed by label."""
    if model is Secret:
        secret = Secret.query.filter(Secret.label == key).one_or_none()
        if secret is None:
            raise DBRecordNotFoundError(f"Secret {key} does not exist")
        return secret
    return model.get_by_id(key)


class Access:
    """
    The record check every route declares (ADR 0037), keyword arguments only:
    - Access(model=Dataset, action=Action.WRITE): loads the record from the path (404 if missing), checks the
      caller may do the action on it (409 if not) and returns it, so the handler takes the record from here;
    - Access(model=Global, action=Action.WRITE): a global create, checked on Global::"0"; returns GLOBAL;
    - Access(action=Action.UNCHECKED): no check and no token needed; the route says why in a comment.
    create_app refuses to start if a route has none (see routes_without_access).
    """

    def __init__(self, *, action: Action, model=None):
        if action == Action.UNCHECKED and model is not None:
            raise TypeError("Access(action=UNCHECKED) takes no model")
        if action != Action.UNCHECKED and model is None:
            raise TypeError(f"Access(action={action}) needs a model")
        self.model = model
        self.action = action
        params = []
        if action != Action.UNCHECKED:
            params.append(inspect.Parameter(
                "caller", inspect.Parameter.KEYWORD_ONLY, default=Depends(get_caller), annotation=Caller,
            ))
            if model is not Global:
                name, type_ = PATH_PARAMS[model.authz_type]
                params.insert(0, inspect.Parameter(name, inspect.Parameter.KEYWORD_ONLY, annotation=type_))
        # FastAPI reads the dependency's parameters from here: the path parameter and the caller
        self.__signature__ = inspect.Signature(params)

    def __call__(self, caller: Caller | None = None, **path):
        if self.action == Action.UNCHECKED:
            return None
        record = GLOBAL if self.model is Global else _load(self.model, next(iter(path.values())))
        require(caller, self.action, record)
        return record

    def __repr__(self):
        model = f"model={self.model.__name__}, " if self.model else ""
        return f"Access({model}action={self.action})"


# Dagster's pipeline state writes and token mints: Dagster carries out what nexus-api decided (ADR 0021) for every
# record, holds no grants and gets no write from Cedar, so these are gated by its role, not checked per record
SYSTEM_ONLY = [Depends(system_only), Depends(Access(action=Action.UNCHECKED))]


# The methods create_app checks for an Access dependency; #688 adds GET
CHECKED_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


def _has_access(dependant) -> bool:
    return any(isinstance(dep.call, Access) or _has_access(dep) for dep in dependant.dependencies)


def api_routes(routers) -> list:
    """The routes of the routers, with their prefix and router dependencies (the app's own list nests them)."""
    return [route for router in routers for route in router.routes if hasattr(route, "dependant")]


def routes_without_access(routers) -> list[str]:
    """Every route with a checked method and no Access dependency, as "METHOD path"."""
    return sorted(
        f"{method} {route.path}"
        for route in api_routes(routers) if not _has_access(route.dependant)
        for method in route.methods & CHECKED_METHODS
    )
