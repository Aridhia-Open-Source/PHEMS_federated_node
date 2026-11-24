"""
Federated node dev tooling. `.dev.env` is found by searching up from the current directory, and
--env-file (or FNCLI_ENV_FILE) names a second env file that wins over it. Which node, and the defaults of the
commands, are in bootstrap/context.yaml (bootstrap/examples/context.yaml); the node's config is the fn.aridhia.com
resources in config/, which kubectl applies and the nexus operator syncs (ADR 0032), not the env:

    fncli --help
    fncli gitea setup -f config/gitea.yaml -f config/demo.yaml
    kubectl apply -f config/
"""

import logging
import sys

import click
from dotenv import find_dotenv, load_dotenv

from fncli.cmds import actions, demo, experiment, gitea, hello_world, pr, project, secret, sensor, simulate, state, trigger, verify


@click.group()
@click.option(
    "--env-file", envvar="FNCLI_ENV_FILE", default=None,
    help="An env file, found from the current directory up, that wins over .dev.env and the shell.",
)
def cli(env_file):
    sys.stdout.reconfigure(line_buffering=True)
    load_dotenv(find_dotenv(".dev.env", usecwd=True))
    if env_file:
        path = find_dotenv(env_file, usecwd=True)
        if not path:
            raise click.ClickException(f"{env_file} not found. From the repo root: cp {env_file}.example {env_file}")
        load_dotenv(path, override=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stdout,
    )


for module in (hello_world, actions, trigger, project, secret, pr, sensor, state, simulate, verify, demo, experiment, gitea):
    for command in module.COMMANDS:
        cli.add_command(command)
