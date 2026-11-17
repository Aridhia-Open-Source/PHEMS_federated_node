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
    Database, ExperimentConfig, experiment_group, load_database, load_project,
)
from fncli.node_config import load_resources, of_kind

REPO_ROOT = Path(__file__).resolve().parents[3]
EXPERIMENTS = REPO_ROOT / "experiments"
CONFIG = REPO_ROOT / "config"
NODE = {"url": "http://localhost:5000", "kube_context": "kind-fn", "keycloak_namespace": "keycloak"}

PROJECT_ENV = """\
RUN_TIMEOUT=60
"""
TRIGGER = {"spec": {"image": "localhost:5001/x-fn:latest", "env": {"BASE": "1"}}}


def project_resource(name="exp") -> dict:
    """What config/experiments/NAME.yaml holds, as far as the commands read it: the Project resource"""
    return {"apiVersion": "fn.aridhia.com/v1alpha1", "kind": "Project", "metadata": {"name": name, "namespace": "fn-operator"},
            "spec": {"datasets": ["x-db"], "repositories": {}}}


def write_experiment(root: Path, name: str, database: str, user: str, secret: str, project_env: str | None = None,
                     node_project: bool = False):
    folder = root / "experiments" / name
    folder.mkdir(parents=True)
    values = {"dbs": {name: {
        "name": database, "user": user, "secret": {"name": secret, "key": "password"},
        "readSchema": "cdm", "writeSchema": "results",
    }}}
    (folder / "values.yaml").write_text(yaml.safe_dump(values))
    if project_env is not None:
        (folder / "project.env").write_text(project_env)
        (folder / "trigger.json").write_text(json.dumps(TRIGGER))
    if node_project:
        config = root / "config" / "experiments"
        config.mkdir(parents=True, exist_ok=True)
        (config / f"{name}.yaml").write_text(yaml.safe_dump(project_resource()))


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
    context = tmp_path / "bootstrap" / "context.yaml"
    context.parent.mkdir()
    context.write_text(yaml.safe_dump({"node": NODE}))
    monkeypatch.setenv("FNCLI_CONTEXT", str(context))
    write_experiment(tmp_path, "x", "x-db", "x_user", "db-datasets-x", PROJECT_ENV, node_project=True)
    write_experiment(tmp_path, "y", "y-db", "y_user", "db-datasets-y")
    (tmp_path / "data").mkdir()
    monkeypatch.setenv("FN_DATA_DIR", str(tmp_path / "data"))
    for key in ("FULL", "DEV_ENV", "RUN_TIMEOUT"):
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


class FakeApi:
    """The backend client as far as `run` reads it: the project is on the node"""

    def find_project(self, name):
        return object() if name == "exp" else None


@pytest.fixture
def steps(monkeypatch):
    """The fncli steps the experiment commands chain, replaced by ones that note what they were given and see."""
    steps = []

    def step(name):
        def callback(**options):
            steps.append((name, options, dict(os.environ)))

        return click.Command(name, callback=callback)

    def gitea_setup(context, paths, rotate):
        steps.append(("gitea-setup", {"files": [path.name for path in paths], "rotate": rotate, "node": context.node.url}, dict(os.environ)))

    def trigger_pr(context, api, project, path, **options):
        # The file is a temporary one: note what it held
        steps.append(("trigger-pr", {"project": project, "trigger": json.loads(path.read_text()), **options}, dict(os.environ)))

    monkeypatch.setattr(experiment, "gitea_setup", gitea_setup)
    monkeypatch.setattr(experiment, "check_kube_context", lambda context: None)
    monkeypatch.setattr(experiment, "start_sensor_command", step("start-sensor"))
    monkeypatch.setattr(experiment, "trigger_pr", trigger_pr)
    monkeypatch.setattr(experiment, "open_target", lambda context: FakeApi())
    monkeypatch.setattr(
        experiment, "get_k8s_secret", lambda secret_name, namespace, key: f"{secret_name}/{namespace}/{key}"
    )
    return steps


def invoke(*args):
    result = CliRunner().invoke(experiment_group, list(args))
    assert result.exit_code == 0, result.output
    return result


def test_the_project_env_wins_over_the_shell_and_the_rest_of_the_env_is_left_alone(monkeypatch):
    monkeypatch.setenv("RUN_TIMEOUT", "5")
    monkeypatch.setenv("NAMESPACE", "fn")

    config = load_project("x")

    assert os.environ["RUN_TIMEOUT"] == "60"
    assert os.environ["NAMESPACE"] == "fn"
    assert config.run_timeout == 60
    assert config.dev_env == {}


def test_the_dev_env_of_the_task_is_read_from_the_shell(monkeypatch):
    monkeypatch.setenv("DEV_ENV", '{"X_DEV": "1"}')

    assert load_project("x").dev_env == {"X_DEV": "1"}


def test_an_unknown_experiment_is_an_error():
    with pytest.raises(click.ClickException, match="No such experiment"):
        load_project("nope")


def test_an_experiment_without_a_project_env_cannot_be_run():
    with pytest.raises(click.ClickException, match="No project.env for y"):
        load_project("y")


def test_the_committed_project_envs_hold_the_run_timeout_only():
    for name, timeout in (("uc1", 1800), ("attacker", 600)):
        values = {}
        for line in (EXPERIMENTS / name / "project.env").read_text().splitlines():
            if line and not line.startswith("#"):
                key, _, value = line.partition("=")
                values[key] = value
        assert set(values) == {"RUN_TIMEOUT"}
        assert int(values["RUN_TIMEOUT"]) == timeout
    assert not (EXPERIMENTS / "demo" / "project.env").exists()


def test_the_committed_uc1_project_env_is_a_complete_config():
    load_dotenv(EXPERIMENTS / "uc1" / "project.env", override=True)

    config = ExperimentConfig()

    assert config.run_timeout == 1800
    assert config.dev_env == {}


@pytest.mark.parametrize("name", ["uc1", "attacker"])
def test_the_committed_trigger_files_ask_for_the_image_the_experiments_bake_file_builds(name):
    trigger = json.loads((EXPERIMENTS / name / "trigger.json").read_text())

    assert list(trigger) == ["spec"]
    assert trigger["spec"]["image"] == f"localhost:5001/{name}-fn:latest"
    assert f'target "{name}-fn"' in (EXPERIMENTS / name / "docker-bake.hcl").read_text()


def test_the_attackers_trigger_file_carries_the_limits_its_pod_must_get():
    spec = json.loads((EXPERIMENTS / "attacker" / "trigger.json").read_text())["spec"]

    assert spec["compute"] == {
        "limits": {"cpu": "500m", "memory": "256Mi"}, "requests": {"cpu": "100m", "memory": "64Mi"},
    }


def test_the_example_trigger_files_are_spec_files():
    for path in (REPO_ROOT / "triggers" / "examples").glob("*.json"):
        trigger = json.loads(path.read_text())
        assert list(trigger) == ["spec"] and trigger["spec"]["image"] == "localhost:5001/demo-fn:latest", path
    failing = json.loads((REPO_ROOT / "triggers" / "examples" / "demo-failing.json").read_text())
    assert failing["spec"]["env"] == {"DEMO_FORCE_EXIT_CODE": "1"}


def test_the_database_and_its_schemas_are_read_from_values_yaml():
    assert load_database("x") == Database("x-db", "x_user", "db-datasets-x", "cdm", "results")


@pytest.mark.parametrize("name", ["demo", "uc1", "attacker"])
def test_every_committed_experiment_gives_its_database_and_schemas(name, monkeypatch):
    monkeypatch.setattr(experiment, "experiments_dir", lambda: EXPERIMENTS)

    database = load_database(name)

    assert (database.read_schema, database.write_schema) == ("cdm", "results")


def test_every_committed_project_is_assigned_a_dataset_that_an_experiment_makes():
    made = {
        yaml.safe_load(path.read_text())["dbs"][path.parent.name]["name"]
        for path in EXPERIMENTS.glob("*/values.yaml") if path.parent.name != "chart"
    }
    files = [CONFIG / "demo.yaml", CONFIG / "github" / "demo-github.yaml", *(CONFIG / "experiments").glob("*.yaml")]
    assigned = {name for project in of_kind(load_resources(files), "Project") for name in project["spec"]["datasets"]}

    assert assigned and assigned <= made, assigned - made


def test_uc1_and_attacker_have_their_node_config():
    assert {"uc1", "attacker"} <= {path.stem for path in (CONFIG / "experiments").glob("*.yaml")}


def test_the_chart_makes_a_dataset_and_its_node_secret_for_every_database():
    template = (EXPERIMENTS / "chart" / "templates" / "node-config.yaml").read_text()

    assert "kind: Dataset" in template and "kind: NodeSecret" in template
    assert "range $key, $db := .Values.dbs" in template


def test_up_installs_the_release_with_every_experiments_database(repo, commands):
    invoke("deploy")

    experiments = repo / "experiments"
    assert commands.lines == [
        f"helm upgrade --install experiments {repo}/experiments/chart --namespace experiments "
        f"--create-namespace -f {experiments}/x/values.yaml -f {experiments}/y/values.yaml --wait --timeout 5m",
    ]


def test_seed_checks_the_release_then_loads_the_seed_sql_as_the_charts_role(repo, commands, steps):
    invoke("seed", "x")

    experiments = repo / "experiments"
    assert commands.lines == [
        "helm status experiments --namespace experiments",
        f"{experiments}/x/seed.sh",
        "kubectl exec -i -n experiments deploy/db-datasets -- psql -v ON_ERROR_STOP=1 -q -U x_user -d x-db",
    ]
    assert commands.calls[2][1]["input"] == "SEED SQL"
    assert steps == []


def test_seed_needs_no_project_env_and_no_context(repo, commands, steps, monkeypatch):
    monkeypatch.delenv("FNCLI_CONTEXT")
    (repo / "bootstrap" / "context.yaml").unlink()

    invoke("seed", "y")

    assert commands.lines[2].endswith("-U y_user -d y-db")


def test_setup_checks_the_release_waits_for_the_dataset_then_sets_up_gitea_and_applies_the_project(repo, commands, steps):
    invoke("setup", "x")

    files = f"-f {repo}/config/gitea.yaml -f {repo}/config/experiments/x.yaml"
    assert commands.lines == [
        "helm status experiments --namespace experiments",
        "kubectl wait --for=jsonpath={.status.synced}=true --timeout=180s -n experiments "
        "datasets.fn.aridhia.com/x-db nodesecrets.fn.aridhia.com/x-db-dataset-creds",
        f"kubectl apply {files}",
        f"kubectl wait --for=jsonpath={{.status.synced}}=true --timeout=180s {files}",
    ]
    assert [(name, options["files"], options["rotate"]) for name, options, _ in steps] == [("gitea-setup", ["x.yaml"], ())]


def test_setup_of_an_experiment_with_no_node_project_only_waits_for_its_dataset(commands, steps):
    invoke("setup", "y")

    assert commands.lines[1:] == [
        "kubectl wait --for=jsonpath={.status.synced}=true --timeout=180s -n experiments "
        "datasets.fn.aridhia.com/y-db nodesecrets.fn.aridhia.com/y-db-dataset-creds",
    ]
    assert steps == []


@pytest.mark.parametrize("command", ["seed", "setup"])
def test_without_the_release_seed_and_setup_tell_you_to_run_up(command, commands, steps):
    commands.failing = "helm"

    result = CliRunner().invoke(experiment_group, [command, "x"])

    assert result.exit_code == 1
    assert "fncli experiment deploy" in result.output
    assert len(commands.calls) == 1
    assert steps == []


@pytest.mark.parametrize("command", ["setup", "run", "teardown", "down"])
def test_the_commands_that_talk_to_the_node_need_a_context_file(command, repo, commands, steps, monkeypatch):
    monkeypatch.delenv("FNCLI_CONTEXT")
    (repo / "bootstrap" / "context.yaml").unlink()
    args = [command, "-y"] if command in ("teardown", "down") else [command]

    result = CliRunner().invoke(experiment_group, [args[0], *(["x"] if command != "down" else []), *args[1:]])

    assert result.exit_code == 2
    assert "context.yaml not found, as given or under bootstrap/ from here up" in result.output


def test_up_makes_the_database_directory_writable_for_postgres(repo, commands):
    invoke("deploy")

    assert (repo / "data" / "experiments" / "datasets").stat().st_mode & 0o777 == 0o777


def test_up_without_the_data_dir_stops_before_helm(repo, commands):
    (repo / "data").rmdir()

    result = CliRunner().invoke(experiment_group, ["deploy"])

    assert result.exit_code == 1
    assert "cluster.sh up" in result.output
    assert commands.calls == []


def test_a_failing_command_stops_seed_with_its_exit_status(commands):
    commands.failing = "kubectl"

    result = CliRunner().invoke(experiment_group, ["seed", "x"])

    assert result.exit_code == 3


def test_run_triggers_the_node_project_and_puts_nothing_in_the_env(steps, monkeypatch):
    monkeypatch.setenv("TEST_PROJECT_NAME", "fn-dev")  # an old .dev.env: not read, not changed
    for name in ("TEST_TRIGGER_REPO", "TEST_RESULTS_REPO", "DEFAULT_PROJECT_DATASET", "NEXUS_API_URL"):
        monkeypatch.delenv(name, raising=False)

    invoke("run", "x")

    _, options, env = steps[1]
    assert options["project"] == "exp"
    assert env["TEST_PROJECT_NAME"] == "fn-dev"
    assert not {"TEST_TRIGGER_REPO", "TEST_RESULTS_REPO", "DEFAULT_PROJECT_DATASET", "NEXUS_API_URL"} & set(env)


def test_run_starts_the_sensors_then_triggers_the_project_with_the_trigger_file_and_dev_env(steps, monkeypatch):
    monkeypatch.setenv("DEV_ENV", '{"X_DEV": "1"}')

    invoke("run", "x")

    (sensors, _, _), (pr, options, _) = steps
    assert (sensors, pr) == ("start-sensor", "trigger-pr")
    assert steps[0][1] == {"group": "all", "name": None}
    assert options == {
        "project": "exp", "merge": True, "watch": True, "timeout": 60,
        "trigger": {"spec": {"image": "localhost:5001/x-fn:latest", "env": {"BASE": "1", "X_DEV": "1"}}},
    }


def test_full_leaves_the_dev_env_out_of_the_pr(monkeypatch, steps):
    monkeypatch.setenv("DEV_ENV", '{"X_DEV": "1"}')
    monkeypatch.setenv("FULL", "1")

    invoke("run", "x")

    assert steps[1][1]["trigger"] == TRIGGER


def test_run_of_an_experiment_with_no_node_project_is_an_error_before_anything_starts(repo, steps):
    (repo / "experiments" / "y" / "project.env").write_text(PROJECT_ENV)
    (repo / "experiments" / "y" / "trigger.json").write_text(json.dumps(TRIGGER))

    result = CliRunner().invoke(experiment_group, ["run", "y"])

    assert result.exit_code == 1
    assert "y has no node project" in result.output
    assert steps == []


def test_run_of_a_project_that_setup_has_not_made_is_an_error_before_the_sensors_start(steps, monkeypatch):
    monkeypatch.setattr(experiment, "open_target", lambda context: SimpleNamespace(find_project=lambda name: None))

    result = CliRunner().invoke(experiment_group, ["run", "x"])

    assert result.exit_code == 1
    assert "Project exp is not on the node: run `fncli experiment setup x` first" in result.output
    assert steps == []


def test_run_of_an_experiment_without_a_trigger_file_is_an_error(repo, steps):
    (repo / "experiments" / "x" / "trigger.json").unlink()

    result = CliRunner().invoke(experiment_group, ["run", "x"])

    assert result.exit_code == 1 and "No trigger.json for x" in result.output
    assert steps == []


def test_build_bakes_the_experiments_image_from_the_repo_root_and_pushes_it(repo, commands):
    invoke("build", "x")

    assert commands.lines == [
        f"docker buildx bake -f {repo}/docker-bake.hcl -f {repo}/experiments/x/docker-bake.hcl x-fn --push"
    ]
    assert commands.calls[0][1]["cwd"] == repo


def test_teardown_deletes_the_node_config_and_leaves_the_dataset(repo, commands, steps):
    invoke("teardown", "x", "-y")

    assert commands.lines == [f"kubectl delete --ignore-not-found --timeout=180s -f {repo}/config/experiments/x.yaml"]
    assert steps == []


def test_teardown_of_an_experiment_with_no_node_project_does_nothing(commands, steps):
    invoke("teardown", "y", "-y")

    assert commands.calls == []


def test_down_tears_down_every_experiment_then_uninstalls_the_release(repo, commands, steps):
    write_experiment(repo, "z", "z-db", "z_user", "db-datasets-z", node_project=True)

    invoke("down", "-y")

    assert commands.lines == [
        f"kubectl delete --ignore-not-found --timeout=180s -f {repo}/config/experiments/x.yaml",
        f"kubectl delete --ignore-not-found --timeout=180s -f {repo}/config/experiments/z.yaml",
        "helm uninstall experiments --namespace experiments",
    ]


def test_the_chart_and_the_other_folders_of_experiments_are_not_experiments(repo, commands):
    (repo / "experiments" / "chart").mkdir()
    (repo / "experiments" / "chart" / "values.yaml").write_text("dbs: {}")
    (repo / "experiments" / "sources").mkdir()

    invoke("deploy")

    assert "chart/values.yaml" not in commands.lines[0]
    assert commands.lines[0].count(" -f ") == 2


def test_run_local_runs_the_image_of_the_trigger_file_against_the_port_forward_and_stops_it(repo, commands, steps, monkeypatch):
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


@pytest.mark.parametrize("name, applied", [("demo", False), ("uc1", True), ("attacker", True)])
def test_setup_and_teardown_work_on_the_committed_experiments(name, applied, commands, steps, monkeypatch):
    """The demo has no node project of its own, uc1 and attacker have one"""
    monkeypatch.setattr(experiment, "experiments_dir", lambda: REPO_ROOT / "experiments")

    invoke("setup", name)
    invoke("teardown", name, "-y")

    assert [options["files"] for _, options, _ in steps] == ([[f"{name}.yaml"]] if applied else [])
    assert any(line.startswith("kubectl delete") for line in commands.lines) == applied


def test_down_goes_through_every_committed_experiment_and_uninstalls_the_release(commands, steps, monkeypatch):
    monkeypatch.setattr(experiment, "experiments_dir", lambda: REPO_ROOT / "experiments")

    invoke("down", "-y")

    assert [line.rsplit("/", 1)[-1] for line in commands.lines] == [
        "attacker.yaml", "uc1.yaml", "helm uninstall experiments --namespace experiments",
    ]
