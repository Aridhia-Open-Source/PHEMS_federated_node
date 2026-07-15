from typing import Generator

import dagster as dg

from app.definitions.sensors.github.base import GithubSensor
from app.models import Repository, PullRequest, PullRequestStatus


class PullRequestTriggerSensor(GithubSensor):
    """Reads validated PRs from database and triggers task creation + monitoring."""

    def __call__(self):
        """
        Execute the sensor. Returns list of RunRequests or SkipReason.

        Flow:
        1. Fetch unprocessed valid PRs from database
        2. For each PR, extract executors from spec
        3. Create RunRequest to monitor task status
        4. Mark PR as processed (on success, not here - in status sensor)
        """
        repositories = self.backend_api.get_repositories()
        if not repositories:
            yield dg.SkipReason("No repositories found in database.")
            return

        pr_count = 0
        for repo in repositories:
            try:
                unprocessed_prs = self._fetch_unprocessed_prs(repo.id)
            except Exception as e:
                self.log.error(f"Failed to fetch PRs for repo {repo.id}: {e}")
                continue

            if not unprocessed_prs:
                continue

            self.log.info(f"Found {len(unprocessed_prs)} unprocessed PRs for repo {repo.id}")

            for pr in unprocessed_prs:
                try:
                    yield self._make_run_request(repo, pr)
                    self.backend_api.update_pull_request_status(
                        repo_id=repo.id,
                        number=pr.number,
                        status=PullRequestStatus.IN_PROGRESS.value,
                    )
                    pr_count += 1
                except Exception as e:
                    self.log.error(f"Failed to create request for PR #{pr.number}: {e}")

        if not pr_count:
            yield dg.SkipReason("No unprocessed pull requests found.")

    def _fetch_unprocessed_prs(self, repo_id: int) -> list[PullRequest]:
        """Fetch valid, unprocessed PRs from database, sorted by merge time DESC."""
        return self.backend_api.get_pull_requests(
            repo_id=repo_id,
            status=PullRequestStatus.UNPROCESSED.value,
            is_valid="true",
        )

    def _make_run_request(self, repo: Repository, pr: PullRequest) -> dg.RunRequest:
        """
        Create RunRequest to trigger k8s_pipes_job.
        Uses PR composite key as run_key for idempotency.
        Includes PR tags for run_status_sensors to monitor and update PR status.
        Passes spec to k8s_pipes_op via run_config.
        """
        env = pr.spec.get("env") or {}
        run_key = f"{pr.repository_id}/{pr.number}"
        docker_image = pr.spec.get("image") or pr.spec.get("docker_image")

        if not docker_image:
            raise ValueError(f"PR #{pr.number} spec in repo {repo.path} missing 'image'")

        return dg.RunRequest(
            run_key=run_key,
            tags={
                "trigger": "github",
                "pr_number": str(pr.number),
                "pr_title": pr.title,
                "repo_id": str(repo.id),
                "repo_uri": repo.uri,
            },
            run_config={
                "ops": {
                    "k8s_pipes_op": {
                        "config": {
                            "docker_image": docker_image,
                            "env": env,
                        }
                    }
                }
            },
        )
