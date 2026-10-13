from unittest.mock import patch

import pytest

from app.definitions.sensors.git.base import GitAPIFactory
from app.gitea import GiteaAPI
from app.github import GithubAPI
from app.models import TriggerRepository
from app.tests.conftest import SAMPLE_REPOSITORY_OBJ


def repo(provider, api_uri):
    return TriggerRepository(**{**SAMPLE_REPOSITORY_OBJ, "provider": provider, "api_uri": api_uri})


@pytest.fixture
def secret_get():
    with patch("app.definitions.sensors.git.base.SecretProvider.get", return_value="tok") as get:
        yield get


def test_github_repository_gets_a_github_api(secret_get):
    api = GitAPIFactory().for_repository(repo("github", "https://api.github.com"))

    assert isinstance(api, GithubAPI)
    assert api.client._base_uri == "https://api.github.com"
    assert api.client.token == "tok"


def test_gitea_repository_gets_a_gitea_api_on_its_api_uri(secret_get):
    api = GitAPIFactory().for_repository(repo("gitea", "http://gitea.fn.svc:3000/api/v1/"))

    assert isinstance(api, GiteaAPI)
    assert api.client._base_uri == "http://gitea.fn.svc:3000/api/v1"
    assert api.client.token == "tok"


def test_the_token_is_read_from_the_repository_secret(secret_get):
    GitAPIFactory().for_repository(repo("github", "https://api.github.com"))

    secret_get.assert_called_once_with("git-token-abc", "fn", "TOKEN")


def test_an_unknown_provider_is_rejected(secret_get):
    with pytest.raises(ValueError, match="Unsupported git provider 'gitlab'"):
        GitAPIFactory().for_repository(repo("gitlab", "https://gitlab.com/api/v4"))
