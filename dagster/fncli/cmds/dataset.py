"""
Commands for the dataset record in the backend. Its details come from the env (DATASET_*,
CLUSTER_DATASET_HOST), defaulting to a dummy stand-in that nothing connects to. It needs its
secret first, see init-dataset-secret.
"""

import logging

import click

from fncli.cmds.common import DatasetConfig, build_backend_api
from fncli.cmds.project import init_backend_project
from fncli.dagster.backend import BackendAPI
from fncli.dagster.models import Dataset, Project

logger = logging.getLogger("dataset")


def init_backend_dataset(
    config: DatasetConfig, backend_api: BackendAPI, project: Project
) -> Dataset:
    dataset = backend_api.get_or_create_dataset(
        config.dataset_name,
        host=config.dataset_host,
        port=config.dataset_port,
        db_type=config.dataset_type,
        secret_label=config.secret_label,
        read_schema=config.dataset_read_schema,
        write_schema=config.dataset_write_schema,
    )
    assignment = backend_api.get_or_assign_dataset(project.id, dataset)
    logger.info(
        f"Backend dataset {dataset.id}: {dataset.name} ({dataset.type} at "
        f"{dataset.host}:{dataset.port}, secret {dataset.secret.label}), "
        f"assigned to project {assignment.project_id} (active: {assignment.active})"
    )
    return dataset


@click.command("init-backend-dataset")
def init_backend_dataset_command():
    """Register the dataset with the backend (needs its secret, see init-dataset-secret)."""
    config = DatasetConfig()
    backend_api = build_backend_api(config)
    project = init_backend_project(config, backend_api)
    init_backend_dataset(config, backend_api, project)


@click.command("delete-backend-dataset")
def delete_backend_dataset_command():
    """Delete the dataset from the backend, and with it every project's assignment of it."""
    config = DatasetConfig()
    backend_api = build_backend_api(config)
    dataset = backend_api.find_dataset(config.dataset_name)
    if dataset is None:
        logger.info(f"Backend dataset {config.dataset_name} does not exist")
        return
    backend_api.delete_dataset(dataset.id)
    logger.info(f"Deleted backend dataset {dataset.name} ({dataset.id})")


COMMANDS = [init_backend_dataset_command, delete_backend_dataset_command]
