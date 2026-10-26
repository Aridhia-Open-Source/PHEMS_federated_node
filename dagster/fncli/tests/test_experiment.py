import json
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import click
from click.testing import CliRunner
from dotenv import load_dotenv
from pydantic import ValidationError
import pytest

from fncli.cmds import experiment
from fncli.cmds.experiment import ExperimentConfig, experiment_group, load_project

REPO_ROOT = Path(__file__).resolve().parents[3]

PROJECT_ENV = """\
IMAGE=localhost:5001/x-fn:latest
SOURCE_DIR=sources/x
DATASET_NAME=x-db
DATASET_USERNAME=x_user
DATASET_SECRET_NAME=db-datasets-x
DATASET_SCHEMA=cdm
DATASET_SCHEMA_WRITE=results
TEST_PROJECT_NAME=exp
RUN_TIMEOUT=60
DEV_ENV='{"X_DEV": "1"}'
"""


@pytest.fixture(autouse=True)
def restore_env():
    """The commands and load_dotenv set variables in this process: put them back after each test."""
    with patch.dict(os.environ):
        yield


@pytest.fixture(autouse=True)
def repo(tmp_path, monkeypatch):
    """A repo root with a .dev.env and two experiments, and the data dir the release needs."""
    (tmp_path / ".dev.env").write_text("")
    projects = tmp_path / "experiments" / "projects"
    for name in ("x", "y"):
        (projects / name).mkdir(parents=True)
        (projects / name / "values.yaml").write_text("")
    (projects / "x" / "project.env").write_text(PROJECT_ENV)
    (tmp_path / "data").mkdir()
    monkeypatch.setenv("FN_DATA_DIR", str(tmp_path / "data"))
    for key in ("FULL", "TEST_PR_ENV", "TEST_PR_IMAGE", "DATASET_PASSWORD", "CLUSTER_DATASET_HOST", "DATASET_PORT"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.chdir(tmp_path)
    return tmp_path


class Commands:
    """Stands in for subprocess.run: notes each command, and fails the ones that start with `failing`."""

    def __init__(self, failing=None):
        self.calls = []
        self.failing = failing

    def __call__(self, command, **kwargs):
        self.calls.append((command, kwargs))
        return SimpleNamespace(returncode=3 if command[0] == self.failing else 0, stdout="SEED SQL")

    @property
    def lines(self):
        return [" ".join(command) for command, _ in self.calls]


@pytest.fixture
def commands(monkeypatch):
    commands = Commands()
    monkeypatch.setattr(experiment.subprocess, "run", commands)
    return commands


@pytest.fixture
def steps(monkeypatch):
    """The fncli steps the experiment commands chain, replaced by commands that note what they were given and see."""
    steps = []

    def step(name):
        def callback(**options):
            steps.append((name, options, dict(os.environ)))

        return click.Command(name, callback=callback)

    for name, attribute in (
        ("setup-project", "setup_project_command"),
        ("start-sensor", "start_sensor_command"),
        ("open-pr", "open_pr_command"),
        ("teardown-project", "teardown_project_command"),
    ):
        monkeypatch.setattr(experiment, attribute, step(name))
    monkeypatch.setattr(
        experiment, "get_k8s_secret", lambda secret_name, namespace, key: f"{secret_name}/{namespace}/{key}"
    )
    return steps


def invoke(*args):
    result = CliRunner().invoke(experiment_group, list(args))
    assert result.exit_code == 0, result.output
    return result


def test_the_project_env_wins_over_the_shell_and_the_rest_of_the_env_is_left_alone(monkeypatch):
    monkeypatch.setenv("TEST_PROJECT_NAME", "from-dev-env")

    config = load_project("x")

    assert os.environ["TEST_PROJECT_NAME"] == "exp"
    assert os.environ["BACKEND_URL"] == "http://localhost:5000"
    assert (config.image, config.source_dir, config.project_name) == ("localhost:5001/x-fn:latest", "sources/x", "exp")
    assert (config.database, config.username, config.secret_name) == ("x-db", "x_user", "db-datasets-x")
    assert (config.read_schema, config.write_schema, config.run_timeout) == ("cdm", "results", 60)
    assert config.dev_env == {"X_DEV": "1"}


def test_an_unknown_project_is_an_error():
    with pytest.raises(click.ClickException, match="No such project"):
        load_project("nope")


def test_a_project_env_missing_a_value_is_rejected(repo, monkeypatch):
    (repo / "experiments" / "projects" / "x" / "project.env").write_text(PROJECT_ENV.replace("IMAGE=", "NOT_IMAGE="))
    monkeypatch.delenv("IMAGE", raising=False)

    with pytest.raises(ValidationError, match="required"):
        load_project("x")


def test_the_committed_uc1_project_env_is_a_complete_config():
    load_dotenv(REPO_ROOT / "experiments" / "projects" / "uc1" / "project.env", override=True)

    config = ExperimentConfig()

    assert config.dev_env == {"UC1_DEV": "1"}
    assert config.run_timeout == 1800
    assert config.database == "uc1-omop"


def test_up_installs_the_release_with_every_project_database(repo, commands):
    invoke("up")

    projects = repo / "experiments" / "projects"
    assert commands.lines == [
        f"helm upgrade --install experiments {repo}/experiments/chart --namespace experiments "
        f"--create-namespace -f {projects}/x/values.yaml -f {projects}/y/values.yaml --wait --timeout 5m",
    ]


def test_setup_checks_the_release_then_seeds_then_sets_up_the_node_project(repo, commands, steps):
    invoke("setup", "x")

    projects = repo / "experiments" / "projects"
    assert commands.lines == [
        "helm status experiments --namespace experiments",
        f"{projects}/x/seed.sh",
        "kubectl exec -i -n experiments deploy/db-datasets -- psql -v ON_ERROR_STOP=1 -q -U x_user -d x-db",
    ]
    assert commands.calls[2][1]["input"] == "SEED SQL"
    (name, _, env), = steps
    assert name == "setup-project"
    assert env["CLUSTER_DATASET_HOST"] == "db-datasets.experiments.svc"
    assert env["DATASET_PORT"] == "5432"
    assert env["DATASET_PASSWORD"] == "db-datasets-x/experiments/password"
    assert env["TEST_PROJECT_NAME"] == "exp"
    assert env["NAMESPACE"] == "fn"


def test_setup_without_the_release_tells_you_to_run_up(commands, steps):
    commands.failing = "helm"

    result = CliRunner().invoke(experiment_group, ["setup", "x"])

    assert result.exit_code == 1
    assert "fncli experiment up" in result.output
    assert len(commands.calls) == 1
    assert steps == []


def test_up_makes_the_database_directory_writable_for_postgres(repo, commands):
    invoke("up")

    assert (repo / "data" / "experiments" / "datasets").stat().st_mode & 0o777 == 0o777


def test_up_without_the_data_dir_stops_before_helm(repo, commands):
    (repo / "data").rmdir()

    result = CliRunner().invoke(experiment_group, ["up"])

    assert result.exit_code == 1
    assert "cluster.sh up" in result.output
    assert commands.calls == []


def test_a_failing_command_stops_setup_with_its_exit_status(commands, steps):
    commands.failing = "kubectl"

    result = CliRunner().invoke(experiment_group, ["setup", "x"])

    assert result.exit_code == 3
    assert steps == []


def test_run_starts_the_sensors_then_opens_a_watched_pr_with_the_image_and_dev_env(steps):
    invoke("run", "x")

    (sensors, _, _), (pr, options, env) = steps
    assert (sensors, pr) == ("start-sensor", "open-pr")
    assert steps[0][1] == {"group": "all", "name": None}
    assert options == {"kind": "watched", "merge": True, "watch": True, "timeout": 60}
    assert env["TEST_PR_IMAGE"] == "localhost:5001/x-fn:latest"
    assert json.loads(env["TEST_PR_ENV"]) == {"X_DEV": "1"}


def test_full_leaves_the_dev_env_out_of_the_pr(monkeypatch, steps):
    monkeypatch.setenv("FULL", "1")

    invoke("run", "x")

    env = steps[1][2]
    assert "TEST_PR_ENV" not in env
    assert env["TEST_PR_IMAGE"] == "localhost:5001/x-fn:latest"


def test_build_builds_and_pushes_the_image(repo, commands):
    invoke("build", "x")

    assert commands.lines == [
        f"docker build -t localhost:5001/x-fn:latest {repo}/experiments/sources/x",
        "docker push localhost:5001/x-fn:latest",
    ]


def test_teardown_tears_down_the_node_project_with_the_project_env(commands, steps):
    invoke("teardown", "x", "-y")

    assert [(name, env["TEST_PROJECT_NAME"]) for name, _, env in steps] == [("teardown-project", "exp")]
    assert commands.calls == []


def test_down_tears_down_every_project_then_uninstalls_the_release(repo, commands, steps):
    (repo / "experiments" / "projects" / "y" / "project.env").write_text("TEST_PROJECT_NAME=y-project\n")

    invoke("down", "-y")

    assert [(name, env["TEST_PROJECT_NAME"]) for name, _, env in steps] == [
        ("teardown-project", "exp"),
        ("teardown-project", "y-project"),
    ]
    assert commands.lines == ["helm uninstall experiments --namespace experiments"]


def test_run_local_runs_the_image_against_the_port_forward_and_stops_it(repo, commands, steps, monkeypatch):
    forward = MagicMock()
    popen = MagicMock(return_value=forward)
    monkeypatch.setattr(experiment.subprocess, "Popen", popen)

    invoke("run", "x", "--local")

    results = repo / "experiments" / "results" / "x"
    assert popen.call_args.args[0] == ["kubectl", "port-forward", "-n", "experiments", "svc/db-datasets", "5434:5432"]
    assert commands.lines == [
        "pg_isready -h localhost -p 5434",
        "docker run --rm --network host -e X_DEV=1 "
        "-e CONNECTION_STRING=server=localhost;database=x-db;port=5434;uid=x_user;pwd=db-datasets-x/experiments/password; "
        f"-e CDM_SCHEMA=cdm -e WRITE_SCHEMA=results -e ARTIFACT_PATH=/artifacts -v {results}:/artifacts "
        "localhost:5001/x-fn:latest",
    ]
    assert results.is_dir()
    forward.terminate.assert_called_once()


def test_a_failing_run_local_stops_the_port_forward_and_does_not_show_the_password(commands, steps, monkeypatch):
    forward = MagicMock()
    monkeypatch.setattr(experiment.subprocess, "Popen", MagicMock(return_value=forward))
    commands.failing = "docker"

    result = CliRunner().invoke(experiment_group, ["run", "x", "--local"])

    assert result.exit_code == 3
    assert "pwd=" not in result.output
    forward.terminate.assert_called_once()
