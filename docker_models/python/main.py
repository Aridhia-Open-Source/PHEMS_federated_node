#!/usr/bin/env python3

import os
import sys
import json
import logging

MNT_BASE_PATH = "/mnt/dagster/artifacts"


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def main():
    argv = sys.argv[1:]
    logger.info(f"[SUBPROC][PYTHON][INFO] - argv: {argv}")
    mock_results(count=5)
    return 0


def mock_results(count):
    task_id = os.environ['TASK_ID']
    output_dir = f"{MNT_BASE_PATH}/{task_id}"
    os.makedirs(output_dir, exist_ok=True)

    for n in range(1, count + 1):
        filepath = f"{output_dir}/result_{n}.json"
        logger.info(f"[SUBPROC][PYTHON][INFO] - Creating file ({n}): {filepath}")
        with open(filepath, 'w') as f:
            f.write(json.dumps({"result": {"value": n}}))


if __name__ == "__main__":
    logger.info("[SUBPROC][PYTHON][INFO] - START main.py")
    return_code = main()
    logger.error(f"[SUBPROC][PYTHON][ERROR] - EXIT main.py ({return_code})")
    sys.exit(return_code)
