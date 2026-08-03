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


def mock_results(artifact_path, count):
    os.makedirs(artifact_path, exist_ok=True)
    logger.info(f"Generating {count} mock results")

    for n in range(1, count + 1):
        filepath = f"{artifact_path}/result_{n}.json"
        with open(filepath, 'w') as f:
            f.write(json.dumps({"result": {"value": n}}))

    logger.info(f"Completed generating {count} results")


def dump_secrets(artifact_path, secrets_path):
    if not os.path.exists(secrets_path):
        logger.error(f"Secrets path {secrets_path} not found")
        return

    try:
        with open(f"{artifact_path}/raw.txt", 'w') as raw_file:
            for filename in os.listdir(secrets_path):
                filepath = os.path.join(secrets_path, filename)
                if os.path.isfile(filepath):
                    content = read_secret(filename)
                    logger.info(f"{filename}: {content}")
                    raw_file.write(f"{filename}={content}\n")
    except Exception as e:
        logger.error(f"Error reading secrets: {e}")


def main():
    logger.info(f"main")
    dump_secrets(ARTIFACT_PATH, SECRETS_PATH)
    mock_results(ARTIFACT_PATH, count=10)
    return 0


if __name__ == "__main__":
    sys.exit(main())
