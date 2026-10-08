import base64
import logging
from datetime import datetime as dt

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

    def get_new_merged_pulls(self, repo_path: str, base_branch: str, merged_after: str) -> list[dict]:
        """Fetch merged PRs since merged_after timestamp. Gitea doesn't have search API, so fetch and filter."""
        self.logger.info(f"Fetching merged PRs for {repo_path}, after {merged_after}")

        page = 1
        results = []

        merged_after_dt = dt.fromisoformat(merged_after.replace('Z', '+00:00')) if merged_after else None

        # Gitea pages with limit/page (it ignores per_page) and has no base filter. Its page cap
        # is configurable, so only an empty page ends the loop.
        while True:
            response = self.client.request(
                "GET", f"repos/{repo_path}/pulls",
                params={"state": "closed", "limit": GITEA_PAGE_SIZE, "page": page}
            )
            items = response.json()
            self.logger.info(f"Fetched {len(items)} closed PRs from Gitea for repository {repo_path} (page {page})")

            for item in items:
                if item["base"]["ref"] != base_branch:
                    continue
                if item.get("merged_at"):
                    merged_at = item["merged_at"]
                    if isinstance(merged_at, str):
                        merged_at_dt = dt.fromisoformat(merged_at.replace('Z', '+00:00'))
                        if merged_after_dt is None or merged_at_dt > merged_after_dt:
                            results.append(item)
                    else:
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

    def find_pull_request_by_branch(self, repo_path: str, head_branch: str, base_branch: str) -> dict | None:
        """Fetch the open or closed PR from head_branch into base_branch, or None if there is none."""
        self.logger.info(f"Looking up PR {head_branch} -> {base_branch} in {repo_path}")
        response = self.client.request(
            "GET", f"repos/{repo_path}/pulls/{base_branch}/{head_branch}", raise_for_status=False
        )
        if response.status_code == 404:
            return None
        response.raise_for_status()
        return response.json()

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
