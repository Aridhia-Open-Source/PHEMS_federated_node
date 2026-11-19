from unittest.mock import MagicMock

import pytest

from app.definitions.sensors.git.base import GitAPIFactory
from app.gitea import GiteaAPI
from app.github import GithubAPI
from app.models import GitToken, ResultsRepository, TriggerRepository
from app.tests.conftest import SAMPLE_PROVIDER, SAMPLE_TRIGGER_REPOSITORY


def repo(provider_type, api_uri):
    provider = {**SAMPLE_PROVIDER, "type": provider_type, "api_uri": api_uri}
    return TriggerRepository(**{**SAMPLE_TRIGGER_REPOSITORY, "provider": provider})


@pytest.fixture
def backend_api():
    api = MagicMock()
    api.get_repository_token.return_value = GitToken(token="tok", expires_at="2026-01-01T01:00:00Z")
    return api


@pytest.fixture
def factory(backend_api):
    return GitAPIFactory(backend_api)


def test_github_repository_gets_a_github_api(factory):
    api = factory.for_repository(repo("github", "https://api.github.com"))

    assert isinstance(api, GithubAPI)
    assert api.client._base_uri == "https://api.github.com"
    assert api.client.token == "tok"


def test_gitea_repository_gets_a_gitea_api_on_its_api_uri(factory):
    api = factory.for_repository(repo("gitea", "http://gitea.fn.svc:3000/api/v1/"))

    assert isinstance(api, GiteaAPI)
    assert api.client._base_uri == "http://gitea.fn.svc:3000/api/v1"
    assert api.client.token == "tok"


def test_the_token_of_a_trigger_repository_comes_from_the_backend(factory, backend_api):
    factory.for_repository(repo("github", "https://api.github.com"))

    backend_api.get_repository_token.assert_called_once_with("trigger", 1, None)


def test_the_token_of_a_results_repository_comes_from_the_backend(factory, backend_api):
    results = ResultsRepository(**{**SAMPLE_TRIGGER_REPOSITORY, "id": 2})

    factory.for_repository(results)

    backend_api.get_repository_token.assert_called_once_with("results", 2, None)


def test_the_project_the_work_is_for_is_passed_on(factory, backend_api):
    factory.for_repository(repo("github", "https://api.github.com"), 4)

    backend_api.get_repository_token.assert_called_once_with("trigger", 1, 4)


def test_each_client_asks_for_its_own_token(factory, backend_api):
    factory.for_repository(repo("github", "https://api.github.com"))
    factory.for_repository(repo("github", "https://api.github.com"))

    assert backend_api.get_repository_token.call_count == 2


def test_an_unknown_provider_is_rejected(factory):
    with pytest.raises(ValueError, match="Unsupported git provider 'gitlab'"):
        factory.for_repository(repo("gitlab", "https://gitlab.com/api/v4"))


def test_a_refusal_by_the_backend_is_raised(factory, backend_api):
    backend_api.get_repository_token.side_effect = PermissionError("revoked")

    with pytest.raises(PermissionError, match="revoked"):
        factory.for_repository(repo("github", "https://api.github.com"))
