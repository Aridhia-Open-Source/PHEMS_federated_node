import dagster as dg

from app.definitions.sensors.git.base import GitAPI, GitSensor
from app.models import NewPullRequest, TriggerRepository

# The most pull requests the backend takes in one ingest
MAX_BATCH_SIZE = 100


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

        saved = 0
        failed = []
        for repo in repos:
            try:
                saved += self._ingest(repo)
            except Exception:  # pylint: disable=broad-exception-caught  # one repository must not stop the others
                self.log.exception(f"Ingesting pull requests of {repo.uri} failed")
                failed.append(repo.uri)
        if failed:
            raise RuntimeError(f"Ingest failed for {', '.join(failed)}; saved {saved} new pull requests of the others")
        if not saved:
            yield dg.SkipReason("No new pull requests found for repositories.")
            return

        yield dg.SkipReason(f"Saved {saved} new pull requests to database.")

    def _ingest(self, repo: TriggerRepository) -> int:
        """
        Posts the PRs merged on the repository since its cursor, the latest stored merge or, with
        none stored, the earliest cursor of its links, in batches of at most MAX_BATCH_SIZE, oldest
        first: the cursor only moves once a batch is stored, so a batch never leaves an older
        unposted PR behind it. Returns how many were posted.
        """
        git_api = self.git_apis.for_repository(repo)
        self.log.info(f"Fetching PRs for {repo.repo_path} since {repo.pr_cursor}")
        merged = git_api.get_new_merged_pulls(repo_path=repo.repo_path, merged_after=repo.pr_cursor)
        self.log.info(f"Git provider returned {len(merged)} PRs for {repo.repo_path}")

        pull_requests = sorted(
            (self._fetch_pr(git_api, repo, pr["number"]) for pr in merged), key=lambda pr: (pr.merged_at, pr.number)
        )
        for start in range(0, len(pull_requests), MAX_BATCH_SIZE):
            batch = pull_requests[start:start + MAX_BATCH_SIZE]
            self.log.info(f"Saving batch of {len(batch)} PRs for repo {repo.id}")
            self.backend_api.create_pull_requests_batch(repo.id, [pr.model_dump() for pr in batch])
        return len(pull_requests)

    def _fetch_pr(self, git_api: GitAPI, repo: TriggerRepository, pr_number: int) -> NewPullRequest:
        """The pull request and the files it changed, which the backend matches against each watcher's watch_dir."""
        pr = git_api.get_pull_request(repo.repo_path, pr_number)
        files = git_api.get_pull_request_files(repo.repo_path, pr_number)
        # Claude (issue 1): a duplicate path here makes the backend 500 the whole batch
        # (pull_request_files primary key). Fix: de-duplicate paths before building the PR.
        return NewPullRequest.from_git(pr, files)
