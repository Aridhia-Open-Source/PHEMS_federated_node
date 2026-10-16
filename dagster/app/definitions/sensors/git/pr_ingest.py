import dagster as dg

from app.definitions.sensors.git.base import GitAPI, GitSensor
from app.models import NewPullRequest, ProjectTriggerRepository, TriggerRepository


class PullRequestIngestSensor(GitSensor):
    """
    Polls the git provider once per global trigger repository that has an active assignment,
    with the repository's own secret and the global cursor, and posts the new merged PRs once for
    every project. The poll has no base branch filter: each PR carries its base branch and the
    backend matches it per assignment. Disabled projects' assignments do not count. A project's lock does not stop the poll, it pauses
    evaluation and launch.
    """

    def __call__(self):
        """Execute the sensor. Yields a SkipReason summarising what was saved."""
        enabled = {p.id for p in self.backend_api.get_projects() if p.enabled}
        assignments = [a for a in self.backend_api.get_repositories(active_only=True) if a.project_id in enabled]
        if not assignments:
            yield dg.SkipReason("No repositories of enabled projects found in database.")
            return

        by_repository: dict[int, list[ProjectTriggerRepository]] = {}
        for assignment in assignments:
            by_repository.setdefault(assignment.trigger_repository.id, []).append(assignment)

        saved = 0
        for group in by_repository.values():
            repo = group[0].trigger_repository
            # No pull request stored yet: start at the earliest cursor of its assignments
            cursor = repo.pr_cursor or min(a.pr_cursor for a in group)
            git_api = self.git_apis.for_repository(repo)
            self.log.info(f"Fetching PRs for {repo.repo_path} since {cursor}")
            merged = git_api.get_new_merged_pulls(repo_path=repo.repo_path, merged_after=cursor)
            self.log.info(f"Git provider returned {len(merged)} PRs for {repo.repo_path}")
            if not merged:
                continue

            pull_requests = [self._fetch_pr(git_api, repo, pr["number"]) for pr in merged]
            self.log.info(f"Saving batch of {len(pull_requests)} PRs for repo {repo.id}")
            self.backend_api.create_pull_requests_batch(repo.id, [pr.model_dump() for pr in pull_requests])
            saved += len(pull_requests)

        if not saved:
            yield dg.SkipReason("No new pull requests found for repositories.")
            return

        yield dg.SkipReason(f"Saved {saved} new pull requests to database.")

    def _fetch_pr(self, git_api: GitAPI, repo: TriggerRepository, pr_number: int) -> NewPullRequest:
        """The pull request and the files it changed, which the backend matches against each watcher's watch_dir."""
        pr = git_api.get_pull_request(repo.repo_path, pr_number)
        files = git_api.get_pull_request_files(repo.repo_path, pr_number)
        return NewPullRequest.from_git(pr, files)
