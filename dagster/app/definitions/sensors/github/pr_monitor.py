"""GitHub PR status monitoring via run_status_sensor."""

from typing import Any

import dagster as dg
from dagster import RunStatusSensorContext, DagsterRun, SkipReason
from app.backend import BackendAPI
from app.github import GithubAPI
from app.models import PullRequestStatus


class PullRequestTaskMonitor:
    """Monitors the status of a PR task run and updates the PR status in the database."""

    STATUS: str

    def __init__(
        self,
        context: RunStatusSensorContext,
        backend_api: BackendAPI,
        github_api: GithubAPI,
    ):
        """Initialize with RunStatusSensorContext and API clients."""
        self.context = context
        self.log = context.log
        self.backend_api = backend_api
        self.github_api = github_api

    @property
    def run(self) -> DagsterRun:
        return self.context.dagster_run

    @property
    def is_github_trigger(self) -> bool:
        return self.run.tags.get("trigger") == "github"

    @property
    def pr_number(self) -> int:
        return int(self.run.tags['pr_number'])

    @property
    def repo_id(self) -> int:
        return int(self.run.tags['repo_id'])

    def validate(self) -> bool | None:
        if not self.is_github_trigger:
            return

        if not self.run.tags.get("pr_number") or not self.run.tags.get("repo_id"):
            raise ValueError("Run is missing required PR tags: 'pr_number' and 'repo_id'.")

        return True


class PullRequestStatusSuccessSensor(PullRequestTaskMonitor):
    """Marks PR as success when k8s_pipes_job completes successfully."""

    STATUS = PullRequestStatus.SUCCESS.value

    def __call__(self):
        """Monitor successful job completion, mark PR, and trigger transfer."""
        if not self.validate():
            yield SkipReason("Run is not triggered from github")
            return

        self.log.info(f"Marking PR #{self.pr_number} in repo {self.repo_id} as success")

        self.backend_api.patch_pull_request(
            self.repo_id, self.pr_number, {"status": self.STATUS}
        )

        yield dg.RunRequest(
            job_name="github_transfer_job",
            run_key=f"{self.repo_id}/{self.pr_number}",
            tags={
                "trigger": "github",
                "pr_number": str(self.pr_number),
                "repo_id": str(self.repo_id),
                "parent_run_id": self.run.run_id,
            },
            run_config={
                "ops": {
                    "github_transfer_op": {
                        "config": {
                            "pr_number": str(self.pr_number),
                            "parent_run_id": self.run.run_id,
                            "repo_uri": self.run.tags["repo_uri"],
                        }
                    }
                }
            },
        )



class PullRequestStatusFailureSensor(PullRequestTaskMonitor):
    """Marks PR as failed when k8s_pipes_job completes with failure."""

    STATUS = PullRequestStatus.FAILURE.value

    def __call__(self):
        """Monitor failed job completion and mark PR as failed."""
        if not self.validate():
            yield SkipReason("Run is not triggered from github")
            return

        self.log.error(f"Marking PR #{self.pr_number} in repo {self.repo_id} as failed")

        self.backend_api.patch_pull_request(
            self.repo_id, self.pr_number, {"status": self.STATUS}
        )
