from datetime import datetime, timezone

import dagster as dg

from app.definitions.sensors.git.base import GitSensor
from app.definitions.sensors.git.evaluate_job import (
    evaluate_repository_pull_requests_job,
    load_unknown_pull_requests,
)
from app.models import TriggerRepository, TriggerState

IN_FLIGHT = [dg.DagsterRunStatus.NOT_STARTED, dg.DagsterRunStatus.QUEUED, dg.DagsterRunStatus.STARTING,
             dg.DagsterRunStatus.STARTED]


class PullRequestEvaluateSensor(GitSensor):
    """Launches one evaluation run per trigger repository of an enabled project that has UNKNOWN PRs."""

    def __call__(self):
        """
        Execute the sensor. Yields a RunRequest per repository to evaluate, or a SkipReason.

        The run key includes the minute: a failed batch is retried by a later tick, but a
        tick evaluated twice in the same minute does not double the run. A repository with
        a run still queued or started is skipped.
        """
        enabled = {p.id for p in self.backend_api.get_projects() if p.enabled}
        launched = 0
        for repo in self.backend_api.get_repositories():
            if repo.project_id not in enabled:
                continue
            if self._run_in_flight(repo):
                self.log.info(f"Evaluation of repo {repo.id} is already in flight")
                continue
            if not self.backend_api.get_pull_requests(repo.id, TriggerState.UNKNOWN.value):
                continue
            yield self._run_request(repo)
            launched += 1

        if not launched:
            yield dg.SkipReason("No repositories with unknown pull requests to evaluate.")

    def _run_in_flight(self, repo: TriggerRepository) -> bool:
        runs = self.context.instance.get_runs(
            filters=dg.RunsFilter(
                job_name=evaluate_repository_pull_requests_job.name,
                tags={"repo_id": str(repo.id)},
                statuses=IN_FLIGHT,
            ),
            limit=1,
        )
        return bool(runs)

    def _run_request(self, repo: TriggerRepository) -> dg.RunRequest:
        minute = datetime.now(timezone.utc).strftime("%Y%m%d%H%M")
        return dg.RunRequest(
            run_key=f"evaluate/{repo.id}/{minute}",
            tags={"repo_id": str(repo.id), "project_id": str(repo.project_id)},
            run_config={"ops": {load_unknown_pull_requests.name: {"config": {"repo_id": repo.id}}}},
        )
