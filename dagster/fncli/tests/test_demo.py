import json
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import click
from click.testing import CliRunner
from dotenv import dotenv_values
import pytest

from app.utils import BackendSession, BaseSession
from fncli.cmds import demo
from fncli.cmds.demo import Step, demo_command

REPO_ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture(autouse=True)
def in_a_dir_with_a_demo_env(tmp_path, monkeypatch):
    """The demo finds .demo.env from the current directory: never the real one in the repo root."""
    (tmp_path / ".demo.env").write_text("TEST_PROJECT_NAME=demo-gitea\nTEST_TRIGGER_REPO=demo-trigger\n")
    monkeypatch.chdir(tmp_path)


def recorder(ran, name, error=None):
    def callback(**options):
        ran.append((name, options))
        if error:
            raise error

    return click.Command(name, callback=callback)


def step_of(ran, name, error=None, **fields):
    return Step(f"title of {name}", f"text of {name}", f"fncli {name}", recorder(ran, name, error), {}, **fields)


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


def run_demo(*args, input=None):
    return CliRunner().invoke(demo_command, list(args), input=input)


def test_yes_runs_every_step_in_order_and_leaves_out_the_teardown(ran):
    result = run_demo("--yes")

    assert result.exit_code == 0
    assert names(ran) == ["one", "two", "three"]
    assert "Step 3: title of three" in result.output
    assert "teardown" not in result.output
    assert "Delete the lot?" not in result.output
    assert result.output.rstrip().endswith("Done.")


def test_each_step_shows_its_number_title_text_and_command(ran):
    result = run_demo("-y")

    assert "Step 1: title of one\ntext of one\n$ fncli one\n" in result.output


def test_enter_runs_a_step_and_the_teardown_is_offered_last(ran):
    result = run_demo(input="\n\n\n\ny\n")

    assert result.exit_code == 0
    assert names(ran) == ["one", "two", "three", "teardown"]
    assert "Step 4: title of teardown" in result.output


def test_s_skips_a_step(ran):
    result = run_demo(input="\ns\n\ns\n")

    assert result.exit_code == 0
    assert names(ran) == ["one", "three"]
    assert "Done." in result.output


def test_q_stops_the_demo(ran):
    result = run_demo(input="\nq\n")

    assert result.exit_code == 0
    assert names(ran) == ["one"]
    assert "Step 3" not in result.output
    assert "Done." not in result.output


def test_from_starts_at_that_step(ran):
    result = run_demo("--yes", "--from", "2")

    assert names(ran) == ["two", "three"]
    assert "Step 1" not in result.output
    assert "Step 2: title of two" in result.output


def test_from_can_start_at_the_teardown(ran):
    result = run_demo("--from", "4", input="\ny\n")

    assert names(ran) == ["teardown"]
    assert result.exit_code == 0


def test_the_teardown_asks_and_does_nothing_on_no(ran):
    result = run_demo("--from", "4", input="\nn\n")

    assert ran == []
    assert "Delete the lot? [y/N]" in result.output
    assert result.exit_code == 0
    assert "Done." in result.output


def test_the_teardown_does_not_ask_when_skipped(ran):
    result = run_demo("--from", "4", input="s\n")

    assert ran == []
    assert "Delete the lot?" not in result.output


def test_a_failing_step_stops_the_demo(ran, monkeypatch):
    monkeypatch.setattr(
        demo, "STEPS",
        [step_of(ran, "one"), step_of(ran, "two", click.ClickException("it broke")), step_of(ran, "three")],
    )

    result = run_demo("--yes")

    assert result.exit_code == 1
    assert "it broke" in result.output
    assert names(ran) == ["one", "two"]
    assert "Done." not in result.output


def test_a_step_that_exits_0_does_not_end_the_demo(ran, monkeypatch):
    # open-pr --watch ends by raising Exit(0) when all went well
    monkeypatch.setattr(
        demo, "STEPS", [step_of(ran, "one", click.exceptions.Exit(0)), step_of(ran, "two")]
    )

    result = run_demo("--yes")

    assert result.exit_code == 0
    assert names(ran) == ["one", "two"]
    assert "Done." in result.output


def test_a_step_that_exits_1_stops_the_demo_with_that_code(ran, monkeypatch):
    monkeypatch.setattr(
        demo, "STEPS", [step_of(ran, "one", click.exceptions.Exit(1)), step_of(ran, "two")]
    )

    result = run_demo("--yes")

    assert result.exit_code == 1
    assert names(ran) == ["one"]
    assert "Done." not in result.output


def test_a_missing_demo_env_is_a_clean_error(ran, tmp_path):
    (tmp_path / ".demo.env").unlink()

    result = run_demo("--yes")

    assert result.exit_code == 1
    assert "cp .demo.env.example .demo.env" in result.output
    assert result.exception.__class__ is SystemExit
    assert ran == []


def test_the_demo_env_overrides_dev_env_and_the_shell(ran, monkeypatch):
    seen = {}
    monkeypatch.setenv("TEST_PROJECT_NAME", "from-dev-env")
    monkeypatch.setattr(
        demo, "STEPS",
        [Step("t", "project {TEST_PROJECT_NAME}", "fncli x", click.Command("x", callback=lambda: seen.update(os.environ)), {})],
    )

    result = run_demo("--yes")

    assert result.exit_code == 0
    assert seen["TEST_PROJECT_NAME"] == "demo-gitea"
    assert "Demo project: demo-gitea. Trigger repo: demo-trigger." in result.output
    assert "project demo-gitea" in result.output


class FakeState:
    """The project's snapshots, one per poll (the last one repeats)."""

    def __init__(self, monkeypatch, *snapshots):
        self.snapshots = list(snapshots)
        self.sleeps = []
        monkeypatch.setattr(demo, "build_backend_api", lambda config: "the api")
        monkeypatch.setattr(demo, "snapshot", self.snapshot)
        monkeypatch.setattr(demo.time, "sleep", self.sleeps.append)

    def snapshot(self, api, name):
        return self.snapshots.pop(0) if len(self.snapshots) > 1 else self.snapshots[0]


def snapshot_of(enabled=False, results=()):
    return {"project": {"id": 3, "name": "demo-gitea", "enabled": enabled}, "results": list(results)}


def waiting_step(ran, name="one", timeout=30, **fields):
    wait = demo.Wait("the project to be enabled", lambda state: state["project"]["enabled"], timeout)
    return step_of(ran, name, wait_for=wait, show=lambda api, state: f"enabled={state['project']['enabled']}", **fields)


def test_a_step_polls_until_its_change_arrived_and_prints_what_it_made_when_it_changes(ran, monkeypatch):
    state = FakeState(monkeypatch, snapshot_of(), snapshot_of(), snapshot_of(), snapshot_of(enabled=True))
    monkeypatch.setattr(demo, "STEPS", [waiting_step(ran), step_of(ran, "two")])

    result = run_demo("--yes")

    assert result.exit_code == 0
    assert result.output.count("--- now:\nenabled=False") == 1
    assert result.output.count("waiting for the project to be enabled...") == 2
    assert result.output.count("--- now:\nenabled=True") == 1
    assert state.sleeps == [demo.POLL_SECONDS] * 3
    assert names(ran) == ["one", "two"]


def test_a_step_that_never_arrives_times_out(ran, monkeypatch):
    FakeState(monkeypatch, snapshot_of())
    monkeypatch.setattr(demo, "STEPS", [waiting_step(ran, timeout=0), step_of(ran, "two")])

    result = run_demo("--yes")

    assert result.exit_code == 1
    assert "timed out waiting for the project to be enabled" in result.output
    assert names(ran) == ["one"]


def test_a_skipped_step_is_not_polled(ran, monkeypatch):
    state = FakeState(monkeypatch, snapshot_of(enabled=True))
    monkeypatch.setattr(demo, "STEPS", [waiting_step(ran)])

    result = run_demo(input="s\ns\n")

    assert ran == []
    assert "now:" not in result.output
    assert state.sleeps == []


def test_a_step_without_a_wait_shows_what_it_made_once(ran, monkeypatch):
    FakeState(monkeypatch, snapshot_of())
    monkeypatch.setattr(demo, "STEPS", [step_of(ran, "one", show=lambda api, state: f"made by {api}")])

    result = run_demo("--yes")

    assert result.output.count("--- now:\nmade by the api") == 1


def test_merge_results_pr_gets_the_number_of_the_first_results_pr(ran, monkeypatch):
    FakeState(monkeypatch, snapshot_of(results=[{"number": 7}, {"number": 5}]))
    merge = recorder(ran, "merge-results-pr")
    monkeypatch.setattr(demo, "merge_results_pr_command", merge)
    monkeypatch.setattr(demo, "STEPS", [Step("merge", "text", "fncli merge-results-pr", merge, {})])

    run_demo("--yes")

    assert ran == [("merge-results-pr", {"number": 7})]


def test_the_steps_are_the_setup_in_order():
    assert [(step.command.name, step.options) for step in demo.STEPS] == [
        ("init-gitea-repo", {"entity": "trigger"}),
        ("init-gitea-repo", {"entity": "results"}),
        ("init-git-secret", {"entity": "trigger"}),
        ("init-git-secret", {"entity": "results"}),
        ("init-dataset-secret", {}),
        ("init-backend-project", {}),
        ("init-backend-trigger-repo", {}),
        ("init-backend-results-repo", {}),
        ("init-backend-dataset", {}),
        ("verify-git-secret", {"entity": "trigger"}),
        ("verify-git-secret", {"entity": "results"}),
        ("project-set", {"enabled": "true"}),
        ("project-healthcheck", {}),
        ("open-pr", {"kind": "watched", "merge": True, "watch": True, "timeout": 300}),
        ("merge-results-pr", {}),
        ("verify-project", {}),
        ("verify-repo", {}),
    ]
    assert [number for number, step in enumerate(demo.STEPS, start=1) if step.wait_for] == [6, 7, 8, 9, 12, 14, 15]
    assert [number for number, step in enumerate(demo.STEPS, start=1) if step.show] == [
        1, 2, 3, 4, 5, 6, 7, 8, 9, 12, 14, 15
    ]


def test_the_sensors_are_not_started_by_the_demo():
    assert "start-sensor" not in [step.command.name for step in demo.STEPS]


def test_every_step_shows_the_command_line_it_runs():
    for step in [*demo.STEPS, demo.TEARDOWN_STEP]:
        assert step.line.startswith(f"fncli {step.command.name}")


def test_every_text_fills_in_from_the_example_config():
    values = dotenv_values(REPO_ROOT / ".demo.env.example")

    for step in [*demo.STEPS, demo.TEARDOWN_STEP]:
        assert step.text.format_map(values)


def test_only_the_teardown_asks_and_it_is_the_teardown_command():
    assert demo.TEARDOWN_STEP.command.name == "teardown-project"
    assert demo.TEARDOWN_STEP.confirm
    assert not any(step.confirm for step in demo.STEPS)


def test_steps_are_separated_by_a_line(ran):
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
        "Webserver calls:\n  GET /projects/1 -> 200  x 3\n  PATCH /projects/1 -> 200\n"
    )


def test_a_step_with_no_backend_calls_shows_none(capsys):
    demo.show_backend_calls([])

    assert capsys.readouterr().out == ""
