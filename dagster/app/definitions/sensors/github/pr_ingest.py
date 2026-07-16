import json
from datetime import datetime as dt
from datetime import timezone as tz
from typing import Generator

import dagster as dg

from app.definitions.sensors.github.base import GithubSensor
from app.models import Repository, PullRequest, PullRequestStatus


class PullRequestIngestSensor(GithubSensor):
    """Polls GitHub for new merged PRs and saves them to database."""

    def __call__(self):
        """Execute the sensor. Yields SkipReason if no work, otherwise processes PRs."""
        repositories = self.backend_api.get_repositories()
        if not repositories:
            yield dg.SkipReason("No repositories found in database.")
            return

        prs_found = []
        for repo in repositories:
            polled_at = dt.now(tz.utc).isoformat()

            self.log.info(f"Fetching PRs for {repo.path} since {repo.last_merged_at}")
            pull_reqs = self.github_api.get_new_merged_pulls(
                repo_path=repo.path,
                base_branch=repo.base_branch,
                merged_after=repo.last_merged_at,
            )
            self.log.info(f"GitHub returned {len(pull_reqs)} PRs for {repo.path}")

            for pr_data in pull_reqs:
                pr = self._fetch_pr(repo, pr_data["number"])
                self._spec_and_validate(repo, pr)
                repo.pull_requests.append(pr)

            self.log.info(f"Validated {len(repo.pull_requests)}/{len(pull_reqs)} PRs for {repo.path}")

            if repo.pull_requests:
                self.log.info(f"Saving batch of {len(repo.pull_requests)} PRs for repo {repo.id}")
                pr_dicts = [pr.model_dump(exclude={'repository_id'}) for pr in repo.pull_requests]
                self.backend_api.create_pull_requests_batch(repo.id, pr_dicts)
                prs_found.extend(pr_dicts)

            self.backend_api.patch_repository(repo.id, {"polled_at": polled_at})

        if not prs_found:
            yield dg.SkipReason("No new pull requests found for repositories in GitHub.")
            return

        yield dg.SkipReason(f"Saved {len(prs_found)} new pull requests to database.")

    def _fetch_pr(self, repo: Repository, pr_number: int) -> PullRequest:
        pr = self.github_api.get_pull_request(repo.path, pr_number)
        return PullRequest(
            repository_id=repo.id,
            number=pr['number'],
            title=pr['title'],
            raised_by=pr['user']['login'],
            merged_at=pr['merged_at'],
            merge_commit_sha=pr['merge_commit_sha'],
            is_valid=False,
            status=PullRequestStatus.UNPROCESSED.value,
            spec={},
        )

    def _spec_and_validate(self, repo: Repository, pr: PullRequest) -> PullRequest | None:
        pr_files = self.github_api.get_pull_request_files(repo.path, pr.number)
        try:
            pr.spec = self._fetch_spec(repo, pr_files, pr.merge_commit_sha)
            pr.is_valid = True  # TODO: Spec JSON validation
        except Exception as e:
            pr.is_valid = False
            self.log.info(f"PR #{pr.number} in repo {repo.path} is invalid: {e}")

    def _fetch_spec(self, repo: Repository, pr_files: list[dict], ref: str):
        spec = self._find_spec_file(repo.watch_dir, pr_files)
        contents = self.github_api.get_file_contents(
            repo_path=repo.path,
            file_path=spec['filename'],
            ref=ref,
        )
        return json.loads(contents).get('spec', {})  # FIXME: validation needed?

    def _find_spec_file(self, watch_dir: str, pr_files: list[dict]):
        files = [f for f in pr_files if self._is_spec_file(f, watch_dir)]
        if len(files) > 1:
            raise MultipleSpecFileError
        if len(files) == 0:
            raise NotFoundSpecFileError
        return files[0]

    def _is_spec_file(self, file, watch_dir: str):
        is_dir = file["filename"].startswith(watch_dir)
        is_ext = file["filename"].endswith('.json')
        is_new = file["status"] == "added"
        return is_dir and is_ext and is_new

    def _save_prs(self, repo: Repository, pull_reqs: list[PullRequest]) -> None:
        """Save valid PRs to database."""
        for pr in pull_reqs:
            self.backend_api.create_pull_request(**pr.model_dump())


class MultipleSpecFileError(Exception):
    pass


class NotFoundSpecFileError(Exception):
    pass
