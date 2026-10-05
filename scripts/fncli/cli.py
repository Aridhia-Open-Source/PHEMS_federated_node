"""
Federated node dev tooling. `.dev.env` is found by searching up from the current directory:

    python -m scripts.fncli --help
"""

import logging

import click
from dotenv import find_dotenv, load_dotenv

from fncli.cmds import hello_world, init_repo


@click.group()
def cli():
    load_dotenv(find_dotenv(".dev.env", usecwd=True))
    logging.basicConfig(level=logging.INFO, format="%(message)s")


for module in (hello_world, init_repo):
    for command in module.COMMANDS:
        cli.add_command(command)
