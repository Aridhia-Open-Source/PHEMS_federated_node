import json
from typing import cast

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
                unknown_prs = self._fetch_unknown_prs(repo.id)
            except Exception as e:
                self.log.error(f"Failed to fetch PRs for repo {repo.id}: {e}")
                continue

            if not unknown_prs:
                continue

            self.log.info(f"Found {len(unknown_prs)} unknown PRs for repo {repo.id}")

            for pr in unknown_prs:
                try:
                    pr.status, pr.spec = self._setup_pull_request(repo, pr)
                    if pr.status == PullRequestStatus.READY.value:
                        yield self._make_run_request(repo, pr)

                    patch_data = {'status': pr.status, 'spec': pr.spec}
                    self.backend_api.patch_pull_request(repo.id, pr.number, patch_data)
                    pr_count += 1
                except Exception as e:
                    self.log.error(f"Failed to create request for PR #{pr.number}: {e}")

        if not pr_count:
            yield dg.SkipReason("No unknown pull requests found.")

    def _fetch_unknown_prs(self, repo_id: int) -> list[PullRequest]:
        """Fetch unknown PRs from database, sorted by merged_at?"""
        return self.backend_api.get_pull_requests(
            repo_id=repo_id,
            status=PullRequestStatus.UNKNOWN.value,
        )

    def _setup_pull_request(self, repo: Repository, pr: PullRequest) -> tuple[str, dict]:
        spec = {}
        self.log.info(f"=== SETUP PR #{pr.number} in repo {repo.path} ===")
        self.log.info(f"Watch dir: {repo.watch_dir}")

        pr_files = self.github_api.get_pull_request_files(repo.path, pr.number)
        self.log.info(f"Files in PR: {[f['filename'] for f in pr_files]}")

        watched_files = self._filter_watched_files(repo.watch_dir, pr_files)
        watched_file_names = [f["filename"] for f in watched_files]

        self.log.info(f"Watched files found: {watched_file_names} (count: {len(watched_file_names)})")

        if not watched_file_names:
            self.log.warning("No watched files - marking IGNORED")
            return PullRequestStatus.IGNORED.value, spec
        if len(watched_file_names) > 1:
            self.log.warning(f"Multiple watched files ({len(watched_file_names)}) - marking INVALID")
            return PullRequestStatus.INVALID.value, spec

        try:
            spec_file_name = cast(str, watched_file_names[0])
            self.log.info(f"Fetching spec from: {spec_file_name}")
            spec_contents = self._get_spec_data(repo, spec_file_name, pr.merge_commit_sha)
            self.log.info(f"Spec contents fetched: {spec_contents}")
            spec = self._validate_spec(spec_contents)
            self.log.info(f"Spec validated: {spec}")
            return PullRequestStatus.READY.value, spec
        except Exception as e:
            self.log.error(f"EXCEPTION in _setup_pull_request PR #{pr.number}: {type(e).__name__}: {e}", exc_info=True)
            pr.spec = {}
            return PullRequestStatus.INVALID.value, spec

    def _validate_spec(self, data: dict):
        spec = data['spec']
        if not isinstance(spec, dict):
            raise ValueError("Spec must be a dictionary")
        if not spec.get("image") and not spec.get("docker_image"):
            raise ValueError("Spec must contain 'image' or 'docker_image' key")

        return spec

    def _get_spec_data(self, repo: Repository, filepath: str, ref: str):
        contents = self.github_api.get_file_contents(
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

    def _make_run_request(self, repo: Repository, pr: PullRequest) -> dg.RunRequest:
        """
        Create RunRequest to trigger k8s_pipes_job.
        Uses PR composite key as run_key for idempotency.
        Includes PR tags for run_status_sensors to monitor and update PR status.
        Passes spec to k8s_pipes_op via run_config.
        Injects dataset credentials as mounted secret volume.
        """
        if not pr.spec.get("image"):
            raise ValueError(f"PR #{pr.number} spec in repo {repo.path} missing 'image'")

        dataset = self.backend_api.get_dataset(repo.dataset_id)

        return dg.RunRequest(
            run_key=f"{pr.repository_id}/{pr.number}",
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
                            "env": pr.spec.get("env") or {},
                            "docker_image": pr.spec["image"],
                            **dataset.dump_task_fields(),
                        }
                    }
                }
            },
        )

