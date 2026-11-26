"""
The Cedar policies (ADR 0037): every case in nexus/api/authz/cases.yaml, then can() on real grants (a group's
grant, expired grants, the latest expiry per relation).
"""
import time
from datetime import datetime as dt, timedelta, timezone

import pytest
import yaml

from app.rules.authz import AUTHZ_DIR, GLOBAL, NEVER, Action, Principal, Resource, can, grants_for, is_allowed
from app.dtos.caller import Caller
from app.models.grant import Grant
from app.models.user import User

HOUR = 3600


def _expand(cases: list[dict]):
    for case in cases:
        types = case["resource"] if isinstance(case["resource"], list) else [case["resource"]]
        for type_ in types:
            for action in case.get("allow", []):
                yield pytest.param(case, type_, action, True, id=f"{case['name']} / {type_} / {action} allowed")
            for action in case.get("deny", []):
                yield pytest.param(case, type_, action, False, id=f"{case['name']} / {type_} / {action} denied")


CASES = list(_expand(yaml.safe_load((AUTHZ_DIR / "cases.yaml").read_text())["cases"]))


@pytest.mark.parametrize("case, type_, action, allowed", CASES)
def test_case(case, type_, action, allowed):
    now = int(time.time())
    expiries = {"never": NEVER, "future": now + HOUR, "expired": now - HOUR}
    principal = Principal(user_id="id-caller", role=case["role"], groups=tuple(case.get("groups", [])))
    attrs = {"revoked": case.get("revoked", False)} if type_ == "Dataset" else {}
    resource = Resource(type=type_, id="0" if type_ == "Global" else "7", attrs=attrs)
    grants = {relation: expiries[when] for relation, when in case.get("grants", {}).items()}
    assert is_allowed(principal, Action(action), resource, grants, now) is allowed


def test_every_action_is_covered():
    """Each checked action appears in the cases, allowed and denied."""
    checked = {(action, allowed) for _, _, action, allowed in (param.values for param in CASES)}
    for action in Action:
        if action != Action.UNCHECKED:
            assert (action, True) in checked and (action, False) in checked, action


def caller(role="Users", groups=(), user_id="id-alice") -> Caller:
    return Caller(user_id=user_id, role=role, groups=list(groups), user=User(id=user_id, username=user_id))


def grant(record, relation, subject_type="user", subject_id="id-alice", expires_at=None) -> Grant:
    row = Grant(
        object_type=record.authz_type, object_id=record.id, relation=relation,
        subject_type=subject_type, subject_id=subject_id, expires_at=expires_at,
    )
    row.add()
    return row


def test_group_grant(project):
    grant(project, "write", subject_type="group", subject_id="/studies/uc1")
    assert can(caller("Administrator", ["/studies/uc1"]), Action.WRITE, project)
    assert not can(caller("Administrator", ["/studies/uc2"]), Action.WRITE, project)
    assert not can(caller("Administrator", ["/studies/uc1"]), Action.MANAGE, project)
    assert not can(caller("Users", ["/studies/uc1"]), Action.WRITE, project)


def test_expired_grant_is_left_out(project):
    grant(project, "execute", expires_at=dt.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=1))
    assert grants_for(caller(), project) == {}
    assert not can(caller(), Action.EXECUTE, project)


def test_latest_expiry_per_relation(project):
    """The user's own grant and its group's grant fold to the later expiry; no expiry wins."""
    soon = dt.now(timezone.utc).replace(tzinfo=None) + timedelta(hours=1)
    grant(project, "execute", expires_at=soon)
    grant(project, "execute", subject_type="group", subject_id="/studies/uc1", expires_at=soon + timedelta(days=1))
    grant(project, "read", expires_at=soon)
    grant(project, "read", subject_type="group", subject_id="/studies/uc1")
    grants = grants_for(caller(groups=["/studies/uc1"]), project)
    later = soon + timedelta(days=1)
    assert grants["execute"] == int(later.replace(tzinfo=timezone.utc).timestamp())
    assert grants["read"] == NEVER


def test_other_users_grant_does_not_count(project):
    grant(project, "manage", subject_id="id-bob")
    assert not can(caller(), Action.READ, project)


def test_global_and_revoked(project, dataset):
    assert can(caller("Administrator", ["/roles/admins"]), Action.WRITE, GLOBAL)
    assert not can(caller(), Action.WRITE, GLOBAL)
    grant(dataset, "manage")
    assert can(caller(), Action.EXECUTE, dataset)
    dataset.revoked = True
    assert not can(caller(), Action.EXECUTE, dataset)
