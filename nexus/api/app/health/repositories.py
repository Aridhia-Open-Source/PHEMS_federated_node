"""
Trigger and results repository health: can the repository be reached with its own secret.
"""
from collections.abc import Callable

from app.dtos.healthcheck import (
    ProjectResultsRepositoryHealthDTO, ProjectTriggerRepositoryHealthDTO, RepositoryConnectionDTO
)
from app.health.run import health_check_dto
from app.models.git_repository import GitRepositoryMixin
from app.models.project_results_repository import ProjectResultsRepository
from app.models.project_trigger_repository import ProjectTriggerRepository
from app.models.pull_request_trigger import PullRequestTrigger


def prepare_repository_health(repository: GitRepositoryMixin) -> Callable[[], RepositoryConnectionDTO]:
    """A global trigger or results repository: can it be reached with its own secret."""
    id, uri, provider, enabled = repository.id, repository.uri, repository.provider.type, repository.enabled
    prepared = repository.prepare_connection_check()

    def run():
        check = prepared()
        return RepositoryConnectionDTO(
            id=id, uri=uri, provider=provider, enabled=enabled,
            status=check.status.value, health_check=health_check_dto(check),
        )
    return run

def prepare_trigger_resource_health(resource: ProjectTriggerRepository) -> Callable[[], ProjectTriggerRepositoryHealthDTO]:
    repository = prepare_repository_health(resource.trigger_repository)
    project_id, enabled, revoked, active = resource.project_id, resource.enabled, resource.revoked, resource.active
    pr_count = PullRequestTrigger.query.filter_by(project_trigger_repository_id=resource.id).count()
    return lambda: ProjectTriggerRepositoryHealthDTO(
        project_id=project_id, pr_count=pr_count, enabled=enabled, revoked=revoked, active=active,
        trigger_repository=repository(),
    )

def prepare_results_resource_health(resource: ProjectResultsRepository) -> Callable[[], ProjectResultsRepositoryHealthDTO]:
    repository = prepare_repository_health(resource.results_repository)
    project_id, enabled, revoked, active = resource.project_id, resource.enabled, resource.revoked, resource.active
    owned_by_federated_node, target_dir, base_branch = (
        resource.owned_by_federated_node, resource.target_dir, resource.base_branch
    )
    return lambda: ProjectResultsRepositoryHealthDTO(
        project_id=project_id, owned_by_federated_node=owned_by_federated_node, target_dir=target_dir,
        base_branch=base_branch, enabled=enabled, revoked=revoked, active=active, results_repository=repository(),
    )
