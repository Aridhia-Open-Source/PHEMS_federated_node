"""What `resource-set`, `project-set` and `global-set` send, with the one login fncli is given (revoking needs an Administrator)."""

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


def test_revoking_uses_the_login_given(calls):
    api = MagicMock(name="api")

    state.set_resource(api, "p", "trigger", None, "true", None)

    ((used, method, path, kwargs),) = calls
    assert used is api and method == "PATCH" and path.endswith("/7") and kwargs["json"] == {"revoked": True}


def test_other_changes_use_the_login_given(calls):
    api = MagicMock(name="api")

    state.set_resource(api, "p", "results", "false", None, None, target_dir="out/")

    ((used, _, _, kwargs),) = calls
    assert used is api and kwargs["json"] == {"enabled": False, "target_dir": "out/"}


def test_target_dir_is_only_for_the_results_resource(calls):
    with pytest.raises(Exception, match="results resource"):
        state.set_resource(MagicMock(), "p", "trigger", None, None, None, target_dir="x/")


@pytest.mark.parametrize("kind", ["trigger", "results"])
def test_base_branch_is_sent_for_the_trigger_and_results_resources(calls, kind):
    state.set_resource(MagicMock(), "p", kind, None, None, None, base_branch="release")

    ((_, method, _, kwargs),) = calls
    assert (method, kwargs["json"]) == ("PATCH", {"base_branch": "release"})


def test_base_branch_is_not_for_a_dataset_resource(calls):
    with pytest.raises(Exception, match="trigger and results"):
        state.set_resource(MagicMock(), "p", "dataset", None, None, None, base_branch="release")


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
    assert {param.name for param in state.project_set_command.params} == {"enabled", "revoked", "backfill", "project", "expect", "context"}


def test_revoking_a_project_uses_the_login_given(calls):
    api = MagicMock(name="api")

    state.set_project(api, "p", None, False, None, revoked="true")

    ((used, method, path, kwargs),) = calls
    assert used is api and (method, path, kwargs["json"]) == ("PATCH", "/projects/1", {"revoked": True})


def test_enabling_a_project_uses_the_login_given(calls):
    api = MagicMock(name="api")

    state.set_project(api, "p", "true", False, None)

    ((used, _, _, kwargs),) = calls
    assert used is api and kwargs["json"] == {"enabled": True}


def test_revoking_a_global_resource_uses_the_login_given(calls):
    api = MagicMock(name="api")

    state.set_global(api, "p", "results", None, None, revoked="false")

    ((used, method, path, kwargs),) = calls
    assert used is api and (method, path, kwargs["json"]) == ("PATCH", "/global/repositories/results/7", {"revoked": False})


def test_turning_a_global_resource_off_uses_the_login_given(calls):
    api = MagicMock(name="api")

    state.set_global(api, "p", "secret", "false", None)

    ((used, _, path, kwargs),) = calls
    assert used is api and path == "/global/secrets/7" and kwargs["json"] == {"enabled": False}


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
