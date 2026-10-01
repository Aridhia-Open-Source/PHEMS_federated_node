import json
from typing import cast

from app.definitions.sensors.git.base import GitAPI
from app.models import PullRequest, PullRequestSpec, PullRequestStatus, TriggerRepository


class PullRequestParser:
    """
    Reads the spec a pull request carries: finds the new spec file in the repository's
    watch_dir, reads it at the merge commit and validates its spec.
    """

    def __init__(self, git_api: GitAPI, repo: TriggerRepository, log):
        self.git_api = git_api
        self.repo = repo
        self.log = log

    def parse(self, pr: PullRequest) -> tuple[PullRequestStatus, PullRequestSpec | None]:
        """
        IGNORED if the PR has no watched file, INVALID if it has several or its spec is
        invalid, else READY with the spec.
        """
        pr_files = self.git_api.get_pull_request_files(self.repo.path, pr.number)
        watched_files = self._filter_watched_files(pr_files)
        watched_file_names = [f["filename"] for f in watched_files]
        self.log.info(f"PR #{pr.number} in {self.repo.path}: watched files {watched_file_names}")

        if not watched_file_names:
            self.log.warning("No watched files - marking IGNORED")
            return PullRequestStatus.IGNORED, None
        if len(watched_file_names) > 1:
            self.log.warning(f"Multiple watched files ({len(watched_file_names)}) - marking INVALID")
            return PullRequestStatus.INVALID, None

        try:
            data = self._get_spec_data(cast(str, watched_file_names[0]), pr.merge_commit_sha)
            spec = PullRequestSpec.model_validate(data["spec"])
        except Exception as e:
            self.log.error(f"PR #{pr.number} spec is invalid: {type(e).__name__}: {e}")
            return PullRequestStatus.INVALID, None
        return PullRequestStatus.READY, spec

    def _get_spec_data(self, filepath: str, ref: str):
        contents = self.git_api.get_file_contents(
            repo_path=self.repo.path,
            file_path=filepath,
            ref=ref,
        )
        return json.loads(contents)

    def _filter_watched_files(self, pr_files: list[dict]):
        def _is_watched_json_file(f):
            is_dir = f["filename"].startswith(self.repo.watch_dir)
            is_ext = f["filename"].endswith('.json')
            is_new = f["status"] == "added"
            return is_dir and is_ext and is_new

        return [f for f in pr_files if _is_watched_json_file(f)]
