import dagster as dg

from app.definitions.sensors.git.base import GitAPI, GitSensor
from app.models import PullRequest, PullRequestStatus, TriggerRepository


class PullRequestIngestSensor(GitSensor):
    """Polls the git provider for new merged PRs and saves them to the database."""

    def __call__(self):
        """Execute the sensor. Yields a SkipReason summarising what was saved."""
        repositories = self.backend_api.get_repositories()
        if not repositories:
            yield dg.SkipReason("No repositories found in database.")
            return

        saved = 0
        for repo in repositories:
            git_api = self.git_apis.for_repository(repo)
            self.log.info(f"Fetching PRs for {repo.repo_path} since {repo.pr_cursor}")
            merged = git_api.get_new_merged_pulls(
                repo_path=repo.repo_path,
                base_branch=repo.base_branch,
                merged_after=repo.pr_cursor,
            )
            self.log.info(f"Git provider returned {len(merged)} PRs for {repo.repo_path}")
            if not merged:
                continue

            pull_requests = [self._fetch_pr(git_api, repo, pr["number"]) for pr in merged]
            self.log.info(f"Saving batch of {len(pull_requests)} PRs for repo {repo.id}")
            self.backend_api.create_pull_requests_batch(
                repo.id,
                [pr.model_dump(exclude={"trigger_repository_id"}) for pr in pull_requests],
            )
            saved += len(pull_requests)

        if not saved:
            yield dg.SkipReason("No new pull requests found for repositories.")
            return

        yield dg.SkipReason(f"Saved {saved} new pull requests to database.")

    def _fetch_pr(self, git_api: GitAPI, repo: TriggerRepository, pr_number: int) -> PullRequest:
        pr = git_api.get_pull_request(repo.repo_path, pr_number)
        return PullRequest(
            trigger_repository_id=repo.id,
            number=pr["number"],
            title=pr["title"],
            raised_by=pr["user"]["login"],
            merged_at=pr["merged_at"],
            merge_commit_sha=pr["merge_commit_sha"],
            status=PullRequestStatus.UNKNOWN.value,
            payload={},
        )
