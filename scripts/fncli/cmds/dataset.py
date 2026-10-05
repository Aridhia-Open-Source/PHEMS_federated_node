"""
Commands for the dataset record in the backend. The dataset is a stand-in: nothing connects
to it, so its details are dummies. It needs its secret first, see init-dataset-secret.
"""

import logging

import click

from fncli.cmds.common import DatasetConfig, build_backend_api
from fncli.cmds.project import find_project, init_backend_project
from fncli.dagster.backend import BackendAPI
from fncli.dagster.models import Dataset, Project

logger = logging.getLogger("dataset")

DATASET_HOST = "db-datasets.fn.svc"
DATASET_PORT = 5432
DATASET_TYPE = "postgres"
DATASET_READ_SCHEMA = "cdm"
DATASET_WRITE_SCHEMA = "results"


def init_backend_dataset(
    config: DatasetConfig, backend_api: BackendAPI, project: Project
) -> Dataset:
    dataset = backend_api.get_or_create_dataset(
        config.dataset_name,
        project.id,
        host=DATASET_HOST,
        port=DATASET_PORT,
        db_type=DATASET_TYPE,
        secret_label=config.secret_label,
        read_schema=DATASET_READ_SCHEMA,
        write_schema=DATASET_WRITE_SCHEMA,
    )
    logger.info(
        f"Backend dataset {dataset.id}: {dataset.name} ({dataset.type} at "
        f"{dataset.host}:{dataset.port}, secret {dataset.secret.label}, "
        f"project {dataset.project_id})"
    )
    return dataset


@click.command("init-backend-dataset")
def init_backend_dataset_command():
    """Register the dummy dataset with the backend (needs its secret, see init-dataset-secret)."""
    config = DatasetConfig()
    backend_api = build_backend_api(config)
    project = init_backend_project(config, backend_api)
    init_backend_dataset(config, backend_api, project)


@click.command("delete-backend-dataset")
def delete_backend_dataset_command():
    """Delete the dataset from the backend."""
    config = DatasetConfig()
    backend_api = build_backend_api(config)
    project = find_project(config, backend_api)
    if project is None:
        return
    dataset = backend_api.find_dataset(config.dataset_name, project.id)
    if dataset is None:
        logger.info(f"Backend dataset {config.dataset_name} does not exist")
        return
    backend_api.delete_dataset(dataset.id)
    logger.info(f"Deleted backend dataset {dataset.name} ({dataset.id})")


COMMANDS = [init_backend_dataset_command, delete_backend_dataset_command]
