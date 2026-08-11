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
from clients import BackendSession, BackendAdapter, BackendAPI  # noqa
from utils import load_dagster_system_creds as _load_creds  # noqa


# Which use case is being seeded: SEED_ENV_FILE picks the dotenv file, so uc1 and
# uc3 can each keep their own (dev.db/.env, dev.db/uc3.env). Values already exported
# by the calling script win either way - load_dotenv does not override them.
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         os.environ.get('SEED_ENV_FILE', '.env')))
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
CLUSTER_DATASET_HOST = os.environ['CLUSTER_DATASET_HOST']
DATASET_PORT = int(os.environ['DATASET_PORT'])
DATASET_USERNAME = os.environ['DATASET_USERNAME']
DATASET_PASSWORD = os.environ['DATASET_PASSWORD']
DATASET_SCHEMA = os.environ['DATASET_SCHEMA']
DATASET_SCHEMA_WRITE = os.environ['DATASET_SCHEMA_WRITE']
DATASET_TYPE = os.environ['DATASET_TYPE']

# Data Access Request
REQUEST_USER_ID = os.environ['REQUEST_USER_ID']
REQUEST_PROJECT_NAME = os.environ['REQUEST_PROJECT_NAME']
REQUEST_TITLE = os.environ['REQUEST_TITLE']
REQUEST_DESCRIPTION = os.environ['REQUEST_DESCRIPTION']
REQUEST_START_DATE = os.environ['REQUEST_START_DATE']
REQUEST_END_DATE = os.environ['REQUEST_END_DATE']


def _same_repo(a: str, b: str) -> bool:
    """Compare repo URIs the way the backend stores them (scheme/.git stripped)."""
    def norm(uri):
        return (uri or '').removeprefix('https://').removeprefix('http://') \
                          .removesuffix('.git').rstrip('/').lower()
    return norm(a) == norm(b)


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
    logger.info("===================================================================")
    logger.info("Seeding Database!")
    logger.info("===================================================================")

    creds = _load_creds()
    logger.info(f"Loaded credentials for user: {creds}")
    api = _init_backend_api(**creds)
    logger.info(f"Initialized backend API client for {creds['username']}")

    # Datasets are kept per use case, so seeding uc3 leaves uc1's dataset registered
    # (and vice versa). Repositories cannot be: Repository.uri is unique in the
    # backend, and the dagster sensor resolves a task's dataset from the repository
    # the spec arrived through - so the repo row is replaced here, and whichever use
    # case was seeded last owns spec delivery.
    logger.info("Fetching existing repositories...")
    existing_repos = api.get_repositories() or []
    logger.info(f"Repositories found: {len(existing_repos)}")
    for r in existing_repos:
        if _same_repo(r.uri, REPO_URI):
            logger.info(f"Deleting existing repository ({r.id}) - {r.uri} [{r.watch_dir}]")
            api.delete_repository(r.id)
        else:
            logger.info(f"Keeping repository ({r.id}) - {r.uri} [{r.watch_dir}]")

    logger.info("Fetching existing datasets...")
    existing_datasets = api.get_datasets() or []
    logger.info(f"Datasets found: {len(existing_datasets)}")

    for ds in existing_datasets:
        if ds.name != DATASET_NAME:
            logger.info(f"Keeping dataset ({ds.id}) - {ds.name}")
            continue
        logger.info(f"Deleting existing dataset ({ds.id}) - {ds.name}")
        api.delete_dataset(ds.id)

    logger.info("Creating new dataset...")
    dataset = api.create_dataset(
        name=DATASET_NAME,
        host=CLUSTER_DATASET_HOST,
        port=DATASET_PORT,
        username=DATASET_USERNAME,
        password=DATASET_PASSWORD,
        schema=DATASET_SCHEMA,
        db_type=DATASET_TYPE,
        schema_write=DATASET_SCHEMA_WRITE,
    )

    logger.info("Creating new repository...")
    repo = api.create_repository(
        uri=REPO_URI,
        watch_dir=REPO_WATCH_DIR,
        base_branch=REPO_BRANCH,
        initial_cursor=REPO_INIT_CURSOR,
        dataset_id=dataset.id,
    )

    logger.info("========================================================================")
    logger.info(f"Seed complete - (dataset_id={dataset.id}, repository_id={repo.id})")
    logger.info("========================================================================")


if __name__ == '__main__':
    seed()
