#!/usr/bin/env python3

import os
import sys
import json
import logging


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
ARTIFACT_PATH = os.environ["ARTIFACT_PATH"]


def main():
    argv = sys.argv[1:]
    logger.info(f"[SUBPROC][PYTHON][INFO] - argv: {argv}")
    mock_results(count=5)
    return 0


def mock_results(count):
    os.makedirs(ARTIFACT_PATH, exist_ok=True)

    for n in range(1, count + 1):
        filepath = f"{ARTIFACT_PATH}/result_{n}.json"
        logger.info(f"[SUBPROC][PYTHON][INFO] - Creating file ({n}): {filepath}")
        with open(filepath, 'w') as f:
            f.write(json.dumps({"result": {"value": n}}))


if __name__ == "__main__":
    logger.info("[SUBPROC][PYTHON][INFO] - START main.py")
    return_code = main()
    logger.error(f"[SUBPROC][PYTHON][ERROR] - EXIT main.py ({return_code})")
    sys.exit(return_code)
