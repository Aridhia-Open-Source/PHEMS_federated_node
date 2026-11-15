"""
`fncli experiment` runs real experiments against the dev node, see experiments/README.md. Each experiment is a folder
experiments/NAME/ that holds its database for the chart (values.yaml: the database, its login's Secret and the
dataset's schemas), its seed, its image and docker-bake.hcl, its trigger file (trigger.json, the image and anything
else the task is asked for), and project.env with the settings of `run` only (no secrets; it wins over .dev.env and the
shell). The chart makes each database's Dataset and NodeSecret resources (ADR 0032), which the nexus operator syncs.
Its project and repositories are the resources of config/experiments/NAME.yaml, if it has one: `setup` makes its Gitea
repositories and Secrets (`fncli gitea setup`) and kubectl applies it, `teardown` deletes it. `deploy`, `seed`,
`setup`, `run` and `teardown` can be repeated after a failure.
"""

import json
import logging
import os
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

import click
import yaml
from dotenv import find_dotenv, load_dotenv
from pydantic import Field

from app.config import EnvConfig
from fncli.cmds.gitea import gitea_setup
from fncli.cmds.sensor import start_sensor_command
from fncli.cmds.target import check_kube_context, context_option, open_target
from fncli.cmds.trigger import trigger_pr
from fncli.context import Context
from fncli import node_config
from fncli.k8s import get_k8s_secret

logger = logging.getLogger("experiment")

# Not NAMESPACE: that is the node's own namespace, which the Gitea config reads from the env.
NAMESPACE = "experiments"
RELEASE = "experiments"
DATABASE_PORT = 5432


class ReleaseConfig(EnvConfig):
    """What the experiments release needs from the host."""

    # cluster.sh bind-mounts this into the kind node
    fn_data_dir: Path = Field(default=Path.home() / ".fn" / "data", alias="FN_DATA_DIR")


class ExperimentConfig(ReleaseConfig):
    """What project.env sets for running the experiment, and the host settings that can be set in the env."""

    run_timeout: int = Field(default=0, alias="RUN_TIMEOUT")
    # Extra env for the task, as JSON, e.g. '{"EXAMPLE_FLAG": "1"}': set in the shell, not in project.env
    dev_env: dict[str, str] = Field(default={}, alias="DEV_ENV", validate_default=False)
    # `run --local`'s port-forward. 5432 is the node's own Postgres.
    local_port: int = Field(default=5434, alias="EXPERIMENTS_LOCAL_PORT")


def experiments_dir() -> Path:
    """experiments/ of the checkout fncli is run in: the repo root is where .dev.env is found."""
    dev_env = find_dotenv(".dev.env", usecwd=True)
    if not dev_env:
        raise click.ClickException(".dev.env not found: run this from inside the repo")
    return Path(dev_env).parent / "experiments"


def experiment_dir(name: str) -> Path:
    path = experiments_dir() / name
    if not path.is_dir():
        raise click.ClickException(f"No such experiment: {path}")
    return path


def trigger_file(name: str) -> Path:
    """The trigger file `run` asks the node for: the experiment's image, in its own folder"""
    path = experiment_dir(name) / "trigger.json"
    if not path.is_file():
        raise click.ClickException(f"No trigger.json for {name}: {path}")
    return path


def config_dir() -> Path:
    return experiments_dir().parent / "config"


def config_file(name: str) -> Path | None:
    """The experiment's node config, its project and repositories, if it has one"""
    path = config_dir() / "experiments" / f"{name}.yaml"
    return path if path.is_file() else None


def project_name(name: str) -> str:
    """The name of the Project resource in the experiment's node config"""
    path = config_file(name)
    if path is None:
        raise click.ClickException(f"{name} has no node project: config/experiments/{name}.yaml")
    return node_config.of_kind(node_config.load_resources([path]), "Project")[0]["metadata"]["name"]


@dataclass(frozen=True)
class Database:
    """The experiment's database as the chart makes it (values.yaml), and the schemas its dataset reads and writes"""

    name: str  # the database, and the dataset's name in the node
    username: str
    secret_name: str  # the chart's Secret in NAMESPACE: `username` and `password`
    read_schema: str
    write_schema: str


def load_database(name: str) -> Database:
    """The database of experiment NAME: its `dbs.NAME` entry in values.yaml"""
    entry = yaml.safe_load((experiment_dir(name) / "values.yaml").read_text())["dbs"][name]
    return Database(entry["name"], entry["user"], entry["secret"]["name"], entry["readSchema"], entry["writeSchema"])


def load_project(name: str) -> ExperimentConfig:
    """The group has loaded .dev.env without overriding what is set: the project's values must win."""
    env_file = experiment_dir(name) / "project.env"
    if not env_file.is_file():
        raise click.ClickException(f"No project.env for {name}: {env_file}")
    load_dotenv(env_file, override=True)
    return ExperimentConfig()


def task_env(config: ExperimentConfig) -> dict[str, str]:
    """The task's env for this run: the project's DEV_ENV, unless FULL=1."""
    return {} if os.environ.get("FULL") == "1" else config.dev_env


def run(command: list[str], **kwargs) -> subprocess.CompletedProcess:
    """
    Run a command and exit with its status if it fails. The command is not echoed or put in
    a traceback: the `run --local` one carries the database password.
    """
    result = subprocess.run(command, **kwargs)
    if result.returncode:
        raise click.exceptions.Exit(result.returncode)
    return result


def install_release(config: ReleaseConfig):
    """Install or upgrade the experiments release, with the database of every project."""
    if not config.fn_data_dir.is_dir():
        raise click.ClickException(f"{config.fn_data_dir} does not exist - run ./scripts/cluster.sh up first")
    host_dir = config.fn_data_dir / "experiments" / "datasets"
    host_dir.mkdir(parents=True, exist_ok=True)
    # As in deploy.sh: world-writable until Postgres initialises it and takes ownership.
    if host_dir.stat().st_uid == os.geteuid():
        host_dir.chmod(0o777)
    values = [arg for name in experiment_names() for arg in ("-f", str(experiment_dir(name) / "values.yaml"))]
    run([
        "helm", "upgrade", "--install", RELEASE, str(experiments_dir() / "chart"),
        "--namespace", NAMESPACE, "--create-namespace", *values, "--wait", "--timeout", "5m",
    ])


def release_installed() -> bool:
    return subprocess.run(
        ["helm", "status", RELEASE, "--namespace", NAMESPACE], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    ).returncode == 0


def seed_database(name: str, database: Database):
    """Load the project's seed SQL, which recreates its schemas. As the project's role over the pod's local socket, so no port-forward is needed."""
    sql = run([str(experiment_dir(name) / "seed.sh")], stdout=subprocess.PIPE, text=True).stdout
    run(
        [
            "kubectl", "exec", "-i", "-n", NAMESPACE, "deploy/db-datasets", "--",
            "psql", "-v", "ON_ERROR_STOP=1", "-q", "-U", database.username, "-d", database.name,
        ],
        input=sql,
        text=True,
        stdout=subprocess.DEVNULL,
    )


name_argument = click.argument("name")


@click.group("experiment")
def experiment_group():
    """Run a real experiment against the dev node: set it up, build its image, run it."""


@experiment_group.command("deploy")
def deploy_command():
    """Install or upgrade the experiments release: Postgres with every project's database. Safe to rerun."""
    install_release(ReleaseConfig())


def require_release():
    if not release_installed():
        raise click.ClickException("No experiments deployment: run `fncli experiment deploy` first")


@experiment_group.command("seed")
@name_argument
def seed_command(name):
    """Load NAME's dummy data into its database on the experiments release (`up`). Its schemas are recreated. Safe to rerun."""
    database = load_database(name)
    require_release()
    logger.info(f"=== Seeding {database.name} ===")
    seed_database(name, database)


@experiment_group.command("setup")
@name_argument
@context_option
def setup_command(name, context):
    """
    Register NAME in the node, against its database on the experiments release (`deploy`): wait for the chart's
    Dataset and NodeSecret of its database to sync, then, if it has config/experiments/NAME.yaml, make its Gitea
    repositories and Secrets (`fncli gitea setup`), kubectl apply it with config/gitea.yaml and wait for it to sync.
    Safe to rerun.
    """
    database = load_database(name)
    require_release()
    check_kube_context(context)
    logger.info(f"=== Waiting for dataset {database.name} to sync ===")
    node_config.wait_synced(
        "-n", NAMESPACE, f"datasets.fn.aridhia.com/{database.name}", f"nodesecrets.fn.aridhia.com/{database.name}-dataset-creds",
    )
    path = config_file(name)
    if path is None:
        return
    logger.info(f"=== Setting up node config {path.name} ===")
    gitea_setup(context, [path], ())
    files = [config_dir() / "gitea.yaml", path]
    node_config.apply(files)
    node_config.wait_synced(*node_config.file_args(files))


@experiment_group.command("build")
@name_argument
def build_command(name):
    """Build NAME's image with the project's docker-bake.hcl and push it to the kind registry."""
    repo = experiments_dir().parent
    # Bake contexts are relative to the repo root
    command = [
        "docker", "buildx", "bake",
        "-f", str(repo / "docker-bake.hcl"),
        "-f", str(experiment_dir(name) / "docker-bake.hcl"),
        f"{name}-fn", "--push",
    ]
    run(command, cwd=repo)


@experiment_group.command("run")
@name_argument
@context_option
@click.option("--local", is_flag=True, help="Run the image in docker against its database, with no node.")
@click.pass_context
def run_command(ctx, name, context, local):
    """
    Open and merge a trigger PR with NAME's trigger.json and watch its task. With --local, run the
    image in docker against its database instead, with no node. The project's DEV_ENV is
    added to the task's env; FULL=1 leaves it out.
    """
    config = load_project(name)
    trigger = json.loads(trigger_file(name).read_text())
    if local:
        run_local(name, config, trigger["spec"]["image"])
        return
    project = project_name(name)
    api = open_target(context)
    if api.find_project(project) is None:
        raise click.ClickException(f"Project {project} is not on the node: run `fncli experiment setup {name}` first")
    ctx.invoke(start_sensor_command, group="all", name=None)
    env = task_env(config)
    logger.info(f"Task env: {json.dumps(env)}")
    trigger["spec"]["env"] = {**trigger["spec"].get("env", {}), **env}
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "trigger.json"
        path.write_text(json.dumps(trigger))
        trigger_pr(context, api, project, path, merge=True, watch=True, timeout=config.run_timeout)


def run_local(name: str, config: ExperimentConfig, image: str):
    """NAME's image in docker against its database through a port-forward. Results go to experiments/results/NAME."""
    database = load_database(name)
    password = get_k8s_secret(database.secret_name, NAMESPACE, "password")
    out_dir = experiments_dir() / "results" / name
    out_dir.mkdir(parents=True, exist_ok=True)

    port_forward = subprocess.Popen(
        ["kubectl", "port-forward", "-n", NAMESPACE, "svc/db-datasets", f"{config.local_port}:{DATABASE_PORT}"],
        stdout=subprocess.DEVNULL,
    )
    try:
        while subprocess.run(
            ["pg_isready", "-h", "localhost", "-p", str(config.local_port)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        ).returncode:
            time.sleep(1)
        env = task_env(config)
        logger.info(f"Results: {out_dir}")
        logger.info(f"Task env: {json.dumps(env)}")
        # The experiments database is Postgres; same form as the node's (app/definitions/pipes.py).
        connection = (
            f"driver={{PostgreSQL ANSI}};Uid={database.username};Pwd={password};"
            f"Server=localhost,{config.local_port};Database={database.name};"
        )
        run([
            "docker", "run", "--rm", "--network", "host",
            *[arg for key, value in env.items() for arg in ("-e", f"{key}={value}")],
            "-e", f"CONNECTION_STRING={connection}",
            "-e", f"CDM_SCHEMA={database.read_schema}",
            "-e", f"WRITE_SCHEMA={database.write_schema}",
            "-e", "ARTIFACT_PATH=/artifacts",
            "-v", f"{out_dir}:/artifacts",
            image,
        ])
    finally:
        port_forward.terminate()


def experiment_names() -> list[str]:
    """Every experiment: the folders under experiments/ with a values.yaml, but the chart's."""
    return sorted(path.parent.name for path in experiments_dir().glob("*/values.yaml") if path.parent.name != "chart")


def teardown_experiment(context: Context, name: str):
    """
    Remove what `setup` applied for NAME: `kubectl delete` of config/experiments/NAME.yaml, its project, repositories
    and their NodeSecrets. The dataset is the chart's and stays until `down`. Gitea and the Secrets are left alone.
    """
    path = config_file(name)
    if path is None:
        return
    check_kube_context(context)
    logger.info(f"=== Tearing down node config {path.name} ===")
    node_config.delete([path])


@experiment_group.command("teardown")
@name_argument
@context_option
@click.confirmation_option("-y", "--yes", prompt="Delete the experiment's node project and repositories (if any) from the node?")
def teardown_command(name, context):
    """
    Remove what `setup` applied for NAME: its project and repositories (config/experiments/NAME.yaml). The dataset,
    the Gitea repos and OAuth apps, the experiments release and NAME's database stay. Safe to rerun.
    """
    teardown_experiment(context, name)


@experiment_group.command("down")
@context_option
@click.confirmation_option(
    "-y", "--yes", prompt="Tear down every experiment's node project and uninstall the experiments release?"
)
def down_command(context):
    """
    Tear down every experiment's node project, then uninstall the experiments release, which deletes the datasets'
    resources (the operator soft-deletes them in nexus-api). The secrets and database files stay, so a later `setup`
    gets the same data back. A dataset still assigned to a project outside the experiments (a demo project, say) stays
    Terminating until that project is deleted.
    """
    for name in experiment_names():
        teardown_experiment(context, name)
    run(["helm", "uninstall", RELEASE, "--namespace", NAMESPACE])


COMMANDS = [experiment_group]
