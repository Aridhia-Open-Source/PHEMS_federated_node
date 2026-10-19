"""Which backend login `link-set` uses: revoking is admin only, everything else uses the dagster system user."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from fncli.cmds import state


@pytest.fixture
def calls(monkeypatch):
    made = []
    monkeypatch.setattr(state, "find_project", lambda api, name: SimpleNamespace(id=1))
    monkeypatch.setattr(state, "first_link", lambda api, project_id, kind: {})
    monkeypatch.setattr(state, "link_key", lambda kind, link: 7)
    monkeypatch.setattr(state, "call", lambda api, method, path, **kw: made.append((api, method, path, kw)) or MagicMock())
    monkeypatch.setattr(state, "report", lambda response, expect: 0)
    return made


def test_revoking_uses_the_admin_login(calls):
    system, admin = MagicMock(name="system"), MagicMock(name="admin")

    state.set_link(system, "p", "trigger", None, "true", None, admin_api=admin)

    ((used, method, path, kwargs),) = calls
    assert used is admin and method == "PATCH" and path.endswith("/7") and kwargs["json"] == {"revoked": True}


def test_other_changes_keep_the_system_login_even_when_an_admin_is_given(calls):
    system, admin = MagicMock(name="system"), MagicMock(name="admin")

    state.set_link(system, "p", "results", "false", None, None, target_dir="out/", admin_api=admin)

    ((used, _, _, kwargs),) = calls
    assert used is system and kwargs["json"] == {"enabled": False, "target_dir": "out/"}


def test_revoking_without_an_admin_falls_back_to_the_system_login_and_says_so(calls, capsys):
    system = MagicMock(name="system")

    state.set_link(system, "p", "trigger", None, "true", None)

    ((used, _, _, _),) = calls
    assert used is system
    assert "FNCLI_ADMIN_USER" in capsys.readouterr().out


def test_target_dir_is_only_for_the_results_link(calls):
    with pytest.raises(Exception, match="results link"):
        state.set_link(MagicMock(), "p", "trigger", None, None, None, target_dir="x/")
