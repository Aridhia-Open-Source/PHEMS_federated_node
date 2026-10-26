import dagster as dg

from app.definitions.sensors.base import LaunchingSensor, run_key
from app.definitions.sensors.git.base import GitSensor
from app.definitions.sensors.git.evaluate_job import (
    evaluate_repository_pull_requests_job,
    load_unknown_pull_requests,
)
from app.models import ProjectTriggerRepository, TriggerState


class PullRequestEvaluateSensor(LaunchingSensor, GitSensor):
    """
    Launches one evaluation run per trigger repository of an enabled project that has
    UNKNOWN PRs, reading each project's resources.

    The run key names the project resource and its newest UNKNOWN PR number, see run_key: a newly ingested
    PR launches at once, and a failed batch is retried once per retry interval. A repository
    with a run still queued or started is skipped.
    """

    job = evaluate_repository_pull_requests_job
    failure_label = "Evaluation"
    skip_message = "No repositories with unknown pull requests to evaluate."

    def __init__(self, *args, **kwds):
        super().__init__(*args, **kwds)
        self.newest_unknown: dict[tuple[int, int], int] = {}

    def items(self):
        for project in self.backend_api.get_projects(enabled=True):
            yield from self.backend_api.get_project_trigger_repositories(project.id, active=True)

    def describe(self, item: ProjectTriggerRepository) -> str:
        return f"Evaluation of repo {item.trigger_repository.id} of project {item.project_id}"

    def tags(self, item: ProjectTriggerRepository) -> dict[str, str]:
        return {"repo_id": str(item.trigger_repository.id), "project_id": str(item.project_id)}

    def ready(self, item: ProjectTriggerRepository) -> bool:
        """Whether the project resource has UNKNOWN PRs, noting the newest one's number for the run key."""
        unknown = self.backend_api.get_pull_requests(
            item.project_id, item.trigger_repository.id, state=TriggerState.UNKNOWN.value
        )
        if unknown:
            self.newest_unknown[(item.project_id, item.trigger_repository.id)] = max(pr.number for pr in unknown)
        return bool(unknown)

    def run_request(self, item: ProjectTriggerRepository) -> dg.RunRequest:
        newest = self.newest_unknown[(item.project_id, item.trigger_repository.id)]
        return dg.RunRequest(
            run_key=run_key("evaluate", f"{item.project_id}/{item.trigger_repository.id}", newest),
            tags=self.tags(item),
            run_config={"ops": {load_unknown_pull_requests.name: {"config": {"project_id": item.project_id, "repo_id": item.trigger_repository.id}}}},
        )
