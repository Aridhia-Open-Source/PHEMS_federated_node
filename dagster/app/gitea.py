import base64
import logging
import time
from datetime import datetime as dt

import requests

from app.utils import HttpClient

GITEA_API_BASE_URL = "http://gitea.fn.svc:4000/api/v1"
# Gitea caps a page at 50 by default (it ignores per_page and takes limit).
GITEA_PAGE_SIZE = 50

default_logger = logging.getLogger(__name__)


class GiteaClient(HttpClient):
    def __init__(self, token: str, session=None, base_uri: str = GITEA_API_BASE_URL):
        super().__init__(base_uri, token=token, session=session)


class GiteaAPI:
    def __init__(self, client: GiteaClient, logger=None):
        self.client = client
        self.logger = logger or default_logger

    def get_pull_request(self, repo_path: str, pr_number: int) -> dict:
        """Fetch full PR details for a given PR number."""
        self.logger.info(f"Fetching PR details for {repo_path} PR #{pr_number}")
        response = self.client.request(
            "GET", f"repos/{repo_path}/pulls/{pr_number}"
        )
        return response.json()

    def get_pulls(self, repo_path: str, since: str, state: str = "all", merged_only: bool = False) -> list[dict]:
        """
        Fetch the PRs in state (open, closed or all) updated after since, or with merged_only just those merged
        after since. Gitea doesn't have search API, so list PRs most recently updated first and filter.
        """
        self.logger.info(f"Fetching {state} PRs for {repo_path}, updated after {since}")

        since_dt = dt.fromisoformat(since.replace('Z', '+00:00'))
        page = 1
        results = []

        # Gitea pages with limit/page (it ignores per_page). Its page cap
        # is configurable, so only an empty page ends the loop.
        while True:
            response = self.client.request(
                "GET", f"repos/{repo_path}/pulls",
                params={"state": state, "sort": "recentupdate", "limit": GITEA_PAGE_SIZE, "page": page}
            )
            items = response.json()
            self.logger.info(f"Fetched {len(items)} {state} PRs from Gitea for repository {repo_path} (page {page})")

            for item in items:
                # updated_at is never before merged_at, so nothing older can be newly merged
                if dt.fromisoformat(item["updated_at"].replace('Z', '+00:00')) <= since_dt:
                    return results
                if not merged_only or (
                    item["merged_at"] and dt.fromisoformat(item["merged_at"].replace('Z', '+00:00')) > since_dt
                ):
                    results.append(item)

            if not items:
                return results

            page += 1

    def get_pull_request_files(self, repo_path: str, pr_number: int):
        """Fetch files changed in a PR."""
        self.logger.info(f"fetching pull request files for {repo_path} PR #{pr_number}")

        page = 1
        files = []
        while True:
            response = self.client.request(
                "GET",
                f"repos/{repo_path}/pulls/{pr_number}/files",
                params={"page": page, "limit": GITEA_PAGE_SIZE}
            )
            items = response.json()
            self.logger.info(f"Fetched {len(items)} files from Gitea for PR #{pr_number} (page {page})")
            files.extend(items)

            if not items:
                return files

            page += 1

    def get_file_contents(self, repo_path: str, file_path: str, ref: str) -> str:
        """Fetch file contents at a given ref."""
        self.logger.info(f"Fetching file {file_path} from {repo_path} at {ref}")
        response = self.client.request(
            "GET",
            f"repos/{repo_path}/contents/{file_path}",
            params={"ref": ref}
        )
        data = response.json()
        if "content" in data:
            return base64.b64decode(data["content"]).decode("utf-8")
        return data.get("content", "")

    def get_default_branch(self, repo_path: str) -> str:
        """The repository's default branch, the one results pull requests go into."""
        response = self.client.request("GET", f"repos/{repo_path}")
        return response.json()["default_branch"]

    def create_pull_request(
        self, repo_path: str, head_branch: str, base_branch: str, title: str, body: str
    ) -> dict:
        """Create a pull request from head_branch into base_branch."""
        self.logger.info(f"Creating PR {head_branch} -> {base_branch} in {repo_path}")
        response = self.client.request(
            "POST",
            f"repos/{repo_path}/pulls",
            json={"title": title, "body": body, "head": head_branch, "base": base_branch},
        )
        return response.json()

    # fncli merges the results pull requests with this, with the same signature as GithubAPI's.

    def merge_pull_request(self, repo_path: str, pr_number: int) -> None:
        """Merge the pull request with a merge commit. Retries on 405 (mergeability computing)."""
        self.logger.info(f"Merging PR #{pr_number} in {repo_path}")
        max_attempts = 10
        for attempt in range(1, max_attempts + 1):
            try:
                self.client.request(
                    "POST", f"repos/{repo_path}/pulls/{pr_number}/merge", json={"Do": "merge"}
                )
                return
            except requests.HTTPError as e:
                if e.response.status_code != 405 or attempt == max_attempts:
                    raise
                self.logger.info(f"Merge returned 405, retrying (attempt {attempt}/{max_attempts})")
                time.sleep(3)
