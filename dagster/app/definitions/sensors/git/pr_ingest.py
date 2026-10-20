import dagster as dg

from app.definitions.sensors.base import LaunchingSensor, run_key
from app.definitions.sensors.git.base import GitSensor
from app.definitions.sensors.git.ingest_job import ingest_pull_requests, ingest_pull_requests_job
from app.models import TriggerRepository


class PullRequestIngestSensor(LaunchingSensor, GitSensor):
    """
    Polls the git provider once per global trigger repository that is enabled, on an enabled
    provider, with an enabled secret, whatever its project links. It uses the repository's own
    secret and the cursor the backend gives it, and launches ingest_pull_requests_job for each one
    with new merged PRs. The job posts them once for every project. The poll has no base branch
    filter: each PR carries its base branch and the backend matches it per link. A disabled
    project does not stop the poll, it gets no evaluation or launch.

    The run key names the repository and its cursor, see run_key: new merged PRs move the
    cursor, so they launch at once, and a failed run is retried once per retry interval. A
    repository with a run still queued or started is skipped. A failed check is logged and the
    other repositories still launch, see LaunchingSensor.
    """

    job = ingest_pull_requests_job
    failure_label = "Ingest"
    skip_message = "No new pull requests found for repositories."

    def items(self) -> list[TriggerRepository]:
        return self.backend_api.get_pollable_trigger_repositories()

    def describe(self, item: TriggerRepository) -> str:
        return item.uri

    def tags(self, item: TriggerRepository) -> dict[str, str]:
        return {"trigger": "ingest", "repo_id": str(item.id)}

    def ready(self, item: TriggerRepository) -> bool:
        """The provider's merged PRs since the repository's cursor. Reads the repository's secret."""
        git_api = self.git_apis.for_repository(item)
        merged = git_api.get_new_merged_pulls(repo_path=item.repo_path, merged_after=item.pr_cursor)
        self.log.info(f"Git provider returned {len(merged)} new PRs for {item.repo_path} since {item.pr_cursor}")
        return bool(merged)

    def run_request(self, item: TriggerRepository) -> dg.RunRequest:
        """The run that ingests the repository's merged PRs since its cursor."""
        return dg.RunRequest(
            run_key=run_key("ingest", item.id, item.pr_cursor),
            tags=self.tags(item),
            run_config={"ops": {ingest_pull_requests.name: {"config": {"repo_id": item.id}}}},
        )
