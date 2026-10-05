"""
Federated node dev tooling. `.dev.env` is found by searching up from the current directory:

    fncli --help
"""

import logging

import click
from dotenv import find_dotenv, load_dotenv

from fncli.cmds import dataset, hello_world, pr, project, repository, secret


@click.group()
def cli():
    load_dotenv(find_dotenv(".dev.env", usecwd=True))
    logging.basicConfig(level=logging.INFO, format="%(message)s")


for module in (hello_world, project, repository, secret, dataset, pr):
    for command in module.COMMANDS:
        cli.add_command(command)
