from datetime import datetime, timezone

import dagster as dg

from app.definitions.sensors.git.base import GitSensor
from app.definitions.sensors.git.evaluate_job import (
    evaluate_repository_pull_requests_job,
    load_unknown_pull_requests,
)
from app.models import ProjectTriggerRepository, TriggerState

IN_FLIGHT = [dg.DagsterRunStatus.NOT_STARTED, dg.DagsterRunStatus.QUEUED, dg.DagsterRunStatus.STARTING,
             dg.DagsterRunStatus.STARTED]


class PullRequestEvaluateSensor(GitSensor):
    """Launches one evaluation run per trigger repository of an enabled, unlocked project that has UNKNOWN PRs, reading each project's links."""

    def __call__(self):
        """
        Execute the sensor. Yields a RunRequest per repository to evaluate, or a SkipReason.

        The run key includes the minute: a failed batch is retried by a later tick, but a
        tick evaluated twice in the same minute does not double the run. A repository with
        a run still queued or started is skipped.
        """
        projects = [p for p in self.backend_api.get_projects() if p.enabled and not p.locked]
        launched = 0
        for project in projects:
            for repo in self.backend_api.get_project_trigger_repositories(project.id):
                if not repo.active:
                    continue
                if self._run_in_flight(repo):
                    self.log.info(f"Evaluation of repo {repo.trigger_repository.id} of project {repo.project_id} is already in flight")
                    continue
                if not self.backend_api.get_pull_requests(repo.project_id, repo.trigger_repository.id, TriggerState.UNKNOWN.value):
                    continue
                yield self._run_request(repo)
                launched += 1

        if not launched:
            yield dg.SkipReason("No repositories with unknown pull requests to evaluate.")

    def _run_in_flight(self, repo: ProjectTriggerRepository) -> bool:
        runs = self.context.instance.get_runs(
            filters=dg.RunsFilter(
                job_name=evaluate_repository_pull_requests_job.name,
                tags={"project_id": str(repo.project_id), "repo_id": str(repo.trigger_repository.id)},
                statuses=IN_FLIGHT,
            ),
            limit=1,
        )
        return bool(runs)

    def _run_request(self, repo: ProjectTriggerRepository) -> dg.RunRequest:
        minute = datetime.now(timezone.utc).strftime("%Y%m%d%H%M")
        return dg.RunRequest(
            run_key=f"evaluate/{repo.project_id}/{repo.trigger_repository.id}/{minute}",
            tags={"repo_id": str(repo.trigger_repository.id), "project_id": str(repo.project_id)},
            run_config={"ops": {load_unknown_pull_requests.name: {"config": {"project_id": repo.project_id, "repo_id": repo.trigger_repository.id}}}},
        )
