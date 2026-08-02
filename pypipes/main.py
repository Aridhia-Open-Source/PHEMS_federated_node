#!/usr/bin/env python3

import os
import sys
import json
import logging

ARTIFACT_PATH = os.environ["ARTIFACT_PATH"]
SECRETS_PATH = "/var/secrets/db"

os.makedirs(ARTIFACT_PATH, exist_ok=True)

logger = logging.getLogger()
logger.setLevel(logging.INFO)

stdout_handler = logging.StreamHandler(sys.stdout)
stdout_handler.setFormatter(logging.Formatter('%(levelname)s:%(name)s:%(message)s'))
logger.addHandler(stdout_handler)

file_handler = logging.FileHandler(f"{ARTIFACT_PATH}/pypipes.log")
file_handler.setFormatter(logging.Formatter('%(levelname)s:%(name)s:%(message)s'))
logger.addHandler(file_handler)


def read_secret(secret_name: str) -> str:
    """Read a secret from the mounted k8s secret volume."""
    path = f"{SECRETS_PATH}/{secret_name}"
    try:
        with open(path, 'r') as f:
            return f.read().strip()
    except FileNotFoundError:
        logger.warning(f"Secret not found at {path}")
        return ""


def main():
    logger.info(f"Starting main with artifact path: {ARTIFACT_PATH}")

    if os.path.exists(SECRETS_PATH):
        logger.info("=== Mounted Secrets ===")
        try:
            for filename in os.listdir(SECRETS_PATH):
                filepath = os.path.join(SECRETS_PATH, filename)
                if os.path.isfile(filepath):
                    content = read_secret(filename)
                    logger.info(f"{filename}: {content}")
        except Exception as e:
            logger.error(f"Error reading secrets: {e}")
        logger.info("=== End Secrets ===")
    else:
        logger.warning(f"Secrets path {SECRETS_PATH} not found - dataset credentials not mounted")

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
