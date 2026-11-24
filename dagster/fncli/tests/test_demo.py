"""`fncli demo` (fncli.cmds.demo): the walk, its steps and what it needs on the node, with the node and backend faked."""

import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import click
from click.testing import CliRunner
import pytest
import yaml

from nexus_client.http import BackendSession, BaseSession
from fncli.cmds import demo
from fncli.cmds.demo import Demo, Step, demo_command, step_names
from fncli.node_config import load_resources, of_kind

REPO_ROOT = Path(__file__).resolve().parents[3]
CONFIG = REPO_ROOT / "config"


def project_resource(name="demo-gitea", synced=True, generation=2, observed=2, message="") -> dict:
    """A Project resource as the cluster returns it, with the operator's status"""
    return {
        "metadata": {"name": name, "namespace": "fn-operator", "generation": generation},
        "spec": {
            "datasets": ["shared"],
            "repositories": {
                "triggers": [{
                    "repository": "http://gitea.fn.svc:4000/gitea_admin/trigger-repo", "watchDir": "specs/",
                    "baseBranch": "main",
                }],
                "results": {
                    "repository": "http://gitea.fn.svc:4000/gitea_admin/results-repo", "targetDir": "results/",
                    "baseBranch": "main",
                },
            },
        },
        "status": {"synced": synced, "observedGeneration": observed, "message": message},
    }


class FakeApi:
    """The backend client as far as the demo reads it: the datasets on the node"""

    def __init__(self, datasets=("shared",)):
        self.datasets = datasets

    def find_dataset(self, name):
        return SimpleNamespace(name=name) if name in self.datasets else None

    def __str__(self):
        return "the api"


@pytest.fixture(autouse=True)
def restore_env():
    """The commands load the node's env file over the env: put it back after each test."""
    with patch.dict(os.environ):
        yield


@pytest.fixture
def context_file(tmp_path, monkeypatch):
    """The context file the commands find through FNCLI_CONTEXT, and the triggers/ folder with the default trigger file"""
    path = tmp_path / "context.yaml"
    path.write_text(yaml.safe_dump({
        "node": {"url": "http://localhost:5000", "kube_context": "kind-fn", "keycloak_namespace": "keycloak"},
        "defaults": {"project": "demo-gitea", "trigger_type": "pr"},
    }))
    (tmp_path / "triggers" / "examples").mkdir(parents=True)
    (tmp_path / "triggers" / "examples" / "demo.json").write_text('{"spec": {"image": "busybox:1"}}')
    monkeypatch.setenv("FNCLI_CONTEXT", str(path))
    monkeypatch.delenv("FNCLI_DEFAULT_PROJECT", raising=False)
    monkeypatch.delenv("FNCLI_DEFAULT_TRIGGER_TYPE", raising=False)
    monkeypatch.chdir(tmp_path)
    return path


@pytest.fixture
def opened(monkeypatch):
    """The Project resources demo_command read, as (namespace, name)"""
    return []


@pytest.fixture
def resources(monkeypatch, context_file, opened):
    """The cluster's Project resources by name, and a node that has the dataset. A test changes them."""
    resources = {"demo-gitea": project_resource(), "demo-other": project_resource("demo-other")}
    api = FakeApi()

    def get_node_config(plural, namespace, name):
        opened.append((namespace, name))
        return resources.get(name)

    monkeypatch.setattr(demo, "get_node_config", get_node_config)
    monkeypatch.setattr(demo, "open_target", lambda context: api)
    return resources


def recorder(ran, name, error=None):
    def callback(**options):
        ran.append((name, options))
        if error:
            raise error

    return click.Command(name, callback=callback)


def step_of(ran, name, error=None, **fields):
    command = recorder(ran, name, error)
    return Step(
        f"title of {name}", f"text of {name}", f"fncli {name}", lambda ctx, demo: ctx.invoke(command), **fields
    )


@pytest.fixture
def ran(monkeypatch):
    """The steps, replaced by commands that only note that they ran."""
    ran = []
    monkeypatch.setattr(demo, "STEPS", [step_of(ran, "one"), step_of(ran, "two"), step_of(ran, "three")])
    return ran


def names(ran):
    return [name for name, _ in ran]


@pytest.fixture
def run_demo(resources):
    def run(*args, input=None):
        return CliRunner().invoke(demo_command, list(args), input=input)

    return run


def test_yes_runs_every_step_in_order(ran, run_demo, opened):
    result = run_demo("--yes")

    assert result.exit_code == 0, result.output
    assert names(ran) == ["one", "two", "three"]
    assert opened == [("fn-operator", "demo-gitea")]
    assert "Step 3: title of three" in result.output
    assert result.output.rstrip().endswith("Done.")


def test_each_step_shows_its_number_title_text_and_command(ran, run_demo):
    result = run_demo("-y")

    assert "Step 1: title of one\ntext of one\n$ fncli one\n" in result.output


def test_enter_runs_a_step(ran, run_demo):
    result = run_demo(input="\n\n\n")

    assert result.exit_code == 0, result.output
    assert names(ran) == ["one", "two", "three"]


def test_s_skips_a_step(ran, run_demo):
    result = run_demo(input="\ns\n\ns\n")

    assert result.exit_code == 0, result.output
    assert names(ran) == ["one", "three"]
    assert "Done." in result.output


def test_q_stops_the_demo(ran, run_demo):
    result = run_demo(input="\nq\n")

    assert result.exit_code == 0, result.output
    assert names(ran) == ["one"]
    assert "Step 3" not in result.output
    assert "Done." not in result.output


def test_from_starts_at_that_step(ran, run_demo):
    result = run_demo("--yes", "--from", "2")

    assert names(ran) == ["two", "three"]
    assert "Step 1" not in result.output
    assert "Step 2: title of two" in result.output


def test_a_failing_step_stops_the_demo(ran, run_demo, monkeypatch):
    monkeypatch.setattr(
        demo, "STEPS",
        [step_of(ran, "one"), step_of(ran, "two", click.ClickException("it broke")), step_of(ran, "three")],
    )

    result = run_demo("--yes")

    assert result.exit_code == 1
    assert "it broke" in result.output
    assert names(ran) == ["one", "two"]
    assert "Done." not in result.output


def test_a_step_that_exits_0_does_not_end_the_demo(ran, run_demo, monkeypatch):
    # trigger --watch ends by raising Exit(0) when all went well
    monkeypatch.setattr(
        demo, "STEPS", [step_of(ran, "one", click.exceptions.Exit(0)), step_of(ran, "two")]
    )

    result = run_demo("--yes")

    assert result.exit_code == 0, result.output
    assert names(ran) == ["one", "two"]
    assert "Done." in result.output


def test_a_step_that_exits_1_stops_the_demo_with_that_code(ran, run_demo, monkeypatch):
    monkeypatch.setattr(
        demo, "STEPS", [step_of(ran, "one", click.exceptions.Exit(1)), step_of(ran, "two")]
    )

    result = run_demo("--yes")

    assert result.exit_code == 1
    assert names(ran) == ["one"]
    assert "Done." not in result.output


def test_the_files_names_fill_in_the_steps_text_and_none_of_them_goes_in_the_env(run_demo, monkeypatch):
    seen = {}
    moved = ("TEST_PROJECT_NAME", "TEST_TRIGGER_REPO", "TEST_RESULTS_REPO", "DEFAULT_PROJECT_DATASET", "NEXUS_API_URL")
    for name in moved:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(
        demo, "STEPS",
        [Step("t", "project {project}", "fncli x", lambda ctx, demo: seen.update(
            project=demo.project, dataset=demo.spec["datasets"][0], env=dict(os.environ)
        ))],
    )

    result = run_demo("--yes")

    assert result.exit_code == 0, result.output
    assert (seen["project"], seen["dataset"]) == ("demo-gitea", "shared")
    assert not set(moved) & set(seen["env"])
    assert "Demo project: demo-gitea. Trigger repo: gitea_admin/trigger-repo." in result.output
    assert "project demo-gitea" in result.output


def test_the_demo_runs_when_the_project_resource_is_synced(ran, run_demo):
    result = run_demo("--yes")

    assert result.exit_code == 0, result.output
    assert "not synced" not in result.output
    assert names(ran) == ["one", "two", "three"]


@pytest.mark.parametrize(
    "status",
    [
        {"synced": False, "message": "dataset shared not found"},
        {"generation": 3, "message": "dataset shared not found"},
    ],
    ids=["not-synced", "older-generation"],
)
def test_the_demo_refuses_with_exit_1_until_the_operator_has_synced_the_project(status, ran, run_demo, resources):
    resources["demo-gitea"] = project_resource(**status)

    result = run_demo("--yes", "--from", "3")

    assert result.exit_code == 1
    assert "Project demo-gitea is not synced to the node yet: dataset shared not found" in result.output
    assert "kubectl get fn -n fn-operator" in result.output
    assert ran == []


def test_a_project_with_no_resource_stops_the_demo(ran, run_demo):
    result = run_demo("--yes", "--project", "nope")

    assert result.exit_code == 1
    assert "No Project resource nope in namespace fn" in result.output
    assert ran == []


def test_a_dataset_that_is_not_on_the_node_stops_the_demo_before_any_step(ran, run_demo, monkeypatch):
    monkeypatch.setattr(demo, "open_target", lambda context: FakeApi(datasets=()))

    result = run_demo("--yes")

    assert result.exit_code == 1
    assert "Dataset shared is not on the node" in result.output
    assert "fncli experiment setup demo" in result.output
    assert ran == []


def test_without_a_project_flag_the_default_project_is_used_and_said_on_the_first_line(ran, run_demo, opened):
    result = run_demo("--yes")

    assert result.exit_code == 0, result.output
    assert result.output.splitlines()[0].startswith("Using the defaults of ")
    assert result.output.splitlines()[0].endswith(": project demo-gitea")


def test_a_project_flag_beats_the_default_and_says_nothing(ran, run_demo, opened):
    result = run_demo("--yes", "--project", "demo-other")

    assert "Using the defaults" not in result.output
    assert opened == [("fn-operator", "demo-other")]


def test_the_env_default_project_beats_the_context_file(ran, run_demo, opened, monkeypatch):
    monkeypatch.setenv("FNCLI_DEFAULT_PROJECT", "demo-other")

    result = run_demo("--yes")

    assert result.output.splitlines()[0].endswith(": project demo-other")
    assert opened == [("fn-operator", "demo-other")]


def test_no_project_flag_and_no_default_is_a_usage_error(ran, run_demo, context_file):
    context_file.write_text(yaml.safe_dump(
        {"node": {"url": "http://localhost:5000", "kube_context": "kind-fn", "keycloak_namespace": "keycloak"}}
    ))

    result = run_demo("--yes")

    assert result.exit_code == 2
    assert "Give --project" in result.output
    assert ran == []


def test_the_trigger_file_is_the_argument_found_as_given_or_under_triggers(ran, run_demo, tmp_path, monkeypatch):
    seen = {}
    monkeypatch.setattr(demo, "STEPS", [Step("t", "{trigger}", "fncli x", lambda ctx, demo: seen.update(file=demo.trigger_file))])

    assert run_demo("--yes").exit_code == 0
    assert seen["file"] == tmp_path / "triggers" / "examples" / "demo.json"

    (tmp_path / "triggers" / "mine.json").write_text("{}")
    assert run_demo("--yes", "mine.json").exit_code == 0
    assert seen["file"] == tmp_path / "triggers" / "mine.json"

    result = run_demo("--yes", "nope.json")
    assert result.exit_code == 2 and "nope.json not found, as given or under triggers/ from here up" in result.output


def test_the_pull_request_step_triggers_the_demo_project_by_pr_with_the_trigger_file(monkeypatch):
    calls = []
    monkeypatch.setattr(demo, "trigger_pr", lambda *args, **options: calls.append((args, options)))

    demo.trigger_by_pr(None, SimpleNamespace(
        context="the context", api="the api", project="demo-gitea", trigger_file=Path("t.json")
    ))

    assert calls == [
        (("the context", "the api", "demo-gitea", Path("t.json")), {"merge": True, "watch": True, "timeout": 300})
    ]


class FakeState:
    """The project's snapshots, one per poll (the last one repeats)."""

    def __init__(self, monkeypatch, *snapshots):
        self.snapshots = list(snapshots)
        self.sleeps = []
        monkeypatch.setattr(demo, "snapshot", self.snapshot)
        monkeypatch.setattr(demo.time, "sleep", self.sleeps.append)

    def snapshot(self, api, name):
        return self.snapshots.pop(0) if len(self.snapshots) > 1 else self.snapshots[0]


def snapshot_of(enabled=False, results=()):
    return {"project": {"id": 3, "name": "demo-gitea", "enabled": enabled}, "results": list(results)}


def waiting_step(ran, name="one", timeout=30, **fields):
    wait = demo.Wait("the project to be enabled", lambda state: state["project"]["enabled"], timeout)
    return step_of(ran, name, wait_for=wait, show=lambda demo, state: f"enabled={state['project']['enabled']}", **fields)


def test_a_step_polls_until_its_change_arrived_and_prints_what_it_made_when_it_changes(ran, run_demo, monkeypatch):
    state = FakeState(monkeypatch, snapshot_of(), snapshot_of(), snapshot_of(), snapshot_of(enabled=True))
    monkeypatch.setattr(demo, "STEPS", [waiting_step(ran), step_of(ran, "two")])

    result = run_demo("--yes")

    assert result.exit_code == 0, result.output
    assert result.output.count("--- now:\nenabled=False") == 1
    assert result.output.count("waiting for the project to be enabled...") == 2
    assert result.output.count("--- now:\nenabled=True") == 1
    assert state.sleeps == [demo.POLL_SECONDS] * 3
    assert names(ran) == ["one", "two"]


def test_a_step_that_never_arrives_times_out(ran, run_demo, monkeypatch):
    FakeState(monkeypatch, snapshot_of())
    monkeypatch.setattr(demo, "STEPS", [waiting_step(ran, timeout=0), step_of(ran, "two")])

    result = run_demo("--yes")

    assert result.exit_code == 1
    assert "timed out waiting for the project to be enabled" in result.output
    assert names(ran) == ["one"]


def test_a_skipped_step_is_not_polled(ran, run_demo, monkeypatch):
    state = FakeState(monkeypatch, snapshot_of(enabled=True))
    monkeypatch.setattr(demo, "STEPS", [waiting_step(ran)])

    result = run_demo(input="s\ns\n")

    assert ran == []
    assert "now:" not in result.output
    assert state.sleeps == []


def test_a_step_without_a_wait_shows_what_it_made_once(ran, run_demo, monkeypatch):
    FakeState(monkeypatch, snapshot_of())
    monkeypatch.setattr(demo, "STEPS", [step_of(ran, "one", show=lambda demo, state: f"made by {demo.api}")])

    result = run_demo("--yes")

    assert result.output.count("--- now:\nmade by the api") == 1


def test_merge_results_pr_gets_the_number_of_the_latest_results_pr(ran, monkeypatch):
    FakeState(monkeypatch, snapshot_of(results=[{"number": 5}, {"number": 7}]))
    monkeypatch.setattr(demo, "merge_results_pr_command", recorder(ran, "merge-results-pr"))

    with click.Context(click.Command("demo")) as ctx:
        demo.merge_results_pr(
            ctx, SimpleNamespace(context="the context", api="the api", project="demo-gitea")
        )

    assert ran == [("merge-results-pr", {"number": 7, "context": "the context", "project": "demo-gitea"})]


def test_the_merged_wait_follows_the_latest_results_pr_not_an_earlier_runs():
    merge_step = next(step for step in demo.STEPS if step.title == "Merge the results pull request")
    earlier_run_merged = snapshot_of(results=[{"step": "MERGED"}, {"step": "OPEN"}])
    this_run_merged = snapshot_of(results=[{"step": "MERGED"}, {"step": "MERGED"}])

    assert not merge_step.wait_for.done(earlier_run_merged)
    assert merge_step.wait_for.done(this_run_merged)


def test_the_steps_are_the_checks_and_the_pull_request_walk_in_order():
    assert [step.title for step in demo.STEPS] == [
        "Check the node can log in to the dataset's database",
        "Check the git host accepts the trigger token",
        "Check the git host accepts the results token",
        "Project healthcheck",
        "Open and merge a pull request in the trigger repo",
        "Merge the results pull request",
        "Check the project",
        "Check every merged pull request ran",
    ]
    assert [number for number, step in enumerate(demo.STEPS, start=1) if step.wait_for] == [5, 6]


def test_no_step_creates_or_deletes_anything_on_the_node():
    assert not [step for step in demo.STEPS if step.line.startswith(("kubectl", "fncli project-set"))]
    assert not hasattr(demo, "TEARDOWN_STEP")


def test_the_sensors_are_not_started_by_the_demo():
    assert not [step for step in demo.STEPS if "start-sensor" in step.line]


def test_every_step_shows_the_command_it_runs():
    for step in demo.STEPS:
        assert step.line.startswith(("fncli ", "GET /global/datasets"))


DEMO_FILES = {"demo-gitea": CONFIG / "demo.yaml", "demo-github": CONFIG / "github" / "demo-github.yaml"}


@pytest.mark.parametrize("name", DEMO_FILES)
def test_every_text_and_command_fills_in_from_the_demo_files(name):
    project = of_kind(load_resources([DEMO_FILES[name]]), "Project")[0]
    values = step_names(Demo("the context", Path("triggers/examples/demo.json"), None, name, project["spec"]))

    for step in demo.STEPS:
        assert step.text.format_map(values) and step.line.format_map(values)


@pytest.mark.parametrize("name", DEMO_FILES)
def test_the_demo_files_assign_the_demo_dataset_without_holding_it(name):
    resources = load_resources([DEMO_FILES[name]])

    assert of_kind(resources, "Dataset") == []
    assert [(p["metadata"]["name"], p["spec"]["datasets"]) for p in of_kind(resources, "Project")] == [(name, ["demo-db"])]


def test_steps_are_separated_by_a_line(ran, run_demo):
    result = run_demo("-y")

    assert result.output.count(demo.SEPARATOR + "\nStep ") == 3


def test_the_backend_calls_of_a_step_are_noted_with_path_and_status():
    response = MagicMock(status_code=201)
    response.request.path_url = "/global/secrets"
    calls = []

    with patch.object(BaseSession, "request", return_value=response):
        with demo.record_backend_calls(calls):
            BackendSession(MagicMock()).request("post", "/global/secrets")

    assert calls == [("POST", "/global/secrets", 201)]


def test_repeated_backend_calls_are_shown_once_with_a_count(capsys):
    demo.show_backend_calls([("GET", "/projects/1", 200)] * 3 + [("PATCH", "/projects/1", 200)])

    assert capsys.readouterr().out == (
        "nexus-api calls:\n  GET /projects/1 -> 200  x 3\n  PATCH /projects/1 -> 200\n"
    )


def test_a_step_with_no_backend_calls_shows_none(capsys):
    demo.show_backend_calls([])

    assert capsys.readouterr().out == ""
