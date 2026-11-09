"""
Federated node dev tooling. `.dev.env` is found by searching up from the current directory, and
--env-file (or FNCLI_ENV_FILE) names a second env file that wins over it. The node itself is set up from a
node file (bootstrap/examples), not from the env:

    fncli --help
    fncli diff -f examples/demo-github.yaml
    fncli apply -f examples/demo-github.yaml
"""

import logging
import sys

import click
from dotenv import find_dotenv, load_dotenv

from fncli.cmds import actions, demo, experiment, hello_world, nodefile, pr, project, secret, sensor, simulate, state, verify


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


for module in (hello_world, actions, project, secret, pr, sensor, state, simulate, verify, demo, experiment, nodefile):
    for command in module.COMMANDS:
        cli.add_command(command)
