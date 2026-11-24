"""Who fncli logs in to nexus-api as: FN_USERNAME and FN_PASSWORD, else what it asks for, never a user it picks."""

import pytest

from fncli.cmds import common


@pytest.fixture(autouse=True)
def fresh(monkeypatch):
    monkeypatch.setattr(common, "_prompted", {})
    monkeypatch.delenv("FN_USERNAME", raising=False)
    monkeypatch.delenv("FN_PASSWORD", raising=False)


@pytest.fixture
def asked(monkeypatch):
    """What was asked for, answered with alice / secret"""
    questions = []
    monkeypatch.setattr(common.click, "prompt", lambda text, **kw: questions.append(text) or "alice")
    monkeypatch.setattr(common.getpass, "getpass", lambda text: questions.append(text) or "secret")
    return questions


def test_the_env_login_is_used_without_asking(monkeypatch, asked):
    monkeypatch.setenv("FN_USERNAME", "dagster")
    monkeypatch.setenv("FN_PASSWORD", "pw")

    assert common.login() == ("dagster", "pw")
    assert not asked


def test_an_unset_login_is_asked_for_once(asked):
    assert common.login() == ("alice", "secret")
    assert common.login() == ("alice", "secret")
    assert asked == ["nexus-api username", "Password for alice: "]


def test_only_the_missing_password_is_asked_for(monkeypatch, asked):
    monkeypatch.setenv("FN_USERNAME", "admin@example.org")

    assert common.login() == ("admin@example.org", "secret")
    assert asked == ["Password for admin@example.org: "]


def test_the_env_is_read_on_every_call(monkeypatch, asked):
    monkeypatch.setenv("FN_USERNAME", "dagster")
    monkeypatch.setenv("FN_PASSWORD", "pw")
    common.login()
    monkeypatch.setenv("FN_USERNAME", "admin@example.org")
    monkeypatch.setenv("FN_PASSWORD", "admin-pw")

    assert common.login() == ("admin@example.org", "admin-pw")
