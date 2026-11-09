"""
`fncli experiment` runs real experiments against the dev node, see experiments/README.md. Each experiment is a folder
experiments/NAME/ that holds its database for the chart (values.yaml), its seed, its image and docker-bake.hcl, its
dataset as a node file (dataset.yaml, which `setup` applies after checking it against values.yaml and `teardown`
deletes), its trigger file (trigger.json, the image and anything else the task is asked for), and project.env with the
settings of `run` only (no secrets; it wins over .dev.env and the shell). Its node project and repositories are in the
node files bootstrap/examples/globals-NAME.yaml and projects/NAME.yaml, if it has them: `setup` applies them after the
dataset and `teardown` deletes them first. `up`, `seed`, `setup`, `run` and `teardown` can be repeated after a failure.
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
from fncli.cmds.demo import step_env
from fncli.cmds.nodefile import apply_node_file, context_option, delete_node_file, open_target, quiet_backend_logs
from fncli.cmds.sensor import start_sensor_command
from fncli.cmds.trigger import trigger_pr
from fncli.k8s import get_k8s_secret
from fncli.nodefile.loader import Context, load_node_file
from fncli.nodefile.schema import K8sSecretRef, NodeFile
from fncli.nodefile.state import read_state

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


def dataset_file(name: str) -> Path:
    """The node file of the experiment's dataset, in its own folder"""
    path = experiment_dir(name) / "dataset.yaml"
    if not path.is_file():
        raise click.ClickException(f"No dataset.yaml for {name}: {path}")
    return path


def trigger_file(name: str) -> Path:
    """The trigger file `run` asks the node for: the experiment's image, in its own folder"""
    path = experiment_dir(name) / "trigger.json"
    if not path.is_file():
        raise click.ClickException(f"No trigger.json for {name}: {path}")
    return path


def examples_dir() -> Path:
    return experiments_dir().parent / "bootstrap" / "examples"


def project_node_file(name: str) -> Path | None:
    """The experiment's node file with its project, next to the other examples, if it has one"""
    path = examples_dir() / "projects" / f"{name}.yaml"
    return path if path.is_file() else None


def node_files(name: str) -> list[Path]:
    """The experiment's node files after its dataset, in the order `setup` applies them: its global resources, then its project"""
    path = examples_dir() / f"globals-{name}.yaml"
    return [*([path] if path.is_file() else []), *([project] if (project := project_node_file(name)) else [])]


@dataclass(frozen=True)
class Database:
    """The experiment's database as the chart makes it (values.yaml), and the schemas its dataset reads and writes"""

    name: str  # the database, and the dataset's name in the node
    username: str
    secret_name: str  # the chart's Secret in NAMESPACE: `username` and `password`
    read_schema: str
    write_schema: str


def check_dataset(name: str, entry: dict, node: NodeFile):
    """dataset.yaml must name what the chart makes: the dataset by the database's name, the secret by the chart's"""
    problems = []
    dataset_names = [dataset.name for dataset in node.datasets]
    if dataset_names != [entry["name"]]:
        problems.append(f"its datasets are {dataset_names}, but dbs.{name}.name in values.yaml is {entry['name']}")
    secret = node.secrets.get(node.datasets[0].secret) if node.datasets else None
    read_from = {
        (ref.k8s_secret.namespace, ref.k8s_secret.name)
        for ref in (secret.values or {}).values() if isinstance(ref, K8sSecretRef)
    } if secret else set()
    if read_from != {(NAMESPACE, entry["secret"]["name"])}:
        problems.append(
            f"its dataset's secret reads {sorted(read_from)}, but dbs.{name}.secret.name in values.yaml is "
            f"{entry['secret']['name']} in namespace {NAMESPACE}"
        )
    if problems:
        listing = "\n".join(f"  - {problem}" for problem in problems)
        raise click.ClickException(f"experiments/{name}/dataset.yaml does not match values.yaml:\n{listing}")


def load_database(name: str) -> Database:
    """
    The database of experiment NAME from values.yaml (its `dbs.NAME` entry) and dataset.yaml (the schemas), after
    checking that dataset.yaml names the same database and secret as values.yaml.
    """
    values = experiment_dir(name) / "values.yaml"
    entry = yaml.safe_load(values.read_text())["dbs"][name]
    node = load_node_file(dataset_file(name))
    check_dataset(name, entry, node)
    dataset = node.datasets[0]
    return Database(entry["name"], entry["user"], entry["secret"]["name"], dataset.read_schema, dataset.write_schema)


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
    Register NAME in the node, against its database on the experiments release (`up`): check that its
    dataset.yaml names the database and secret of its values.yaml, then `fncli apply` it (the dataset and its
    secret), then the node files with its global resources and its project if it has them. Safe to rerun.
    """
    database = load_database(name)
    require_release()
    logger.info(f"=== Setting up dataset {database.name} ===")
    # Its login is generated by the chart: dataset.yaml reads it back from the chart's secret
    apply_node_file(context, dataset_file(name), None, yes=True)
    for path in node_files(name):
        logger.info(f"=== Setting up node resources from {path.name} ===")
        apply_node_file(context, path, None, yes=True)


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
    project_file = project_node_file(name)
    if project_file is None:
        raise click.ClickException(f"{name} has no node project: bootstrap/examples/projects/{name}.yaml")
    spec = load_node_file(project_file).projects[0]
    api = open_target(context)
    if api.find_project(spec.name) is None:
        raise click.ClickException(f"Project {spec.name} is not on the node: run `fncli experiment setup {name}` first")
    with quiet_backend_logs():
        state = read_state(api)
    # The pull request's names are the node project's, not whatever .dev.env has for the dev project
    os.environ.update(step_env(context, spec, state))
    ctx.invoke(start_sensor_command, group="all", name=None)
    env = task_env(config)
    logger.info(f"Task env: {json.dumps(env)}")
    trigger["spec"]["env"] = {**trigger["spec"].get("env", {}), **env}
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "trigger.json"
        path.write_text(json.dumps(trigger))
        trigger_pr(spec.name, path, merge=True, watch=True, timeout=config.run_timeout)


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
    """Every experiment: the folders under experiments/ with a dataset.yaml."""
    return sorted(path.parent.name for path in experiments_dir().glob("*/dataset.yaml"))


def teardown_experiment(context: Context, name: str):
    """
    Remove what `setup` registered for NAME, in reverse: the node project, then its global resources, then the dataset
    with its secret (`fncli delete --all` of each file). The dataset is refused, and the command exits 1, while a project
    outside these files (a demo project, say) is still assigned it. Gitea is left alone.
    """
    for path in reversed(node_files(name)):
        logger.info(f"=== Tearing down node resources from {path.name} ===")
        delete_node_file(context, path, with_globals=True, yes=True)
    logger.info(f"=== Tearing down dataset of {name} ===")
    delete_node_file(context, dataset_file(name), with_globals=True, yes=True)


@experiment_group.command("teardown")
@name_argument
@context_option
@click.confirmation_option("-y", "--yes", prompt="Delete the experiment's node project (if any), its dataset and their secrets from the node?")
def teardown_command(name, context):
    """
    Remove what `setup` registered in the node for NAME: its project, global resources and dataset. The Gitea repos
    and OAuth apps, the experiments release and NAME's database stay. Safe to rerun.
    """
    teardown_experiment(context, name)


@experiment_group.command("down")
@context_option
@click.confirmation_option(
    "-y", "--yes", prompt="Tear down every experiment's node project and uninstall the experiments release?"
)
def down_command(context):
    """
    Tear down every experiment's node project and dataset, then uninstall the experiments release. The
    secrets and database files stay, so a later `setup` gets the same data back. It stops, and leaves the release,
    if a dataset is still assigned to a project it does not tear down (delete the demo projects first).
    """
    for name in experiment_names():
        teardown_experiment(context, name)
    run(["helm", "uninstall", RELEASE, "--namespace", NAMESPACE])


COMMANDS = [experiment_group]
