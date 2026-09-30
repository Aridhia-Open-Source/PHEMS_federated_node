import json
from http import HTTPStatus
from typing import cast

import dagster as dg
import requests

from app.definitions.sensors.git.base import GitAPI, GitSensor
from app.models import PullRequest, PullRequestStatus, TriggerRepository


class PullRequestProcessSensor(GitSensor):
    """
    Reads the spec of each UNKNOWN PR in a trigger repository of an enabled project,
    and raises its task request. The PR ends READY, IGNORED or INVALID.
    """

    def __call__(self):
        """Execute the sensor. Yields a SkipReason summarising what was processed."""
        enabled = {p.id for p in self.backend_api.get_projects() if p.enabled}
        repositories = [r for r in self.backend_api.get_repositories() if r.project_id in enabled]
        if not repositories:
            yield dg.SkipReason("No repositories of enabled projects found in database.")
            return

        processed = 0
        for repo in repositories:
            try:
                unknown_prs = self.backend_api.get_pull_requests(
                    repo_id=repo.id,
                    status=PullRequestStatus.UNKNOWN.value,
                )
            except Exception as e:
                self.log.error(f"Failed to fetch PRs for repo {repo.id}: {e}")
                continue

            if not unknown_prs:
                continue

            self.log.info(f"Found {len(unknown_prs)} unknown PRs for repo {repo.id}")
            git_api = self.git_apis.for_repository(repo)

            for pr in unknown_prs:
                try:
                    status, payload = self._setup_pull_request(git_api, repo, pr)
                    self.backend_api.patch_pull_request(
                        repo.id, pr.number, {"status": status, "payload": payload}
                    )
                    processed += 1
                except Exception as e:
                    self.log.error(f"Failed to process PR #{pr.number}: {e}")

        if not processed:
            yield dg.SkipReason("No unknown pull requests found.")
            return

        yield dg.SkipReason(f"Processed {processed} pull requests.")

    def _setup_pull_request(self, git_api: GitAPI, repo: TriggerRepository, pr: PullRequest) -> tuple[str, dict]:
        spec = {}
        pr_files = git_api.get_pull_request_files(repo.path, pr.number)
        watched_files = self._filter_watched_files(repo.watch_dir, pr_files)
        watched_file_names = [f["filename"] for f in watched_files]
        self.log.info(f"PR #{pr.number} in {repo.path}: watched files {watched_file_names}")

        if not watched_file_names:
            self.log.warning("No watched files - marking IGNORED")
            return PullRequestStatus.IGNORED.value, spec
        if len(watched_file_names) > 1:
            self.log.warning(f"Multiple watched files ({len(watched_file_names)}) - marking INVALID")
            return PullRequestStatus.INVALID.value, spec

        try:
            spec_file_name = cast(str, watched_file_names[0])
            spec_contents = self._get_spec_data(git_api, repo, spec_file_name, pr.merge_commit_sha)
            spec = self._validate_spec(spec_contents)
        except Exception as e:
            self.log.error(f"PR #{pr.number} spec is invalid: {type(e).__name__}: {e}")
            return PullRequestStatus.INVALID.value, {}

        try:
            self.backend_api.create_task_request(repo.id, pr.number, spec)
        except requests.HTTPError as e:
            # The backend normalises the spec and rejects one it cannot run
            if e.response.status_code != HTTPStatus.BAD_REQUEST:
                raise
            self.log.error(f"PR #{pr.number} spec rejected by the backend: {e.response.text}")
            return PullRequestStatus.INVALID.value, {}
        return PullRequestStatus.READY.value, spec

    def _validate_spec(self, data: dict):
        spec = data['spec']
        if not isinstance(spec, dict):
            raise ValueError("Spec must be a dictionary")
        if not spec.get("image") and not spec.get("docker_image"):
            raise ValueError("Spec must contain 'image' or 'docker_image' key")

        return spec

    def _get_spec_data(self, git_api: GitAPI, repo: TriggerRepository, filepath: str, ref: str):
        contents = git_api.get_file_contents(
            repo_path=repo.path,
            file_path=filepath,
            ref=ref,
        )
        return json.loads(contents)

    def _filter_watched_files(self, watch_dir: str, pr_files: list[dict]):
        def _is_watched_json_file(f):
            is_dir = f["filename"].startswith(watch_dir)
            is_ext = f["filename"].endswith('.json')
            is_new = f["status"] == "added"
            return is_dir and is_ext and is_new

        return [f for f in pr_files if _is_watched_json_file(f)]
