import json
from datetime import datetime as dt
from datetime import timezone as tz

import dagster as dg

from app.definitions.sensors.gitea.base import GiteaSensor
from app.models import TriggerRepository, PullRequest, PullRequestStatus


class PullRequestIngestSensor(GiteaSensor):
    """Polls Gitea for new merged PRs and saves them to database."""

    def __call__(self):
        """Execute the sensor. Yields SkipReason if no work, otherwise processes PRs."""
        repositories = self.backend_api.get_repositories()
        if not repositories:
            yield dg.SkipReason("No repositories found in database.")
            return

        prs_found = []
        for repo in repositories:
            self.log.info(f"Fetching PRs for {repo.path} since {repo.pr_cursor}")
            pull_reqs = self.gitea_api.get_new_merged_pulls(
                repo_path=repo.path,
                base_branch=repo.base_branch,
                merged_after=repo.pr_cursor
            )
            self.log.info(f"Gitea returned {len(pull_reqs)} PRs for {repo.path}")

            for pr_data in pull_reqs:
                pr = self._fetch_pr(repo, pr_data["number"])
                repo.pull_requests.append(pr)

            self.log.info(f"Ingested {len(repo.pull_requests)}/{len(pull_reqs)} PRs for {repo.path}")

            if repo.pull_requests:
                self.log.info(f"Saving batch of {len(repo.pull_requests)} PRs for repo {repo.id}")
                pr_dicts = [pr.model_dump(exclude={'trigger_repository_id'}) for pr in repo.pull_requests]
                self.backend_api.create_pull_requests_batch(repo.id, pr_dicts)
                prs_found.extend(pr_dicts)

        if not prs_found:
            yield dg.SkipReason("No new pull requests found for repositories in Gitea.")
            return

        yield dg.SkipReason(f"Saved {len(prs_found)} new pull requests to database.")

    def _fetch_pr(self, repo: TriggerRepository, pr_number: int) -> PullRequest:
        pr = self.gitea_api.get_pull_request(repo.path, pr_number)
        return PullRequest(
            trigger_repository_id=repo.id,
            number=pr['number'],
            title=pr['title'],
            raised_by=pr['user']['login'],
            merged_at=pr['merged_at'],
            merge_commit_sha=pr['merge_base_sha'],
            status=PullRequestStatus.UNKNOWN.value,
            payload={},
        )
