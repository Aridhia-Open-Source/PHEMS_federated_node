"""
Federated node dev tooling. `.dev.env` is found by searching up from the current directory, and
--env-file (or FNCLI_ENV_FILE) names a second env file that wins over it, e.g. to run on GitHub:

    fncli --help
    fncli --env-file .demo-github.env verify-git-secret
"""

import logging
import sys

import click
from dotenv import find_dotenv, load_dotenv

from fncli.cmds import actions, dataset, demo, experiment, hello_world, pr, project, repository, secret, sensor, simulate, state, verify


@click.group()
@click.option(
    "--env-file", envvar="FNCLI_ENV_FILE", default=None,
    help="An env file, found from the current directory up, that wins over .dev.env and the shell, e.g. .demo-github.env to run on GitHub.",
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


for module in (hello_world, actions, project, repository, secret, dataset, pr, sensor, state, simulate, verify, demo, experiment):
    for command in module.COMMANDS:
        cli.add_command(command)
