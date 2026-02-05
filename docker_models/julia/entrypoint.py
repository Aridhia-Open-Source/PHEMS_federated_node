#!/usr/bin/env python3

import sys
import subprocess
import logging

from dagster_pipes import open_dagster_pipes

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def entrypoint():
    with open_dagster_pipes() as pipes:
        pipes.log.info("Starting Julia subproc...")

        proc = subprocess.Popen(
            [
                "julia",
                "--project=/project",
                "/project/src/main.jl",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,  # line-buffered
        )

        for line in proc.stdout or []:
            pipes.log.info(line.rstrip())

        for line in proc.stderr or []:
            pipes.log.error(line.rstrip())

        returncode = proc.wait()
        if returncode != 0:
            raise subprocess.CalledProcessError(
                returncode, proc.args
            )

        pipes.log.info(f"Exiting Julia subproc - ({returncode})")
        return returncode


if __name__ == "__main__":
    logger.info("RUNNING entrypoint.py")
    sys.exit(entrypoint())
