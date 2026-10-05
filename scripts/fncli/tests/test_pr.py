import importlib.util
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from fncli.cmds.pr import KINDS, PrConfig, file_for, new_branch_name

SPEC_MODULE = Path(__file__).parents[2] / "../dagster/app/models/pull_request_spec.py"


@pytest.fixture(scope="module")
def spec_model():
    """The Dagster code location's own model, loaded by path: the two must agree."""
    spec = importlib.util.spec_from_file_location("pull_request_spec", SPEC_MODULE.resolve())
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.PullRequestSpec


@pytest.fixture
def config():
    return PrConfig(pr_image="busybox:1")


def spec_of(content):
    return json.loads(content)["spec"]


def test_the_kinds():
    assert KINDS == ["watched", "unwatched", "invalid"]


def test_watched_file_is_under_the_watch_dir_and_validates(config, spec_model):
    path, content = file_for(config, "pr-1", "watched")

    assert path == "specs/pr-1.json"
    spec = spec_model.model_validate(spec_of(content))
    assert spec.image == "busybox:1" and spec.name == "pr-1"


def test_invalid_file_is_watched_but_fails_the_spec(config, spec_model):
    path, content = file_for(config, "pr-1", "invalid")

    assert path.startswith("specs/") and path.endswith(".json")
    with pytest.raises(ValidationError):
        spec_model.model_validate(spec_of(content))


def test_unwatched_file_is_outside_the_watch_dir(config):
    path, _ = file_for(config, "pr-1", "unwatched")

    assert not path.startswith(config.watch_dir)
    assert not path.endswith(".json")


def test_repo_path_is_the_admin_user_and_repo():
    assert PrConfig(gitea_admin_user="admin").repo_path == "admin/trigger"


def test_branch_names_are_prefixed_with_the_time():
    name = new_branch_name()

    assert name.startswith("pr-") and name[3:].isdigit()
