#!/usr/bin/env python3

import os
import sys
import json
import logging

logging.basicConfig(level=logging.INFO, stream=sys.stdout)
logger = logging.getLogger(__name__)

ARTIFACT_PATH = os.environ["ARTIFACT_PATH"]


def main():
    logger.info(f"Starting main with artifact path: {ARTIFACT_PATH}")
    mock_results(count=5)
    return 0


def mock_results(count):
    os.makedirs(ARTIFACT_PATH, exist_ok=True)
    logger.info(f"Generating {count} mock results")

    for n in range(1, count + 1):
        filepath = f"{ARTIFACT_PATH}/result_{n}.json"
        with open(filepath, 'w') as f:
            f.write(json.dumps({"result": {"value": n}}))

    logger.info(f"Completed generating {count} results")


if __name__ == "__main__":
    sys.exit(main())
