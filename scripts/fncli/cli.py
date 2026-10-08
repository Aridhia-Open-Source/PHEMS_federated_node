"""
Federated node dev tooling. `.dev.env` is found by searching up from the current directory:

    fncli --help
"""

import logging

import click
from dotenv import find_dotenv, load_dotenv

from fncli.cmds import actions, dataset, hello_world, pr, project, repository, secret, sensor, verify


@click.group()
def cli():
    load_dotenv(find_dotenv(".dev.env", usecwd=True))
    logging.basicConfig(level=logging.INFO, format="%(message)s")


for module in (hello_world, actions, project, repository, secret, dataset, pr, sensor, verify):
    for command in module.COMMANDS:
        cli.add_command(command)
