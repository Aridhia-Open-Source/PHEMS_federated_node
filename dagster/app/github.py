import logging
import base64
from datetime import datetime as dt

import requests as req

from app.utils import HttpClient

GH_API_BASE_URL = "https://api.github.com"
GH_PAGE_SIZE = 100

default_logger = logging.getLogger(__name__)


class GithubClient(HttpClient):
    def __init__(self, token: str, session=None, base_uri: str = GH_API_BASE_URL):
        super().__init__(base_uri, token=token, session=session)
        self._session.headers.update({"Accept": "application/vnd.github+json"})


class GithubAPI:
    def __init__(self, client: GithubClient, logger=None):
        self.client = client
        self.logger = logger or default_logger

    def get_pull_request(self, repo_path: str, pr_number: int) -> dict:
        """Fetch full PR details for a given PR number."""
        self.logger.info(f"Fetching PR details for {repo_path} PR #{pr_number}")
        response = self.client.request(
            "GET", f"repos/{repo_path}/pulls/{pr_number}"
        )
        return response.json()

    def get_new_merged_pulls(self, repo_path: str, base_branch: str, merged_after: str) -> list[dict]:
        """
        Fetch the PRs merged into base_branch after merged_after. Lists closed PRs most recently
        updated first rather than searching: the search API allows 30 requests a minute and
        its index lags, which could let the cursor pass a PR before it is found.
        """
        self.logger.info(f"Fetching merged PRs for {repo_path}, after {merged_after}")

        merged_after_dt = dt.fromisoformat(merged_after.replace('Z', '+00:00'))
        page = 1
        results = []
        while True:
            response = self.client.request(
                "GET", f"repos/{repo_path}/pulls",
                params={
                    "state": "closed", "base": base_branch, "sort": "updated", "direction": "desc",
                    "per_page": GH_PAGE_SIZE, "page": page,
                },
            )
            items = response.json()
            self.logger.info(f"Fetched {len(items)} closed PRs from GitHub for repository {repo_path} (page {page})")

            for item in items:
                # updated_at is never before merged_at, so nothing older can be newly merged
                if dt.fromisoformat(item["updated_at"].replace('Z', '+00:00')) <= merged_after_dt:
                    return results
                if item["merged_at"] and dt.fromisoformat(item["merged_at"].replace('Z', '+00:00')) > merged_after_dt:
                    results.append(item)

            if len(items) < GH_PAGE_SIZE:
                return results
            page += 1

    def get_pull_request_files(self, repo_path: str, pr_number: int):
        self.logger.info(f"fetching pull request files for {repo_path} PR #{pr_number}")

        page = 1
        files = []
        while True:
            response = self.client.request(
                "GET", f"repos/{repo_path}/pulls/{pr_number}/files",
                params={"per_page": 100, "page": page},
            )
            page_files = response.json()
            if not page_files:
                break
            files.extend(page_files)
            page += 1
        return files

    def get_file_contents(self, repo_path: str, file_path: str, ref: str) -> str:
        response = self.client.request(
            "GET", f"repos/{repo_path}/contents/{file_path}",
            params={"ref": ref},
        )
        data = response.json()
        return base64.b64decode(data["content"]).decode("utf-8")

    def get_default_branch(self, repo_path: str) -> str:
        """The repository's default branch, the one results pull requests go into."""
        response = self.client.request("GET", f"repos/{repo_path}")
        return response.json()["default_branch"]

    def find_pull_request_by_branch(self, repo_path: str, head_branch: str, base_branch: str) -> dict | None:
        """Fetch the open or closed PR from head_branch into base_branch, or None if there is none."""
        owner = repo_path.split("/")[0]
        response = self.client.request(
            "GET", f"repos/{repo_path}/pulls",
            params={"head": f"{owner}:{head_branch}", "base": base_branch, "state": "all"},
        )
        pulls = response.json()
        return pulls[0] if pulls else None

    def create_pull_request(
        self, repo_path: str, head_branch: str, base_branch: str, title: str, body: str
    ) -> dict:
        """Create a pull request from head_branch into base_branch."""
        response = self.client.request(
            "POST",
            f"repos/{repo_path}/pulls",
            json={"title": title, "body": body, "head": head_branch, "base": base_branch},
        )
        return response.json()
