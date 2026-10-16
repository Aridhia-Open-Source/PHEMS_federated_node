import dagster as dg

from app.definitions.sensors.git.base import GitAPI, GitSensor
from app.models import NewPullRequest, TriggerRepository


class PullRequestIngestSensor(GitSensor):
    """
    Polls the git provider once per global trigger repository that has an active link of an
    enabled project, with the repository's own secret and the cursor the backend gives it, and
    posts the new merged PRs once for every project. The poll has no base branch filter: each PR
    carries its base branch and the backend matches it per link. Disabled projects' links do not
    count. A project's lock does not stop the poll, it pauses evaluation and launch.
    """

    def __call__(self):
        """Execute the sensor. Yields a SkipReason summarising what was saved."""
        repos = self.backend_api.get_active_trigger_repositories()
        if not repos:
            yield dg.SkipReason("No repositories of enabled projects found in database.")
            return

        saved = sum(self._ingest(repo) for repo in repos)
        if not saved:
            yield dg.SkipReason("No new pull requests found for repositories.")
            return

        yield dg.SkipReason(f"Saved {saved} new pull requests to database.")

    def _ingest(self, repo: TriggerRepository) -> int:
        """
        Posts the PRs merged on the repository since its cursor, the latest stored merge or, with
        none stored, the earliest cursor of its links. Returns how many were posted.
        """
        cursor = repo.pr_cursor
        # Claude (issue 1): repo.pr_cursor is max(merged_at) of the STORED PRs, so it only
        # moves once a batch is accepted. A refused batch = same cursor = same failure every tick.
        # A new repository starts at the earliest project cursor and polls all branches,
        # so this fetch can easily return more than 100 PRs.
        git_api = self.git_apis.for_repository(repo)
        self.log.info(f"Fetching PRs for {repo.repo_path} since {cursor}")
        merged = git_api.get_new_merged_pulls(repo_path=repo.repo_path, merged_after=cursor)
        self.log.info(f"Git provider returned {len(merged)} PRs for {repo.repo_path}")
        if not merged:
            return 0

        pull_requests = [self._fetch_pr(git_api, repo, pr["number"]) for pr in merged]
        self.log.info(f"Saving batch of {len(pull_requests)} PRs for repo {repo.id}")
        # Claude (issue 1): everything goes in ONE post, but the batch is capped at 100 and is
        # refused whole if one PR is invalid. Fix: sort by (merged_at, number) and post in chunks
        # of 100, so the cursor advances chunk by chunk and never skips an unposted PR.
        self.backend_api.create_pull_requests_batch(repo.id, [pr.model_dump() for pr in pull_requests])
        return len(pull_requests)

    def _fetch_pr(self, git_api: GitAPI, repo: TriggerRepository, pr_number: int) -> NewPullRequest:
        """The pull request and the files it changed, which the backend matches against each watcher's watch_dir."""
        pr = git_api.get_pull_request(repo.repo_path, pr_number)
        files = git_api.get_pull_request_files(repo.repo_path, pr_number)
        # Claude (issue 1): a duplicate path here makes the backend 500 the whole batch
        # (pull_request_files primary key). Fix: de-duplicate paths before building the PR.
        return NewPullRequest.from_git(pr, files)
