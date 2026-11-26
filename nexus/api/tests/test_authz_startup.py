"""
Startup checks of the Cedar policies (ADR 0037): a policy or schema that fails validation, an Action missing from
the schema, a rule without an @id or a roles.yaml that disagrees with the rules or the node roles stops create_app;
each new policy hash writes one policy_versions row.
"""
import shutil

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient

from app import create_app
from app.rules import authz
from app.rules.authz import AUTHZ_DIR, PolicyError
from app.database.base_model import engine
from app.models.policy_version import PolicyVersion


@pytest.fixture
def policy_dir(tmp_path, monkeypatch):
    """A copy of the policy files that create_app reads instead of the repo's."""
    for name in authz.POLICY_FILES:
        shutil.copy(AUTHZ_DIR / name, tmp_path / name)
    monkeypatch.setattr(authz, "AUTHZ_DIR", tmp_path)
    authz.load_policies.cache_clear()
    yield tmp_path
    authz.load_policies.cache_clear()


def edit(path, old: str, new: str) -> None:
    text = path.read_text()
    assert old in text
    path.write_text(text.replace(old, new))


def test_repo_policies_are_valid():
    authz.check_policies()


def test_invalid_policy_stops_startup(policy_dir):
    edit(policy_dir / "policies.cedar", "resource.revoked", "resource.revokd")
    with pytest.raises(PolicyError, match="revokd"):
        create_app()


def test_unparsable_policy_stops_startup(policy_dir):
    (policy_dir / "policies.cedar").write_text("permit (principal, action, resource")
    with pytest.raises(PolicyError):
        create_app()


def test_action_missing_from_schema_stops_startup(policy_dir):
    """operate is in Action but its model actions are taken out of the schema (and the rules, which would fail first)."""
    schema = (policy_dir / "schema.cedarschema").read_text()
    start = schema.index("// operate")
    end = schema.index("// manage")
    (policy_dir / "schema.cedarschema").write_text(
        schema[:start].replace("action read, write, execute, assign, operate, manage",
                               "action read, write, execute, assign, manage") + schema[end:]
    )
    policies = (policy_dir / "policies.cedar").read_text()
    start = policies.index("// operate turns")
    end = policies.index("// Any current grant")
    (policy_dir / "policies.cedar").write_text(policies[:start] + policies[end:])
    with pytest.raises(PolicyError, match="Action operate"):
        create_app()


def test_rule_without_an_id_stops_startup(policy_dir):
    edit(policy_dir / "policies.cedar", '@id("dataset.execute.revoked")\n', "")
    with pytest.raises(PolicyError, match="without an @id"):
        create_app()


def test_permission_without_a_rule_stops_startup(policy_dir):
    edit(policy_dir / "roles.yaml", "Service: [global.write.all]", "Service: [global.write.all, global.delete.all]")
    with pytest.raises(PolicyError, match="global.delete.all"):
        create_app()


def test_unknown_role_stops_startup(policy_dir):
    edit(policy_dir / "roles.yaml", "Users: []", "Users: []\nVisitor: []")
    with pytest.raises(PolicyError, match="Visitor"):
        create_app()


def test_role_missing_from_roles_stops_startup(policy_dir):
    edit(policy_dir / "roles.yaml", "Users: []  # grants only", "")
    with pytest.raises(PolicyError, match="node roles"):
        create_app()


def rows() -> list[str]:
    with engine.connect() as conn:
        return list(conn.scalars(sa.select(PolicyVersion.hash).order_by(PolicyVersion.id)))


def test_policy_versions(client, policy_dir):
    """client started the app with the repo's files: one row. A restart adds none; a new hash adds one."""
    first = rows()
    assert len(first) == 1
    with TestClient(create_app()):
        pass
    assert rows() == first
    edit(policy_dir / "cases.yaml", "cases:", "# a new case comment\ncases:")
    authz.load_policies.cache_clear()
    with TestClient(create_app()):
        pass
    assert len(rows()) == 2 and rows()[0] == first[0]
