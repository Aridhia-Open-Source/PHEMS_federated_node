"""`fncli trigger` (fncli.cmds.trigger): the way and the project it uses, and the pull request it opens, with the node faked."""

import json
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

from click.testing import CliRunner
import pytest
import yaml

from fncli.cmds import pr, trigger
from fncli.cmds.trigger import trigger_command
from fncli.tests.conftest import trigger_config

TRIGGER = {"spec": {"image": "busybox:1", "env": {"A": "1"}}}
NODE = {"url": "http://nexus:5000", "kube_context": "kind-fn", "keycloak_namespace": "keycloak", "gitea_admin_user": "boss"}


@pytest.fixture(autouse=True)
def restore_env():
    with patch.dict(os.environ):
        yield


@pytest.fixture
def context_file(tmp_path, monkeypatch):
    path = tmp_path / "context.yaml"
    path.write_text(yaml.safe_dump({"node": NODE, "defaults": {"project": "demo-gitea", "trigger_type": "pr"}}))
    folder = tmp_path / "triggers" / "examples"
    folder.mkdir(parents=True)
    (folder / "demo.json").write_text(json.dumps(TRIGGER))
    monkeypatch.setenv("FNCLI_CONTEXT", str(path))
    monkeypatch.delenv("FNCLI_DEFAULT_PROJECT", raising=False)
    monkeypatch.delenv("FNCLI_DEFAULT_TRIGGER_TYPE", raising=False)
    monkeypatch.chdir(tmp_path)
    return path


@pytest.fixture
def ran(monkeypatch, context_file):
    """The node and the pull request replaced by recorders"""
    ran = {}
    monkeypatch.setattr(trigger, "open_target", lambda context: ran.setdefault("opened", context.path))
    monkeypatch.setattr(trigger, "trigger_pr", lambda *args, **options: ran.update(trigger_pr=(args, options)) or None)
    return ran


def invoke(*args):
    return CliRunner().invoke(trigger_command, list(args))


def test_with_no_flags_it_uses_the_default_project_and_way_and_says_so_on_the_first_line(ran, context_file, tmp_path):
    result = invoke("examples/demo.json")

    assert result.exit_code == 0, result.output
    assert result.output.splitlines()[0] == f"Using the defaults of {context_file}: project demo-gitea, via pr"
    args, options = ran["trigger_pr"]
    assert args[2:] == ("demo-gitea", tmp_path / "triggers" / "examples" / "demo.json", False, False, 300)


def test_flags_beat_the_defaults_and_nothing_is_said(ran):
    result = invoke("examples/demo.json", "--project", "other", "--pr", "--merge", "--watch", "--timeout", "9")

    assert result.exit_code == 0, result.output
    assert "Using the defaults" not in result.output
    assert ran["trigger_pr"][0][2] == "other" and ran["trigger_pr"][0][4:] == (True, True, 9)


def test_only_what_came_from_a_default_is_named(ran, context_file):
    result = invoke("examples/demo.json", "--pr")
    assert result.output.splitlines()[0] == f"Using the defaults of {context_file}: project demo-gitea"

    result = invoke("examples/demo.json", "--project", "other")
    assert result.output.splitlines()[0] == f"Using the defaults of {context_file}: via pr"


def test_the_env_wins_over_the_context_defaults(ran, monkeypatch):
    monkeypatch.setenv("FNCLI_DEFAULT_PROJECT", "from-env")

    result = invoke("examples/demo.json")

    assert result.output.splitlines()[0].endswith(": project from-env, via pr")
    assert ran["trigger_pr"][0][2] == "from-env"


def test_the_node_is_opened_and_its_context_and_client_go_to_the_pull_request_not_the_env(ran, context_file):
    invoke("examples/demo.json")

    context, api = ran["trigger_pr"][0][:2]
    assert ran["opened"] == context_file
    assert context.node.url == "http://nexus:5000" and context.node.gitea_admin_user == "boss"
    assert api == context_file  # what open_target returned
    assert "NEXUS_API_URL" not in os.environ and "GITEA_ADMIN_USER" not in os.environ


def test_api_is_reserved_and_says_it_is_not_built(ran):
    result = invoke("examples/demo.json", "--api")

    assert result.exit_code == 1
    assert "--api is not built yet" in result.output
    assert "trigger_pr" not in ran and "opened" not in ran


def test_a_default_way_of_api_is_the_same_error(ran, monkeypatch):
    monkeypatch.setenv("FNCLI_DEFAULT_TRIGGER_TYPE", "api")

    result = invoke("examples/demo.json")

    assert result.exit_code == 1 and "--api is not built yet" in result.output


def test_pr_and_api_together_are_a_usage_error(ran):
    assert invoke("examples/demo.json", "--pr", "--api").exit_code == 2


def test_no_project_and_no_default_is_a_usage_error(ran, context_file):
    context_file.write_text(yaml.safe_dump({"node": NODE}))

    result = invoke("examples/demo.json")

    assert result.exit_code == 2
    assert "Give --project and --pr or --api, or set them in the defaults of the context file" in result.output
    assert "Using the defaults" not in result.output


def test_a_trigger_file_that_is_not_found_is_a_usage_error(ran):
    result = invoke("nope.json")

    assert result.exit_code == 2 and "nope.json not found, as given or under triggers/ from here up" in result.output


def test_the_pull_request_is_the_trigger_file_into_the_projects_record_from_the_backend(monkeypatch, tmp_path):
    researcher = MagicMock()
    researcher.create_pull_request.return_value = {"number": 6, "html_url": "http://git/pulls/6"}
    monkeypatch.setattr(pr, "build_researcher_git_api", lambda config: researcher)
    loaded = []

    def load_repo_config(entity, context, project, backend_api):
        loaded.append((entity, context, project, backend_api))
        return trigger_config(repo="trigger-x", watch_dir="in/", base_branch="release")

    monkeypatch.setattr(trigger, "load_repo_config", load_repo_config)
    watched = []
    monkeypatch.setattr(pr, "watch_pr", lambda config, number, timeout: watched.append((number, timeout)))
    path = tmp_path / "t.json"
    path.write_text(json.dumps(TRIGGER))

    trigger.trigger_pr("the context", "the api", "demo-gitea", path, merge=True, watch=True, timeout=30)

    assert loaded == [("trigger", "the context", "demo-gitea", "the api")]
    researcher.create_branch.assert_called_once()
    assert researcher.create_branch.call_args.args[0] == "gitea_admin/trigger-x"
    assert researcher.create_branch.call_args.args[2] == "release"
    file_path, content = researcher.create_file.call_args.args[1:3]
    assert file_path.startswith("in/pr-") and file_path.endswith(".json")
    assert json.loads(content) == TRIGGER
    assert researcher.create_pull_request.call_args.kwargs["base_branch"] == "release"
    researcher.merge_pull_request.assert_called_once_with("gitea_admin/trigger-x", 6)
    assert watched == [(6, 30)]


def test_without_merge_the_pull_request_is_only_opened(monkeypatch, tmp_path):
    researcher = MagicMock()
    researcher.create_pull_request.return_value = {"number": 6, "html_url": "http://git/pulls/6"}
    monkeypatch.setattr(pr, "build_researcher_git_api", lambda config: researcher)
    monkeypatch.setattr(
        trigger, "load_repo_config", lambda *args, **options: trigger_config(repo="t", watch_dir="in/", base_branch="main")
    )
    path = tmp_path / "t.json"
    path.write_text(json.dumps(TRIGGER))

    trigger.trigger_pr("the context", "the api", "demo-gitea", path, merge=False, watch=False, timeout=30)

    researcher.create_pull_request.assert_called_once()
    researcher.merge_pull_request.assert_not_called()
