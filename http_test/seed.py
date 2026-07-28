#!/usr/bin/env python
"""
Seed script for development/testing.
Creates test dataset, repository, and request for manual testing.
"""

import os
import sys
import logging

from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(__file__))
from clients import BackendSession, BackendAdapter, BackendAPI
from utils import load_dagster_system_creds as _load_creds

load_dotenv()
logging.basicConfig(level=logging.INFO, format='%(levelname)s:%(name)s:%(message)s')
logger = logging.getLogger(__name__)

BACKEND_API_URI = os.environ['BACKEND_API_URI']

# Repository
REPO_URI = os.environ['REPO_URI']
REPO_WATCH_DIR = os.environ['REPO_WATCH_DIR']
REPO_BRANCH = os.environ['REPO_BRANCH']
REPO_INIT_CURSOR = os.environ['REPO_INITIAL_CURSOR']

# Dataset
DATASET_NAME = os.environ['DATASET_NAME']
DATASET_HOST = os.environ['DATASET_HOST']
DATASET_PORT = int(os.environ['DATASET_PORT'])
DATASET_USERNAME = os.environ['DATASET_USERNAME']
DATASET_PASSWORD = os.environ['DATASET_PASSWORD']
DATASET_SCHEMA = os.environ['DATASET_SCHEMA']
DATASET_TYPE = os.environ['DATASET_TYPE']

# Data Access Request
REQUEST_USER_ID = os.environ['REQUEST_USER_ID']
REQUEST_PROJECT_NAME = os.environ['REQUEST_PROJECT_NAME']
REQUEST_TITLE = os.environ['REQUEST_TITLE']
REQUEST_DESCRIPTION = os.environ['REQUEST_DESCRIPTION']
REQUEST_START_DATE = os.environ['REQUEST_START_DATE']
REQUEST_END_DATE = os.environ['REQUEST_END_DATE']


def _init_backend_api(username: str, password: str):
    adapter = BackendAdapter(
        base_url=BACKEND_API_URI,
        username=username,
        password=password,
    )
    session = BackendSession(adapter=adapter)
    api = BackendAPI(session)
    api.login(username=username, password=password)
    return api


def seed():
    """Create test dataset, repository, and request."""
    creds = _load_creds()
    logger.info(f"Loaded credentials for user: {creds}")
    api = _init_backend_api(**creds)

    logger.info("Seeding Database!")

    logger.info("Deleting existing repositories...")
    existing_repos = api.get_repositories() or []

    for r in existing_repos:
        logger.info(f"Deleting existing repository ({r.id}) - {r.uri}")
        api.delete_repository(r.id)

    repo = api.create_repository(
        uri=REPO_URI,
        watch_dir=REPO_WATCH_DIR,
        base_branch=REPO_BRANCH,
        initial_cursor=REPO_INIT_CURSOR,
        default_dataset_name=DATASET_NAME,
    )

    logger.info("Deleting existing datasets...")
    existing_datasets = api.get_datasets() or []
    logger.info(f"Datasets found: {len(existing_datasets)}")

    for ds in existing_datasets:
        api.delete_dataset(ds.id)

    dataset = api.create_dataset(
        name=DATASET_NAME,
        host=DATASET_HOST,
        port=DATASET_PORT,
        username=DATASET_USERNAME,
        password=DATASET_PASSWORD,
        schema=DATASET_SCHEMA,
        db_type=DATASET_TYPE,
        repository_id=repo.id,
    )

    # logger.info(f"Created dataset: {dataset.id} - {dataset.name}")

    # breakpoint()
    # logger.info(f"Created request: {request.id} - {request.title}")
    # api.approve_request(request.id)

    # logger.info(f"Approved Request - {REQUEST_TITLE}")

    # logger.info(f"Seed complete: dataset={dataset.id}, repo={repo.id}, request={request.id}")


if __name__ == '__main__':
    seed()
