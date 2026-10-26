"""Which backend login `resource-set` uses: revoking is admin only, everything else uses the dagster system user."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from fncli.cmds import state


@pytest.fixture
def calls(monkeypatch):
    made = []
    monkeypatch.setattr(state, "find_project", lambda api, name: SimpleNamespace(id=1))
    monkeypatch.setattr(state, "first_resource", lambda api, project_id, kind: {})
    monkeypatch.setattr(state, "resource_key", lambda kind, resource: 7)
    monkeypatch.setattr(state, "call", lambda api, method, path, **kw: made.append((api, method, path, kw)) or MagicMock())
    monkeypatch.setattr(state, "report", lambda response, expect: 0)
    return made


def test_revoking_uses_the_admin_login(calls):
    system, admin = MagicMock(name="system"), MagicMock(name="admin")

    state.set_resource(system, "p", "trigger", None, "true", None, admin_api=admin)

    ((used, method, path, kwargs),) = calls
    assert used is admin and method == "PATCH" and path.endswith("/7") and kwargs["json"] == {"revoked": True}


def test_other_changes_keep_the_system_login_even_when_an_admin_is_given(calls):
    system, admin = MagicMock(name="system"), MagicMock(name="admin")

    state.set_resource(system, "p", "results", "false", None, None, target_dir="out/", admin_api=admin)

    ((used, _, _, kwargs),) = calls
    assert used is system and kwargs["json"] == {"enabled": False, "target_dir": "out/"}


def test_target_dir_is_only_for_the_results_resource(calls):
    with pytest.raises(Exception, match="results resource"):
        state.set_resource(MagicMock(), "p", "trigger", None, None, None, target_dir="x/")


def test_enabling_a_project_with_backfill_sends_both(calls):
    state.set_project(MagicMock(), "p", "true", True, None)

    ((_, method, path, kwargs),) = calls
    assert (method, path, kwargs["json"]) == ("PATCH", "/projects/1", {"enabled": True, "backfill": True})


def test_enabling_a_project_without_backfill_sends_only_enabled(calls):
    state.set_project(MagicMock(), "p", "true", False, None)

    ((_, _, _, kwargs),) = calls
    assert kwargs["json"] == {"enabled": True}


def test_disabling_a_project_sends_enabled_false(calls):
    state.set_project(MagicMock(), "p", "false", False, None)

    ((_, _, _, kwargs),) = calls
    assert kwargs["json"] == {"enabled": False}


def test_project_set_needs_a_flag(calls):
    with pytest.raises(Exception, match="--enabled, --revoked and/or --backfill"):
        state.set_project(MagicMock(), "p", None, False, None)


def test_project_set_command_options():
    assert {param.name for param in state.project_set_command.params} == {"enabled", "revoked", "backfill", "project", "expect"}


def test_revoking_a_project_uses_the_admin_login(calls):
    system, admin = MagicMock(name="system"), MagicMock(name="admin")

    state.set_project(system, "p", None, False, None, revoked="true", admin_api=admin)

    ((used, method, path, kwargs),) = calls
    assert used is admin and (method, path, kwargs["json"]) == ("PATCH", "/projects/1", {"revoked": True})


def test_enabling_a_project_keeps_the_system_login_even_when_an_admin_is_given(calls):
    system, admin = MagicMock(name="system"), MagicMock(name="admin")

    state.set_project(system, "p", "true", False, None, admin_api=admin)

    ((used, _, _, kwargs),) = calls
    assert used is system and kwargs["json"] == {"enabled": True}


def test_revoking_a_global_resource_uses_the_admin_login(calls):
    system, admin = MagicMock(name="system"), MagicMock(name="admin")

    state.set_global(system, "p", "results", None, None, revoked="false", admin_api=admin)

    ((used, method, path, kwargs),) = calls
    assert used is admin and (method, path, kwargs["json"]) == ("PATCH", "/global/repositories/results/7", {"revoked": False})


def test_turning_a_global_resource_off_keeps_the_system_login(calls):
    system, admin = MagicMock(name="system"), MagicMock(name="admin")

    state.set_global(system, "p", "secret", "false", None, admin_api=admin)

    ((used, _, path, kwargs),) = calls
    assert used is system and path == "/global/secrets/7" and kwargs["json"] == {"enabled": False}


def test_turning_a_secret_off_sends_enabled_false(calls):
    state.set_secret(MagicMock(), "trigger-secret", "false", None)

    ((_, method, path, kwargs),) = calls
    assert (method, path, kwargs["json"]) == ("PATCH", "/global/secrets/trigger-secret", {"enabled": False})


def test_only_repositories_can_be_revoked_globally(calls):
    with pytest.raises(Exception, match="trigger and results"):
        state.set_global(MagicMock(), "p", "dataset", None, None, revoked="true")


def test_global_set_needs_a_flag(calls):
    with pytest.raises(Exception, match="--enabled and/or --revoked"):
        state.set_global(MagicMock(), "p", "trigger", None, None)


def test_second_project_is_created_disabled_assigned_then_enabled(monkeypatch):
    sent = []

    def respond(api, method, path, **kwargs):
        sent.append((method, path, kwargs.get("json")))
        return SimpleNamespace(status_code=201, content=b"{}", json=lambda: {"id": 5}, text="")

    monkeypatch.setattr(state, "find_project", lambda api, name: SimpleNamespace(id=1))
    monkeypatch.setattr(state, "project_resources", lambda api, pid: {
        "secret": [{"secret": {"label": "s"}}], "dataset": [{"dataset": {"id": 2}}], "trigger": [],
        "results": [{"results_repository": {"id": 3}, "target_dir": "out"}],
    })
    monkeypatch.setattr(state, "call", respond)

    state.setup_second_project(MagicMock(), SimpleNamespace(project_name="p"), "two")

    assert sent[0] == ("POST", "/projects", {"name": "two"})  # no enabled: a new project is disabled
    assert sent[-1] == ("PATCH", "/projects/5", {"enabled": True})
    assert [method for method, _, _ in sent[1:-1]] == ["PUT", "PUT", "PUT"]
