from unittest.mock import MagicMock

import click
import pytest
from click.testing import CliRunner

from fncli.cmds import secret
from fncli.cmds.common import ResultsRepoConfig, TriggerRepoConfig
from fncli.cmds.secret import get_git_token, init_git_secret

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
    monkeypatch.setenv("TEST_GIT_PROVIDER", "github")
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


def test_github_token_is_stored_as_token(monkeypatch, backend_api):
    config = github_config(monkeypatch, GH_TOKEN="ghp_x")

    token = init_git_secret(config, MagicMock(), backend_api)

    backend_api.upsert_secret.assert_called_once_with("trigger-creds", {"TOKEN": "ghp_x"})
    assert token == "ghp_x"


def test_github_app_credentials_are_stored_instead_of_the_token(monkeypatch, backend_api):
    config = github_config(
        monkeypatch,
        GH_TOKEN="ghp_x",
        GH_APP_ID="123",
        GH_INSTALLATION_ID="456",
        GH_PRIVATE_KEY="-----BEGIN RSA PRIVATE KEY-----\nabc\n-----END RSA PRIVATE KEY-----",
    )

    token = init_git_secret(config, MagicMock(), backend_api)

    backend_api.upsert_secret.assert_called_once_with(
        "trigger-creds",
        {
            "APP_ID": "123",
            "INSTALLATION_ID": "456",
            "PRIVATE_KEY": "-----BEGIN RSA PRIVATE KEY-----\nabc\n-----END RSA PRIVATE KEY-----",
        },
    )
    assert token is None


def test_a_secret_that_does_not_hold_the_new_value_fails(backend_api, k8s):
    backend_api.upsert_secret.side_effect = lambda label, values: SECRET_RECORD
    k8s.update({"CLIENT_ID": "cid", "CLIENT_SECRET": "csec", "REFRESH_TOKEN": "stale"})
    gitea_api = MagicMock()
    gitea_api.authorize_oauth_app.return_value = OAUTH_TOKENS

    with pytest.raises(RuntimeError, match="does not hold the new REFRESH_TOKEN"):
        init_git_secret(TriggerRepoConfig(), gitea_api, backend_api)


def test_get_git_token_asks_the_backend_for_the_global_repository():
    backend_api = MagicMock()
    backend_api.find_results_repository.return_value = MagicMock(id=9)
    backend_api.get_repository_token.return_value = MagicMock(token="minted")

    token = get_git_token("results", ResultsRepoConfig(), backend_api)

    backend_api.find_results_repository.assert_called_once_with("http://gitea.fn.svc:3000/gitea_admin/results")
    backend_api.get_repository_token.assert_called_once_with("results", 9)
    assert token == "minted"


def test_get_git_token_names_the_command_that_registers_a_missing_repository():
    backend_api = MagicMock()
    backend_api.find_trigger_repository.return_value = None

    with pytest.raises(click.ClickException, match="init-backend-trigger-repo"):
        get_git_token("trigger", TriggerRepoConfig(), backend_api)


def run_command(command, monkeypatch, args, gitea_api=None):
    """Run a command with its repo config, Gitea and backend replaced, and return the Gitea API it used."""
    gitea_api = gitea_api or MagicMock()
    monkeypatch.setattr(secret, "load_repo_config", lambda entity, from_backend, project: TriggerRepoConfig())
    monkeypatch.setattr(secret, "build_git_api", lambda config: gitea_api)
    monkeypatch.setattr(secret, "build_backend_api", lambda config: "backend")
    result = CliRunner().invoke(command, args)
    assert result.exit_code == 0, result.output
    return gitea_api


@pytest.mark.parametrize("args, static_token", [([], False), (["--static-token"], True)])
def test_init_git_secret_command_selects_the_static_token_with_a_flag(monkeypatch, args, static_token):
    calls = []
    monkeypatch.setattr(secret, "init_git_secret", lambda **kwargs: calls.append(kwargs))

    run_command(secret.init_git_secret_command, monkeypatch, args)

    assert calls[0]["static_token"] is static_token


def test_delete_gitea_token_deletes_the_token_and_the_oauth_application(monkeypatch):
    gitea_api = MagicMock()

    run_command(secret.delete_gitea_token_command, monkeypatch, [], gitea_api)

    gitea_api.delete_token.assert_called_once_with("fn-sensor")
    gitea_api.delete_oauth_app.assert_called_once_with("fn-sensor")
