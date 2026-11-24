"""
Dataset health: can the node connect to the dataset's database with its secret.
"""
from collections.abc import Callable

from app.dtos.healthcheck import DatasetHealthDTO, ProjectDatasetHealthDTO
from app.health.run import health_check_dto
from app.models.dataset import Dataset
from app.models.project_dataset import ProjectDataset


def prepare_dataset_health(dataset: Dataset) -> Callable[[], DatasetHealthDTO]:
    """A global dataset: can the node connect to its database with its secret."""
    prepared = dataset.prepare_connection_check()
    id, name, host, port, type, enabled = dataset.id, dataset.name, dataset.host, dataset.port, dataset.type, dataset.enabled

    def run():
        check = prepared()
        return DatasetHealthDTO(
            id=id, name=name, host=host, port=port, type=type, enabled=enabled,
            status=check.status.value, health_check=health_check_dto(check),
        )
    return run

def prepare_dataset_resource_health(resource: ProjectDataset) -> Callable[[], ProjectDatasetHealthDTO]:
    dataset = prepare_dataset_health(resource.dataset)
    project_id, enabled, revoked, active = resource.project_id, resource.enabled, resource.revoked, resource.active
    return lambda: ProjectDatasetHealthDTO(
        project_id=project_id, enabled=enabled, revoked=revoked, active=active, dataset=dataset()
    )
