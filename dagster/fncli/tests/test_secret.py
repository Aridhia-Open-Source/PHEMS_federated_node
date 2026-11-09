import logging
from unittest.mock import MagicMock

import click
import pytest
from click.testing import CliRunner

from fncli.cmds import secret
from fncli.cmds.common import ResultsRepoConfig, TriggerRepoConfig
from fncli.cmds.secret import init_git_secret

SECRET_RECORD = {"label": "trigger-creds", "key": "trigger-creds-abc", "namespace": "fn"}
OAUTH_TOKENS = {
    "client_id": "cid", "client_secret": "csec", "access_token": "access", "refresh_token": "refresh", "expires_in": 3600,
}


@pytest.fixture
def k8s(monkeypatch):
    """The K8s secret: whatever the backend was given to store."""
    stored = {}
    monkeypatch.setattr(secret, "get_k8s_secret", lambda secret_name, namespace, key: stored[key])
    return stored


@pytest.fixture
def backend_api(k8s):
    api = MagicMock()
    api.upsert_secret.side_effect = lambda label, values: k8s.update(values) or SECRET_RECORD
    return api


def github_config(monkeypatch, **env):
    monkeypatch.setenv("TEST_TRIGGER_REPO_URI", "https://github.com/aridhia/trigger")
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    return TriggerRepoConfig()


def test_gitea_defaults_to_oauth_credentials(backend_api):
    gitea_api = MagicMock()
    gitea_api.authorize_oauth_app.return_value = OAUTH_TOKENS

    token = init_git_secret(TriggerRepoConfig(), gitea_api, backend_api)

    gitea_api.authorize_oauth_app.assert_called_once_with("fn-sensor")
    gitea_api.replace_token.assert_not_called()
    backend_api.upsert_secret.assert_called_once_with(
        "trigger-creds", {"CLIENT_ID": "cid", "CLIENT_SECRET": "csec", "REFRESH_TOKEN": "refresh"}
    )
    assert token == "access"


def test_each_gitea_entity_has_its_own_oauth_application(backend_api):
    gitea_api = MagicMock()
    gitea_api.authorize_oauth_app.return_value = OAUTH_TOKENS

    init_git_secret(ResultsRepoConfig(), gitea_api, backend_api)

    gitea_api.authorize_oauth_app.assert_called_once_with("fn-results")


def test_static_token_flag_stores_a_personal_access_token(backend_api):
    gitea_api = MagicMock()
    gitea_api.replace_token.return_value = "pat"

    token = init_git_secret(TriggerRepoConfig(), gitea_api, backend_api, static_token=True)

    gitea_api.replace_token.assert_called_once_with("fn-sensor", ["read:repository"])
    gitea_api.authorize_oauth_app.assert_not_called()
    backend_api.upsert_secret.assert_called_once_with("trigger-creds", {"TOKEN": "pat"})
    assert token == "pat"


def test_github_app_credentials_are_stored(monkeypatch, backend_api):
    config = github_config(
        monkeypatch,
        GH_APP_ID="123",
        GH_INSTALLATION_ID="456",
        GH_PRIVATE_KEY="-----BEGIN RSA PRIVATE KEY-----\nabc\n-----END RSA PRIVATE KEY-----",
    )

    token = init_git_secret(config, None, backend_api)

    backend_api.upsert_secret.assert_called_once_with(
        "trigger-creds",
        {
            "APP_ID": "123",
            "INSTALLATION_ID": "456",
            "PRIVATE_KEY": "-----BEGIN RSA PRIVATE KEY-----\nabc\n-----END RSA PRIVATE KEY-----",
        },
    )
    assert token is None


def test_github_without_the_app_credentials_fails_and_stores_nothing(monkeypatch, backend_api):
    config = github_config(monkeypatch, GH_APP_ID="123")

    with pytest.raises(click.ClickException, match="GH_APP_ID, GH_INSTALLATION_ID and GH_PRIVATE_KEY"):
        init_git_secret(config, None, backend_api)

    backend_api.upsert_secret.assert_not_called()


def test_a_secret_that_does_not_hold_the_new_value_fails(backend_api, k8s):
    backend_api.upsert_secret.side_effect = lambda label, values: SECRET_RECORD
    k8s.update({"CLIENT_ID": "cid", "CLIENT_SECRET": "csec", "REFRESH_TOKEN": "stale"})
    gitea_api = MagicMock()
    gitea_api.authorize_oauth_app.return_value = OAUTH_TOKENS

    with pytest.raises(RuntimeError, match="does not hold the new REFRESH_TOKEN"):
        init_git_secret(TriggerRepoConfig(), gitea_api, backend_api)


def test_delete_gitea_token_deletes_the_token_and_the_oauth_application(monkeypatch):
    gitea_api = MagicMock()
    monkeypatch.setattr(secret, "load_repo_config", lambda entity, from_backend, project: TriggerRepoConfig())
    monkeypatch.setattr(secret, "build_gitea_api", lambda config: gitea_api)

    result = CliRunner().invoke(secret.delete_gitea_token_command, [])

    assert result.exit_code == 0, result.output
    gitea_api.delete_token.assert_called_once_with("fn-sensor")
    gitea_api.delete_oauth_app.assert_called_once_with("fn-sensor")


def test_verify_git_secret_reads_the_repo_with_the_client_for_its_record(monkeypatch, caplog):
    caplog.set_level(logging.INFO, logger="secret")
    git_api = MagicMock()
    monkeypatch.setattr(secret, "load_repo_config", lambda entity, from_backend, project: TriggerRepoConfig())
    monkeypatch.setattr(secret, "build_git_api", lambda config: git_api)

    result = CliRunner().invoke(secret.verify_git_secret_command, [])

    assert result.exit_code == 0, result.output
    git_api.get_default_branch.assert_called_once_with("gitea_admin/trigger")
    assert "The gitea provider accepted the token for gitea_admin/trigger" in caplog.text
