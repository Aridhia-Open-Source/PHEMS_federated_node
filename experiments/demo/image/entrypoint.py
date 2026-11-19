#!/usr/bin/env python3

import sys
import subprocess

from dagster_pipes import open_dagster_pipes


def entrypoint():
    with open_dagster_pipes() as pipes:
        # TODO: use threading to read and redirect stdout and stderr concurrently
        proc = subprocess.Popen(
            [
                "python3",
                "main.py",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )

        returncode = handle(pipes, proc)

        if returncode != 0:
            raise subprocess.CalledProcessError(
                returncode, proc.args
            )

        return returncode


def handle(pipes, proc):
    for line in proc.stdout or []:
        pipes.log.info(line.rstrip())

    for line in proc.stderr or []:
        pipes.log.error(line.rstrip())

    return proc.wait()


if __name__ == "__main__":
    sys.exit(entrypoint())
