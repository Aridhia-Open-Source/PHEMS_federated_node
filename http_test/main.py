#!/usr/bin/env python

"""Backend API client example."""

import logging

from clients import BackendSession, BackendAdapter, BackendAPI
from utils import load_dagster_system_creds

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def main():
    backend_url = "http://localhost:5000"

    creds = load_dagster_system_creds()
    logger.info(f"Credentials: {creds}")

    adapter = BackendAdapter(
        base_url=backend_url,
        username=creds['username'],
        password=creds['password'],
    )
    session = BackendSession(adapter)
    api = BackendAPI(session)
    repos = api.get_repositories() or []

    for repo in repos:
        logger.info(repo.path)


if __name__ == "__main__":
    main()
