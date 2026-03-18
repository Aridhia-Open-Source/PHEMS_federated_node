#!/usr/bin/env python3

import sys
import subprocess
import logging

from dagster_pipes import open_dagster_pipes

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def entrypoint():
    with open_dagster_pipes() as _:
        logger.info("[CHILD][PYTHON][INFO] - Entrypoint!")
        result = subprocess.run(["python3", "main.py"], check=True)
        return result.returncode


if __name__ == "__main__":
    print("Running entrypoint.py")
    sys.exit(entrypoint())
