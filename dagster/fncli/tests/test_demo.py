"""`fncli demo` (fncli.cmds.demo): the walk, its steps and what it needs on the node, with the node and backend faked."""

import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import click
from click.testing import CliRunner
import pytest

from app.utils import BackendSession, BaseSession
from fncli.cmds import demo
from fncli.cmds.demo import Demo, Step, demo_command, step_names
from fncli.nodefile.loader import limit_to_project, load_node_file
from fncli.tests.test_nodefile_diff import make_node, node_data

REPO_ROOT = Path(__file__).resolve().parents[3]
EXAMPLES = REPO_ROOT / "bootstrap" / "examples"


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
    """The demo sets the file's names in the env: put them back after each test."""
    with patch.dict(os.environ):
        yield


@pytest.fixture
def node_file(tmp_path, monkeypatch):
    """A node file for the demo whose dataset is not in it, and the node it was opened on, which has the dataset"""
    path = tmp_path / "demo.yaml"
    path.write_text("")
    data = node_data()
    data["projects"][0]["name"] = "demo-gitea"
    del data["datasets"]
    node = make_node(data)
    api = FakeApi()
    monkeypatch.setattr(demo, "open_node", lambda file, project: (node, api))
    return path


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
    monkeypatch.setattr(
        demo, "TEARDOWN_STEP", step_of(ran, "teardown", confirm="Delete the lot?")
    )
    return ran


def names(ran):
    return [name for name, _ in ran]


@pytest.fixture
def run_demo(node_file):
    def run(*args, input=None):
        return CliRunner().invoke(demo_command, ["-f", str(node_file), *args], input=input)

    return run


def test_yes_runs_every_step_in_order_and_leaves_out_the_teardown(ran, run_demo):
    result = run_demo("--yes")

    assert result.exit_code == 0, result.output
    assert names(ran) == ["one", "two", "three"]
    assert "Step 3: title of three" in result.output
    assert "teardown" not in result.output
    assert "Delete the lot?" not in result.output
    assert result.output.rstrip().endswith("Done.")


def test_each_step_shows_its_number_title_text_and_command(ran, run_demo):
    result = run_demo("-y")

    assert "Step 1: title of one\ntext of one\n$ fncli one\n" in result.output


def test_enter_runs_a_step_and_the_teardown_is_offered_last(ran, run_demo):
    result = run_demo(input="\n\n\n\ny\n")

    assert result.exit_code == 0, result.output
    assert names(ran) == ["one", "two", "three", "teardown"]
    assert "Step 4: title of teardown" in result.output


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


def test_from_can_start_at_the_teardown(ran, run_demo):
    result = run_demo("--from", "4", input="\ny\n")

    assert names(ran) == ["teardown"]
    assert result.exit_code == 0, result.output


def test_the_teardown_asks_and_does_nothing_on_no(ran, run_demo):
    result = run_demo("--from", "4", input="\nn\n")

    assert ran == []
    assert "Delete the lot? [y/N]" in result.output
    assert result.exit_code == 0, result.output
    assert "Done." in result.output


def test_the_teardown_does_not_ask_when_skipped(ran, run_demo):
    result = run_demo("--from", "4", input="s\n")

    assert ran == []
    assert "Delete the lot?" not in result.output


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
    # open-pr --watch ends by raising Exit(0) when all went well
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


def test_the_files_names_win_over_the_env_and_fill_in_the_steps_text(run_demo, monkeypatch):
    seen = {}
    monkeypatch.setenv("TEST_PROJECT_NAME", "from-dev-env")
    monkeypatch.setattr(
        demo, "STEPS",
        [Step("t", "project {project}", "fncli x", lambda ctx, demo: seen.update(os.environ))],
    )

    result = run_demo("--yes")

    assert result.exit_code == 0, result.output
    assert seen["TEST_PROJECT_NAME"] == "demo-gitea"
    assert seen["DEFAULT_PROJECT_DATASET"] == "shared"
    assert "Demo project: demo-gitea. Trigger repo: gitea_admin/trigger-repo." in result.output
    assert "project demo-gitea" in result.output


def test_a_dataset_that_is_not_on_the_node_stops_the_demo_before_any_step(ran, run_demo, node_file, monkeypatch):
    data = node_data()
    del data["datasets"]
    monkeypatch.setattr(demo, "open_node", lambda file, project: (make_node(data), FakeApi(datasets=())))

    result = run_demo("--yes")

    assert result.exit_code == 1
    assert "Dataset shared is not on the node" in result.output
    assert "make experiments setup demo" in result.output
    assert ran == []


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


def test_merge_results_pr_gets_the_number_of_the_first_results_pr(ran, monkeypatch):
    FakeState(monkeypatch, snapshot_of(results=[{"number": 7}, {"number": 5}]))
    monkeypatch.setattr(demo, "merge_results_pr_command", recorder(ran, "merge-results-pr"))

    with click.Context(click.Command("demo")) as ctx:
        demo.merge_results_pr(ctx, SimpleNamespace(api="the api", project=SimpleNamespace(name="demo-gitea")))

    assert ran == [("merge-results-pr", {"number": 7})]


def test_the_steps_are_the_setup_in_order_and_none_makes_the_dataset():
    assert [step.title for step in demo.STEPS] == [
        "Create the Gitea repos",
        "Secrets for the repos (global)",
        "The git provider and the repositories (global)",
        "Check the node can log in to the dataset's database",
        "Create the project",
        "The project's trigger repository resource",
        "The project's results repository resource",
        "The project's dataset resource",
        "Check the git host accepts the trigger token",
        "Check the git host accepts the results token",
        "Enable the project",
        "Project healthcheck",
        "Open and merge a pull request in the trigger repo",
        "Merge the results pull request",
        "Check the project",
        "Check every merged pull request ran",
    ]
    assert [number for number, step in enumerate(demo.STEPS, start=1) if step.wait_for] == [5, 6, 7, 8, 11, 13, 14]
    assert not [step for step in demo.STEPS if "dataset" in step.line and "apply" in step.line and "resource" not in step.line]


def test_the_sensors_are_not_started_by_the_demo():
    assert not [step for step in demo.STEPS if "start-sensor" in step.line]


def test_every_step_shows_the_command_it_runs():
    for step in [*demo.STEPS, demo.TEARDOWN_STEP]:
        assert step.line.startswith(("fncli ", "GET /global/datasets"))


@pytest.mark.parametrize("name", ["demo-gitea", "demo-github"])
def test_every_text_and_command_fills_in_from_the_demo_files(name):
    node = limit_to_project(load_node_file(EXAMPLES / f"{name}.yaml"), name)
    values = step_names(Demo(EXAMPLES / f"{name}.yaml", node, None, node.projects[0]))

    for step in [*demo.STEPS, demo.TEARDOWN_STEP]:
        assert step.text.format_map(values) and step.line.format_map(values)


@pytest.mark.parametrize("name", ["demo-gitea", "demo-github"])
def test_the_demo_files_assign_the_demo_dataset_without_holding_it(name):
    node = load_node_file(EXAMPLES / f"{name}.yaml")

    assert node.datasets == []
    assert [project.datasets for project in node.projects] == [["demo-db"]]
    assert not [label for label in node.secrets if "dataset" in label]


def test_only_the_teardown_asks_and_it_is_the_delete_step():
    assert demo.TEARDOWN_STEP.run is demo.delete_demo
    assert demo.TEARDOWN_STEP.confirm
    assert not any(step.confirm for step in demo.STEPS)


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
