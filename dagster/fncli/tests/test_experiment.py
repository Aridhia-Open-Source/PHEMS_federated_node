"""`fncli experiment` (fncli.cmds.experiment): what each command reads from an experiment's folder and runs."""

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
import yaml

from fncli.cmds import experiment
from fncli.cmds.experiment import (
    Database, ExperimentConfig, check_bootstrap, experiment_group, load_database, load_project,
)
from fncli.nodefile.loader import load_node_file
from fncli.tests.test_nodefile_diff import node_data

REPO_ROOT = Path(__file__).resolve().parents[3]
EXPERIMENTS = REPO_ROOT / "experiments" / "projects"
NODE = {"url": "http://localhost:5000", "kube_context": "kind-fn", "keycloak_namespace": "keycloak"}

PROJECT_ENV = """\
IMAGE=localhost:5001/x-fn:latest
RUN_TIMEOUT=60
"""


def bootstrap_data(database="x-db", secret="db-datasets-x", namespace="experiments") -> dict:
    """What an experiment's bootstrap.yaml holds: its dataset, and a secret read from the chart's"""
    label = f"{database}-dataset-creds"
    return {
        "version": 1,
        "node": NODE,
        "secrets": {label: {"values": {
            key: {"k8s_secret": {"name": secret, "namespace": namespace, "key": key.lower()}}
            for key in ("USERNAME", "PASSWORD")
        }}},
        "datasets": [{
            "name": database, "type": "postgres", "host": "db-datasets.experiments.svc", "port": 5432,
            "read_schema": "cdm", "write_schema": "results", "secret": label,
        }],
    }


def project_node_data(database="x-db") -> dict:
    """What bootstrap/examples/experiments/NAME.yaml holds: the project and its repositories, and the dataset by name only"""
    data = node_data()
    data["projects"][0].update(name="exp", datasets=[database])
    data["datasets"] = []
    del data["secrets"]["dataset-creds"]
    return data


def write_experiment(root: Path, name: str, database: str, user: str, secret: str, project_env: str | None = None,
                     node_project: bool = False):
    folder = root / "experiments" / "projects" / name
    folder.mkdir(parents=True)
    values = {"dbs": {name: {"name": database, "user": user, "secret": {"name": secret, "key": "password"}}}}
    (folder / "values.yaml").write_text(yaml.safe_dump(values))
    (folder / "bootstrap.yaml").write_text(yaml.safe_dump(bootstrap_data(database, secret)))
    if project_env is not None:
        (folder / "project.env").write_text(project_env)
    if node_project:
        examples = root / "bootstrap" / "examples" / "experiments"
        examples.mkdir(parents=True, exist_ok=True)
        (examples / f"{name}.yaml").write_text(yaml.safe_dump(project_node_data(database)))


@pytest.fixture(autouse=True)
def restore_env():
    """The commands and load_dotenv set variables in this process: put them back after each test."""
    with patch.dict(os.environ):
        yield


@pytest.fixture(autouse=True)
def repo(tmp_path, monkeypatch):
    """
    A repo root with a .dev.env and two experiments, and the data dir the release needs. x has a node project and
    run settings; y is only a dataset, like the demo's.
    """
    (tmp_path / ".dev.env").write_text("")
    write_experiment(tmp_path, "x", "x-db", "x_user", "db-datasets-x", PROJECT_ENV, node_project=True)
    write_experiment(tmp_path, "y", "y-db", "y_user", "db-datasets-y")
    (tmp_path / "data").mkdir()
    monkeypatch.setenv("FN_DATA_DIR", str(tmp_path / "data"))
    for key in ("FULL", "DEV_ENV", "TEST_PR_ENV", "TEST_PR_IMAGE"):
        monkeypatch.delenv(key, raising=False)
    # What .dev.env gives the dev project: an experiment must not run in it
    monkeypatch.setenv("TEST_PROJECT_NAME", "fn-dev")
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
    """The node-file and fncli steps the experiment commands chain, replaced by ones that note what they were given and see."""
    steps = []

    def step(name):
        def callback(**options):
            steps.append((name, options, dict(os.environ)))

        return click.Command(name, callback=callback)

    def node_file_step(name):
        def run(path, *args, **options):
            steps.append((name, {"file": path.name, "args": args, **options}, dict(os.environ)))

        return run

    monkeypatch.setattr(experiment, "apply_node_file", node_file_step("apply"))
    monkeypatch.setattr(experiment, "delete_node_file", node_file_step("delete"))
    monkeypatch.setattr(experiment, "start_sensor_command", step("start-sensor"))
    monkeypatch.setattr(experiment, "open_pr_command", step("open-pr"))
    monkeypatch.setattr(
        experiment, "get_k8s_secret", lambda secret_name, namespace, key: f"{secret_name}/{namespace}/{key}"
    )
    return steps


def invoke(*args):
    result = CliRunner().invoke(experiment_group, list(args))
    assert result.exit_code == 0, result.output
    return result


def test_the_project_env_wins_over_the_shell_and_the_rest_of_the_env_is_left_alone(monkeypatch):
    monkeypatch.setenv("IMAGE", "from-the-shell")

    config = load_project("x")

    assert os.environ["IMAGE"] == "localhost:5001/x-fn:latest"
    assert os.environ["TEST_PROJECT_NAME"] == "fn-dev"
    assert (config.image, config.run_timeout) == ("localhost:5001/x-fn:latest", 60)
    assert config.dev_env == {}


def test_the_dev_env_of_the_task_is_read_from_the_shell(monkeypatch):
    monkeypatch.setenv("DEV_ENV", '{"X_DEV": "1"}')

    assert load_project("x").dev_env == {"X_DEV": "1"}


def test_an_unknown_project_is_an_error():
    with pytest.raises(click.ClickException, match="No such project"):
        load_project("nope")


def test_a_project_without_a_project_env_cannot_be_built_or_run():
    with pytest.raises(click.ClickException, match="No project.env for y"):
        load_project("y")


def test_a_project_env_missing_a_value_is_rejected(repo, monkeypatch):
    (repo / "experiments" / "projects" / "x" / "project.env").write_text(PROJECT_ENV.replace("IMAGE=", "NOT_IMAGE="))
    monkeypatch.delenv("IMAGE", raising=False)

    with pytest.raises(ValidationError, match="required"):
        load_project("x")


def test_the_committed_project_envs_hold_the_run_settings_only():
    for name, timeout in (("uc1", 1800), ("attacker", 600)):
        values = {}
        for line in (EXPERIMENTS / name / "project.env").read_text().splitlines():
            if line and not line.startswith("#"):
                key, _, value = line.partition("=")
                values[key] = value
        assert set(values) - {"RESOURCES"} == {"IMAGE", "RUN_TIMEOUT"}
        assert int(values["RUN_TIMEOUT"]) == timeout
    assert not (EXPERIMENTS / "demo" / "project.env").exists()


def test_the_committed_attacker_project_env_is_a_complete_config():
    load_dotenv(EXPERIMENTS / "attacker" / "project.env", override=True)

    config = ExperimentConfig()

    assert (config.image, config.source_dir, config.run_timeout) == ("localhost:5001/attacker-fn:latest", "projects/attacker/image", 600)
    assert config.dev_env == {}


def test_the_database_is_read_from_values_yaml_and_the_schemas_from_bootstrap_yaml():
    assert load_database("x") == Database("x-db", "x_user", "db-datasets-x", "cdm", "results")


def test_a_bootstrap_yaml_that_names_another_dataset_than_values_yaml_is_refused(repo):
    data = bootstrap_data(database="other-db", secret="db-datasets-x")
    (repo / "experiments" / "projects" / "x" / "bootstrap.yaml").write_text(yaml.safe_dump(data))

    with pytest.raises(click.ClickException) as error:
        load_database("x")

    assert "its datasets are ['other-db'], but dbs.x.name in values.yaml is x-db" in error.value.message
    assert "secret" not in error.value.message


def test_a_bootstrap_yaml_that_reads_another_secret_or_namespace_than_the_chart_makes_is_refused(repo):
    path = repo / "experiments" / "projects" / "x" / "bootstrap.yaml"
    for data in (bootstrap_data(secret="db-datasets-other"), bootstrap_data(namespace="fn")):
        path.write_text(yaml.safe_dump(data))

        with pytest.raises(click.ClickException) as error:
            load_database("x")

        assert "dbs.x.secret.name in values.yaml is db-datasets-x in namespace experiments" in error.value.message
        assert "datasets are" not in error.value.message


def test_a_dataset_whose_secret_is_not_in_the_bootstrap_file_is_refused(repo):
    data = bootstrap_data()
    data["secrets"] = {}
    (repo / "experiments" / "projects" / "x" / "bootstrap.yaml").write_text(yaml.safe_dump(data))

    with pytest.raises(click.ClickException, match="its dataset's secret reads \\[\\]"):
        load_database("x")


def test_an_experiment_without_a_bootstrap_yaml_is_an_error(repo):
    (repo / "experiments" / "projects" / "y" / "bootstrap.yaml").unlink()

    with pytest.raises(click.ClickException, match="No bootstrap.yaml for y"):
        load_database("y")


@pytest.mark.parametrize("name", sorted(path.parent.name for path in EXPERIMENTS.glob("*/bootstrap.yaml")))
def test_every_committed_experiment_names_what_its_chart_makes(name):
    entry = yaml.safe_load((EXPERIMENTS / name / "values.yaml").read_text())["dbs"][name]
    node = load_node_file(EXPERIMENTS / name / "bootstrap.yaml")

    check_bootstrap(name, entry, node)

    assert node.projects == [] and node.repositories.triggers == [] and node.providers == []


def test_every_committed_node_project_is_assigned_a_dataset_that_an_experiment_makes():
    made = {
        dataset.name
        for path in EXPERIMENTS.glob("*/bootstrap.yaml") for dataset in load_node_file(path).datasets
    }
    files = [
        *(REPO_ROOT / "bootstrap" / "examples").glob("demo-*.yaml"),
        *(REPO_ROOT / "bootstrap" / "examples" / "experiments").glob("*.yaml"),
    ]
    assigned = {name for path in files for project in load_node_file(path).projects for name in project.datasets}

    assert files and assigned <= made, assigned - made


def test_up_installs_the_release_with_every_project_database(repo, commands):
    invoke("up")

    projects = repo / "experiments" / "projects"
    assert commands.lines == [
        f"helm upgrade --install experiments {repo}/experiments/chart --namespace experiments "
        f"--create-namespace -f {projects}/x/values.yaml -f {projects}/y/values.yaml --wait --timeout 5m",
    ]


def test_seed_checks_the_release_then_loads_the_seed_sql_as_the_charts_role(repo, commands, steps):
    invoke("seed", "x")

    projects = repo / "experiments" / "projects"
    assert commands.lines == [
        "helm status experiments --namespace experiments",
        f"{projects}/x/seed.sh",
        "kubectl exec -i -n experiments deploy/db-datasets -- psql -v ON_ERROR_STOP=1 -q -U x_user -d x-db",
    ]
    assert commands.calls[2][1]["input"] == "SEED SQL"
    assert steps == []


def test_seed_needs_no_project_env(commands, steps):
    invoke("seed", "y")

    assert commands.lines[2].endswith("-U y_user -d y-db")


def test_setup_checks_the_names_and_the_release_then_applies_the_dataset_and_then_the_node_project(commands, steps):
    invoke("setup", "x")

    assert commands.lines == ["helm status experiments --namespace experiments"]
    assert [(name, options["file"], options["yes"]) for name, options, _ in steps] == [
        ("apply", "bootstrap.yaml", True), ("apply", "x.yaml", True),
    ]
    assert all(options["args"] == (None,) for _, options, _ in steps)


def test_setup_of_an_experiment_with_no_node_project_applies_only_its_dataset(commands, steps):
    invoke("setup", "y")

    assert [(name, options["file"]) for name, options, _ in steps] == [("apply", "bootstrap.yaml")]


def test_setup_stops_on_names_that_do_not_match_before_anything_else(repo, commands, steps):
    path = repo / "experiments" / "projects" / "x" / "bootstrap.yaml"
    path.write_text(yaml.safe_dump(bootstrap_data(database="other-db")))

    result = CliRunner().invoke(experiment_group, ["setup", "x"])

    assert result.exit_code == 1
    assert "does not match values.yaml" in result.output
    assert commands.calls == [] and steps == []


@pytest.mark.parametrize("command", ["seed", "setup"])
def test_without_the_release_seed_and_setup_tell_you_to_run_up(command, commands, steps):
    commands.failing = "helm"

    result = CliRunner().invoke(experiment_group, [command, "x"])

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


def test_a_failing_command_stops_seed_with_its_exit_status(commands):
    commands.failing = "kubectl"

    result = CliRunner().invoke(experiment_group, ["seed", "x"])

    assert result.exit_code == 3


def test_run_takes_the_names_of_the_pull_request_from_the_node_project_not_the_dev_env(steps):
    invoke("run", "x")

    env = steps[1][2]
    assert env["TEST_PROJECT_NAME"] == "exp"
    assert env["TEST_TRIGGER_REPO"] == "trigger-repo"
    assert env["TEST_RESULTS_REPO"] == "results-repo"
    assert env["DEFAULT_PROJECT_DATASET"] == "x-db"


def test_run_starts_the_sensors_then_opens_a_watched_pr_with_the_image_and_dev_env(steps, monkeypatch):
    monkeypatch.setenv("DEV_ENV", '{"X_DEV": "1"}')

    invoke("run", "x")

    (sensors, _, _), (pr, options, env) = steps
    assert (sensors, pr) == ("start-sensor", "open-pr")
    assert steps[0][1] == {"group": "all", "name": None}
    assert options == {"kind": "watched", "merge": True, "watch": True, "timeout": 60}
    assert env["TEST_PR_IMAGE"] == "localhost:5001/x-fn:latest"
    assert json.loads(env["TEST_PR_ENV"]) == {"X_DEV": "1"}


def test_full_leaves_the_dev_env_out_of_the_pr(monkeypatch, steps):
    monkeypatch.setenv("DEV_ENV", '{"X_DEV": "1"}')
    monkeypatch.setenv("FULL", "1")

    invoke("run", "x")

    env = steps[1][2]
    assert "TEST_PR_ENV" not in env
    assert env["TEST_PR_IMAGE"] == "localhost:5001/x-fn:latest"


def test_run_of_an_experiment_with_no_node_project_is_an_error_before_anything_starts(repo, steps):
    (repo / "experiments" / "projects" / "y" / "project.env").write_text(PROJECT_ENV)

    result = CliRunner().invoke(experiment_group, ["run", "y"])

    assert result.exit_code == 1
    assert "y has no node project" in result.output
    assert steps == []


def test_build_bakes_the_projects_image_from_the_repo_root_and_pushes_it(repo, commands):
    invoke("build", "x")

    assert commands.lines == [
        f"docker buildx bake -f {repo}/docker-bake.hcl -f {repo}/experiments/projects/x/docker-bake.hcl x-fn --push"
    ]
    assert commands.calls[0][1]["cwd"] == repo


def test_teardown_deletes_the_node_project_first_and_then_the_dataset_with_the_globals(commands, steps):
    invoke("teardown", "x", "-y")

    assert [(name, options["file"], options["with_globals"], options["yes"]) for name, options, _ in steps] == [
        ("delete", "x.yaml", True, True), ("delete", "bootstrap.yaml", True, True),
    ]
    assert commands.calls == []


def test_teardown_of_an_experiment_with_no_node_project_deletes_only_its_dataset(steps):
    invoke("teardown", "y", "-y")

    assert [(name, options["file"]) for name, options, _ in steps] == [("delete", "bootstrap.yaml")]


def test_down_finds_every_experiment_by_its_bootstrap_yaml_then_uninstalls_the_release(repo, commands, steps):
    write_experiment(repo, "z", "z-db", "z_user", "db-datasets-z", node_project=True)

    invoke("down", "-y")

    assert [options["file"] for _, options, _ in steps] == [
        "x.yaml", "bootstrap.yaml", "bootstrap.yaml", "z.yaml", "bootstrap.yaml",
    ]
    assert commands.lines == ["helm uninstall experiments --namespace experiments"]


def test_down_does_not_need_a_project_env_to_find_an_experiment(repo, commands, steps):
    assert not list((repo / "experiments" / "projects" / "y").glob("project.env"))

    invoke("down", "-y")

    assert [options["file"] for _, options, _ in steps] == ["x.yaml", "bootstrap.yaml", "bootstrap.yaml"]


def test_run_local_runs_the_image_against_the_port_forward_and_stops_it(repo, commands, steps, monkeypatch):
    forward = MagicMock()
    popen = MagicMock(return_value=forward)
    monkeypatch.setattr(experiment.subprocess, "Popen", popen)
    monkeypatch.setenv("DEV_ENV", '{"X_DEV": "1"}')

    invoke("run", "x", "--local")

    results = repo / "experiments" / "results" / "x"
    assert popen.call_args.args[0] == ["kubectl", "port-forward", "-n", "experiments", "svc/db-datasets", "5434:5432"]
    assert commands.lines == [
        "pg_isready -h localhost -p 5434",
        "docker run --rm --network host -e X_DEV=1 "
        "-e CONNECTION_STRING=driver={PostgreSQL ANSI};Uid=x_user;Pwd=db-datasets-x/experiments/password;Server=localhost,5434;Database=x-db; "
        f"-e CDM_SCHEMA=cdm -e WRITE_SCHEMA=results -e ARTIFACT_PATH=/artifacts -v {results}:/artifacts "
        "localhost:5001/x-fn:latest",
    ]
    assert results.is_dir()
    forward.terminate.assert_called_once()
    assert steps == []


def test_a_failing_run_local_stops_the_port_forward_and_does_not_show_the_password(commands, steps, monkeypatch):
    forward = MagicMock()
    monkeypatch.setattr(experiment.subprocess, "Popen", MagicMock(return_value=forward))
    commands.failing = "docker"

    result = CliRunner().invoke(experiment_group, ["run", "x", "--local"])

    assert result.exit_code == 3
    assert "pwd=" not in result.output
    forward.terminate.assert_called_once()


@pytest.mark.parametrize("name, node_project", [("demo", False), ("uc1", True), ("attacker", True)])
def test_setup_and_teardown_work_on_the_committed_experiments(name, node_project, commands, steps, monkeypatch):
    """The demo has no node project of its own, uc1 and attacker have one: each is its dataset first, and the reverse on the way out"""
    monkeypatch.setattr(experiment, "experiments_dir", lambda: REPO_ROOT / "experiments")

    invoke("setup", name)
    invoke("teardown", name, "-y")

    project = [f"{name}.yaml"] if node_project else []
    assert [(step, options["file"]) for step, options, _ in steps] == [
        *[("apply", file) for file in ["bootstrap.yaml", *project]],
        *[("delete", file) for file in [*project, "bootstrap.yaml"]],
    ]


def test_down_goes_through_every_committed_experiment_and_uninstalls_the_release(commands, steps, monkeypatch):
    monkeypatch.setattr(experiment, "experiments_dir", lambda: REPO_ROOT / "experiments")

    invoke("down", "-y")

    assert [options["file"] for _, options, _ in steps] == [
        "attacker.yaml", "bootstrap.yaml", "bootstrap.yaml", "uc1.yaml", "bootstrap.yaml",
    ]
    assert commands.lines == ["helm uninstall experiments --namespace experiments"]
