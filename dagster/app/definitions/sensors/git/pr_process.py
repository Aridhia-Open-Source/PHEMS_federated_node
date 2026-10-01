from http import HTTPStatus

import dagster as dg
import requests

from app.definitions.sensors.git.base import GitSensor
from app.definitions.sensors.git.pr_parser import PullRequestParser
from app.models import PullRequest, PullRequestStatus, TriggerRepository


class PullRequestProcessSensor(GitSensor):
    """
    Reads the spec of each UNKNOWN PR in a trigger repository of an enabled project,
    and raises its task request. The PR ends READY, IGNORED or INVALID.
    """

    def __call__(self):
        """Execute the sensor. Yields a SkipReason summarising what was processed."""
        repositories = self._enabled_repositories()
        if not repositories:
            yield dg.SkipReason("No repositories of enabled projects found in database.")
            return

        processed = sum(self._process_repository(repo) for repo in repositories)
        if not processed:
            yield dg.SkipReason("No unknown pull requests found.")
            return

        yield dg.SkipReason(f"Processed {processed} pull requests.")

    def _enabled_repositories(self) -> list[TriggerRepository]:
        enabled = {p.id for p in self.backend_api.get_projects() if p.enabled}
        return [r for r in self.backend_api.get_repositories() if r.project_id in enabled]

    def _unknown_pull_requests(self, repo: TriggerRepository) -> list[PullRequest]:
        try:
            unknown_prs = self.backend_api.get_pull_requests(
                repo_id=repo.id,
                status=PullRequestStatus.UNKNOWN.value,
            )
        except Exception as e:
            self.log.error(f"Failed to fetch PRs for repo {repo.id}: {e}")
            return []
        if unknown_prs:
            self.log.info(f"Found {len(unknown_prs)} unknown PRs for repo {repo.id}")
        return unknown_prs

    def _process_repository(self, repo: TriggerRepository) -> int:
        """Process the UNKNOWN PRs of a repository. Returns how many were patched."""
        unknown_prs = self._unknown_pull_requests(repo)
        if not unknown_prs:
            return 0

        parser = PullRequestParser(self.git_apis.for_repository(repo), repo, self.log)
        processed = 0
        for pr in unknown_prs:
            try:
                status, payload = self._process_pull_request(parser, repo, pr)
                self.backend_api.patch_pull_request(
                    repo.id, pr.number, {"status": status, "payload": payload}
                )
                processed += 1
            except Exception as e:
                self.log.error(f"Failed to process PR #{pr.number}: {e}")
        return processed

    def _process_pull_request(
        self, parser: PullRequestParser, repo: TriggerRepository, pr: PullRequest
    ) -> tuple[str, dict]:
        status, spec = parser.parse(pr)
        if spec is None:
            return status.value, {}

        payload = spec.model_dump()
        try:
            self.backend_api.create_task_request(repo.id, pr.number, payload)
        except requests.HTTPError as e:
            # The backend normalises the spec and rejects one it cannot run
            if e.response.status_code != HTTPStatus.BAD_REQUEST:
                raise
            self.log.error(f"PR #{pr.number} spec rejected by the backend: {e.response.text}")
            return PullRequestStatus.INVALID.value, {}
        return status.value, payload
