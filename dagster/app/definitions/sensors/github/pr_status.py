import dagster as dg
from dagster import RunStatusSensorContext

from app.definitions.sensors.github.base import GithubSensor
from app.models import PullRequestStatus


class PullRequestStatusSensor(GithubSensor):
    """Updates PR status based on k8s_pipes_job lifecycle events."""

    STATUS_MAP = {
        "QUEUED": PullRequestStatus.QUEUED.value,
        "STARTED": PullRequestStatus.STARTED.value,
        "SUCCESS": PullRequestStatus.SUCCESS.value,
        "FAILURE": PullRequestStatus.FAILURE.value,
        "CANCELED": PullRequestStatus.CANCELLED.value,
    }

    def __call__(self, context: RunStatusSensorContext):
        """
        Execute the sensor. Updates PR status based on job status change.
        On SUCCESS, yields RunRequest to trigger transfer job.
        """
        run = context.dagster_run

        pr_status = self.STATUS_MAP.get(run.status.value)
        if not pr_status:
            self.log.warning(f"Unknown run status: {run.status.value}")
            return

        pr_number = run.tags.get("pr_number")
        repo_id = run.tags.get("repo_id")

        if not pr_number or not repo_id:
            self.log.error(f"Missing PR tags on run {run.run_id}: pr_number={pr_number}, repo_id={repo_id}")
            return

        try:
            self.backend_api.patch_pull_request(int(repo_id), int(pr_number), {"status": pr_status})
            self.log.info(f"Updated PR #{pr_number} in repo {repo_id} to status: {pr_status}")

            if run.status == dg.DagsterRunStatus.SUCCESS:
                self.log.info(f"PR #{pr_number} succeeded, triggering transfer job")
                yield dg.RunRequest(
                    run_key=f"{pr_number}-transfer",
                    tags={
                        "trigger": "github_transfer",
                        "pr_number": pr_number,
                        "parent_run_id": run.run_id,
                    },
                )
        except Exception as e:
            self.log.error(f"Failed to update PR #{pr_number}: {e}")
