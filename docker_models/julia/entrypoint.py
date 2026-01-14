#!/usr/bin/env python3

import sys
import subprocess
import logging
import time


from dagster_pipes import open_dagster_pipes


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def entrypoint():
    with open_dagster_pipes() as _:
        return subprocess.run([
            "julia",
            "--project=/project",
            "/project/src/main.jl",
        ], check=True).returncode


if __name__ == "__main__":
    logger.info("RUNNING entrypoint.py")
    sys.exit(entrypoint())
