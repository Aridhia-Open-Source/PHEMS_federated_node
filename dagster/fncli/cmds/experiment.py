"""
`fncli experiment` runs real experiments against the dev node, see experiments/README.md.
Each experiment's names are in experiments/projects/NAME/project.env (no secrets), which wins
over .dev.env and the shell. `setup` and `run` can be repeated after a failure.
"""

import json
import logging
import os
import subprocess
import time
from pathlib import Path

import click
from dotenv import find_dotenv, load_dotenv
from pydantic import Field

from app.config import EnvConfig
from fncli.cmds.actions import open_pr_command, setup_project_command
from fncli.cmds.sensor import start_sensor_command
from fncli.k8s import get_k8s_secret

logger = logging.getLogger("experiment")

# Not NAMESPACE: that is the node's own namespace, which the Gitea config reads from the env.
NAMESPACE = "experiments"
RELEASE = "experiments"
DATABASE_PORT = 5432


class ExperimentConfig(EnvConfig):
    """What project.env sets for the experiment, and the two host settings that can be set in the env."""

    image: str = Field(default="", alias="IMAGE")
    # Relative to experiments/
    source_dir: str = Field(default="", alias="SOURCE_DIR")
    database: str = Field(default="", alias="DATASET_NAME")
    username: str = Field(default="", alias="DATASET_USERNAME")
    secret_name: str = Field(default="", alias="DATASET_SECRET_NAME")
    read_schema: str = Field(default="", alias="DATASET_SCHEMA")
    write_schema: str = Field(default="", alias="DATASET_SCHEMA_WRITE")
    project_name: str = Field(default="", alias="TEST_PROJECT_NAME")
    run_timeout: int = Field(default=0, alias="RUN_TIMEOUT")
    # Extra env for the task, as JSON, e.g. '{"UC1_DEV": "1"}'
    dev_env: dict[str, str] = Field(default={}, alias="DEV_ENV", validate_default=False)
    # cluster.sh bind-mounts this into the kind node
    fn_data_dir: Path = Field(default=Path.home() / ".fn" / "data", alias="FN_DATA_DIR")
    # run-local's port-forward. 5432 is the node's own Postgres.
    local_port: int = Field(default=5434, alias="EXPERIMENTS_LOCAL_PORT")


def experiments_dir() -> Path:
    """experiments/ of the checkout fncli is run in: the repo root is where .dev.env is found."""
    dev_env = find_dotenv(".dev.env", usecwd=True)
    if not dev_env:
        raise click.ClickException(".dev.env not found: run this from inside the repo")
    return Path(dev_env).parent / "experiments"


def load_project(name: str) -> ExperimentConfig:
    """The group has loaded .dev.env without overriding what is set: the project's values must win."""
    env_file = experiments_dir() / "projects" / name / "project.env"
    if not env_file.is_file():
        raise click.ClickException(f"No such project: {env_file}")
    load_dotenv(env_file, override=True)
    return ExperimentConfig()


def task_env(config: ExperimentConfig) -> dict[str, str]:
    """The task's env for this run: the project's DEV_ENV, unless FULL=1."""
    return {} if os.environ.get("FULL") == "1" else config.dev_env


def run(command: list[str], **kwargs) -> subprocess.CompletedProcess:
    """
    Run a command and exit with its status if it fails. The command is not echoed or put in
    a traceback: the run-local one carries the database password.
    """
    result = subprocess.run(command, **kwargs)
    if result.returncode:
        raise click.exceptions.Exit(result.returncode)
    return result


def install_release(config: ExperimentConfig):
    """Install or upgrade the experiments release, with the database of every project."""
    if not config.fn_data_dir.is_dir():
        raise click.ClickException(f"{config.fn_data_dir} does not exist - run ./scripts/cluster.sh up first")
    host_dir = config.fn_data_dir / "experiments" / "datasets"
    host_dir.mkdir(parents=True, exist_ok=True)
    # As in deploy.sh: world-writable until Postgres initialises it and takes ownership.
    if host_dir.stat().st_uid == os.geteuid():
        host_dir.chmod(0o777)
    values = [
        arg
        for path in sorted((experiments_dir() / "projects").glob("*/values.yaml"))
        for arg in ("-f", str(path))
    ]
    run([
        "helm", "upgrade", "--install", RELEASE, str(experiments_dir() / "chart"),
        "--namespace", NAMESPACE, "--create-namespace", *values, "--wait", "--timeout", "5m",
    ])


def seed_database(name: str, config: ExperimentConfig):
    """Load the project's seed SQL, which recreates its schemas. As the project's role over the pod's local socket, so no port-forward is needed."""
    sql = run([str(experiments_dir() / "projects" / name / "seed.sh")], stdout=subprocess.PIPE, text=True).stdout
    run(
        [
            "kubectl", "exec", "-i", "-n", NAMESPACE, "deploy/db-datasets", "--",
            "psql", "-v", "ON_ERROR_STOP=1", "-q", "-U", config.username, "-d", config.database,
        ],
        input=sql,
        text=True,
        stdout=subprocess.DEVNULL,
    )


name_argument = click.argument("name")


@click.group("experiment")
def experiment_group():
    """Run a real experiment against the dev node: set it up, build its image, run it."""


@experiment_group.command("setup")
@name_argument
@click.pass_context
def setup_command(ctx, name):
    """
    Set up NAME for a run: install or upgrade the experiments release, seed NAME's database
    (its schemas are recreated), then set up its node project with the global and project
    resources. Safe to rerun.
    """
    config = load_project(name)
    logger.info("=== Installing the experiments release ===")
    install_release(config)
    # Generated by the chart, so read back from its secret.
    password = get_k8s_secret(config.secret_name, NAMESPACE, "password")
    logger.info(f"=== Seeding {config.database} ===")
    seed_database(name, config)
    logger.info(f"=== Setting up node project {config.project_name} ===")
    os.environ["CLUSTER_DATASET_HOST"] = f"db-datasets.{NAMESPACE}.svc"
    os.environ["DATASET_PORT"] = str(DATABASE_PORT)
    os.environ["DATASET_PASSWORD"] = password
    ctx.invoke(setup_project_command)


@experiment_group.command("build")
@name_argument
def build_command(name):
    """Build NAME's image from its source and push it to the kind registry."""
    config = load_project(name)
    run(["docker", "build", "-t", config.image, str(experiments_dir() / config.source_dir)])
    run(["docker", "push", config.image])


@experiment_group.command("run")
@name_argument
@click.pass_context
def run_command(ctx, name):
    """
    Open and merge a trigger PR for NAME's image and watch its task. The project's DEV_ENV
    is passed to the task; FULL=1 leaves it out.
    """
    config = load_project(name)
    ctx.invoke(start_sensor_command, group="all", name=None)
    env = task_env(config)
    logger.info(f"Task env: {json.dumps(env)}")
    if env:
        os.environ["TEST_PR_ENV"] = json.dumps(env)
    os.environ["TEST_PR_IMAGE"] = config.image
    ctx.invoke(open_pr_command, kind="watched", merge=True, watch=True, timeout=config.run_timeout)


@experiment_group.command("run-local")
@name_argument
def run_local_command(name):
    """
    Run NAME's image in docker against its database through a port-forward, with no node
    involved. Results go to experiments/results/NAME. DEV_ENV is passed to the task; FULL=1
    leaves it out.
    """
    config = load_project(name)
    password = get_k8s_secret(config.secret_name, NAMESPACE, "password")
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
        connection = (
            f"server=localhost;database={config.database};port={config.local_port};"
            f"uid={config.username};pwd={password};"
        )
        run([
            "docker", "run", "--rm", "--network", "host",
            *[arg for key, value in env.items() for arg in ("-e", f"{key}={value}")],
            "-e", f"CONNECTION_STRING={connection}",
            "-e", f"CDM_SCHEMA={config.read_schema}",
            "-e", f"WRITE_SCHEMA={config.write_schema}",
            "-e", "ARTIFACT_PATH=/artifacts",
            "-v", f"{out_dir}:/artifacts",
            config.image,
        ])
    finally:
        port_forward.terminate()


@experiment_group.command("down")
def down_command():
    """Uninstall the experiments release. The secrets and database files stay."""
    run(["helm", "uninstall", RELEASE, "--namespace", NAMESPACE])


COMMANDS = [experiment_group]
