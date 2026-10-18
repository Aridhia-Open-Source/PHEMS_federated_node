from datetime import datetime, timezone

import dagster as dg

from app.definitions.sensors.git.base import GitSensor
from app.definitions.sensors.git.ingest_job import ingest_pull_requests, ingest_pull_requests_job
from app.definitions.sensors.git.pr_evaluate import IN_FLIGHT
from app.models import TriggerRepository


class PullRequestIngestSensor(GitSensor):
    """
    Polls the git provider once per global trigger repository that is enabled, on an enabled
    provider, with an enabled secret, whatever its project links. It uses the repository's own
    secret and the cursor the backend gives it, and launches ingest_pull_requests_job for each one
    with new merged PRs. The job posts them once for every project. The poll has no base branch
    filter: each PR carries its base branch and the backend matches it per link. A project's lock
    does not stop the poll, it pauses evaluation and launch.
    """

    def __call__(self):
        """
        Execute the sensor. Yields a RunRequest per repository with new PRs, or a SkipReason.

        The run key includes the minute: a failed run is retried by a later tick, but a tick
        evaluated twice in the same minute does not double the run. A repository with a run still
        queued or started is skipped.

        A failed check is logged and the other repositories still launch. Dagster drops what a
        failing tick yielded, so the tick only fails, naming the repositories, when nothing
        launched: one broken repository must not starve the rest.
        """
        repos = self.backend_api.get_pollable_trigger_repositories()
        if not repos:
            yield dg.SkipReason("No pollable trigger repositories found.")
            return

        launched = 0
        failed = []
        for repo in repos:
            try:
                if self._ingest_in_flight(repo):
                    self.log.info(f"Ingest of repo {repo.id} is already in flight")
                    continue
                merged = self._new_merged_pulls(repo)
            except Exception:  # pylint: disable=broad-exception-caught  # one repository must not stop the others
                self.log.exception(f"Checking pull requests of {repo.uri} failed")
                failed.append(repo.uri)
                continue
            if merged:
                yield self._ingest_run_request(repo)
                launched += 1
        if failed:
            message = f"Ingest failed for {', '.join(failed)}"
            if not launched:
                raise RuntimeError(message)
            self.log.error(f"{message}; launched {launched} ingest runs for the others")
        if not launched and not failed:
            yield dg.SkipReason("No new pull requests found for repositories.")

    def _new_merged_pulls(self, repo: TriggerRepository) -> list[dict]:
        """The provider's merged PRs since the repository's cursor. Reads the repository's secret."""
        git_api = self.git_apis.for_repository(repo)
        merged = git_api.get_new_merged_pulls(repo_path=repo.repo_path, merged_after=repo.pr_cursor)
        self.log.info(f"Git provider returned {len(merged)} new PRs for {repo.repo_path} since {repo.pr_cursor}")
        return merged

    def _ingest_run_request(self, repo: TriggerRepository) -> dg.RunRequest:
        """
        The run that ingests the repository's merged PRs since its cursor. The run key names the
        cursor and the minute, so a tick repeated in the same minute does not double it.
        """
        minute = datetime.now(timezone.utc).strftime("%Y%m%d%H%M")
        return dg.RunRequest(
            run_key=f"ingest/{repo.id}/{repo.pr_cursor}/{minute}",
            tags={"trigger": "ingest", "repo_id": str(repo.id)},
            run_config={"ops": {ingest_pull_requests.name: {"config": {"repo_id": repo.id}}}},
        )

    def _ingest_in_flight(self, repo: TriggerRepository) -> bool:
        runs = self.context.instance.get_runs(
            filters=dg.RunsFilter(
                job_name=ingest_pull_requests_job.name,
                tags={"trigger": "ingest", "repo_id": str(repo.id)},
                statuses=IN_FLIGHT,
            ),
            limit=1,
        )
        return bool(runs)
