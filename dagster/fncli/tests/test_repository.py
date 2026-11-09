from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from fncli.cmds import repository
from fncli.cmds.common import ResultsRepoConfig, TriggerRepoConfig

PROJECT = SimpleNamespace(id=7)


@pytest.fixture
def backend_api():
    api = MagicMock()
    api.get_or_create_trigger_repository.return_value = SimpleNamespace(
        id=1, uri="u", provider=SimpleNamespace(name="p", api_uri="a"), secret=SimpleNamespace(label="l"),
    )
    return api


def test_the_trigger_repo_is_assigned_with_the_given_base_branch(backend_api):
    repository.init_backend_trigger_repo(TriggerRepoConfig(), backend_api, PROJECT, "release")

    assert backend_api.get_or_assign_repository.call_args.kwargs["base_branch"] == "release"


def test_the_results_repo_is_assigned_with_the_given_base_branch(backend_api):
    repository.init_backend_results_repo(ResultsRepoConfig(), backend_api, PROJECT, "release")

    assert backend_api.get_or_assign_results_repository.call_args.args[-1] == "release"
