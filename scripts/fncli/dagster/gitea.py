import base64
import logging
import time
from datetime import datetime as dt

from fncli.dagster.utils import HttpClient

GITEA_API_BASE_URL = "http://gitea.fn.svc:3000/api/v1"
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


class GiteaAdminClient(HttpClient):
    """Admin calls authenticate as the admin user rather than with an access token."""

    def __init__(self, username: str, password: str, session=None, base_uri: str = GITEA_API_BASE_URL):
        super().__init__(base_uri, session=session)
        self._session.auth = (username, password)


class GiteaAdminAPI:
    def __init__(self, client: GiteaAdminClient, username: str, logger=None):
        self.client = client
        self.username = username
        self.logger = logger or default_logger

    def get_or_create_repo(self, name: str, description: str = "") -> dict:
        """Fetch the admin user's repo, creating it (with an initial commit) if missing."""
        response = self.client.request(
            "GET", f"repos/{self.username}/{name}", raise_for_status=False
        )
        if response.status_code != 404:
            self.logger.info(f"Repo {name} already exists")
        else:
            self.logger.info(f"Creating repo {name}")
            response = self.client.request(
                "POST",
                "user/repos",
                json={"name": name, "description": description, "private": False, "auto_init": True},
            )
        response.raise_for_status()
        return response.json()

    def delete_repo(self, name: str) -> bool:
        """Delete the admin user's repo. Returns whether there was one to delete."""
        response = self.client.request(
            "DELETE", f"repos/{self.username}/{name}", raise_for_status=False
        )
        if response.status_code == 404:
            return False
        response.raise_for_status()
        return True

    def delete_token(self, name: str) -> bool:
        """Delete the admin user's token. Returns whether there was one to delete."""
        response = self.client.request(
            "DELETE", f"users/{self.username}/tokens/{name}", raise_for_status=False
        )
        if response.status_code == 404:
            return False
        response.raise_for_status()
        return True

    def replace_token(self, name: str, scopes: list[str]) -> str:
        """
        Gitea only returns a token's value when it is created, so replace any previous
        token under the same name rather than pile up new ones on every run.
        """
        self.delete_token(name)
        response = self.client.request(
            "POST", f"users/{self.username}/tokens", json={"name": name, "scopes": scopes}
        )
        return response.json()["sha1"]

    def create_branch(self, repo_path: str, new_branch: str, old_branch: str) -> None:
        """Create new_branch from the head of old_branch."""
        self.logger.info(f"Creating branch {new_branch} from {old_branch} in {repo_path}")
        self.client.request(
            "POST",
            f"repos/{repo_path}/branches",
            json={"new_branch_name": new_branch, "old_branch_name": old_branch},
        )

    def create_file(self, repo_path: str, file_path: str, content: str, message: str, branch: str):
        """Commit a NEW file to branch. Fails if the file exists: modifying is not supported."""
        self.logger.info(f"Committing {file_path} to {branch} in {repo_path}")
        self.client.request(
            "POST",
            f"repos/{repo_path}/contents/{file_path}",
            json={
                "content": base64.b64encode(content.encode()).decode(),
                "message": message,
                "branch": branch,
            },
        )

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
            except Exception as e:
                if hasattr(e, 'response') and hasattr(e.response, 'status_code') and e.response.status_code == 405:
                    if attempt < max_attempts:
                        self.logger.info(f"Merge returned 405, retrying (attempt {attempt}/{max_attempts})")
                        time.sleep(3)
                    else:
                        self.logger.error(f"Merge failed with 405 after {max_attempts} attempts")
                        raise
                else:
                    raise
