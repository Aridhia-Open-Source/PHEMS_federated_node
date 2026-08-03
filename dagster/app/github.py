import logging
import base64
import requests as req

from app.utils import HttpClient

GH_API_BASE_URL = "https://api.github.com"

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
        self.logger.info(f"Fetching merged PRs for {repo_path}, after {merged_after}")

        page = 1
        per_page = 100
        results = []
        while True:
            query = (
                f"repo:{repo_path} "
                f"is:pr is:merged "
                f"base:{base_branch} "
                f"merged:>{merged_after}"
            )
            response = self.client.request(
                "GET", "search/issues",
                params={"q": query, "per_page": per_page, "page": page},
            )
            items = response.json().get("items")
            self.logger.info(f"Fetched {len(items)} PRs from GitHub for repository {repo_path} (page {page})")
            results.extend(items)
            page += 1

            if not items:
                return results

    def filter_prs_by_watch_dir(self, prs: list[dict], watch_dir: str, file_ext: str = "") -> list[dict]:
        results = []
        for pr in prs:
            pr_number = pr["number"]
            repo_path = pr["base"]["repo"]["full_name"]
            self.logger.info(f"Checking PR #{pr_number} files")
            pr = self.client.request("GET", f"repos/{repo_path}/pulls/{pr_number}").json()
            pr_files = self.get_pull_request_files(repo_path, pr_number)
            pr["watched_files"] = self._filter_watched_dir(pr_files, watch_dir, file_ext)

            if pr["watched_files"]:
                self.logger.info(f"Found new PR #{pr_number} for repo {repo_path} with watched files: {pr['watched_files']}")
                results.append(pr)
            else:
                self.logger.info(f"Skipped new PR #{pr_number} for repo {repo_path} no new files in {watch_dir}")

        return results

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

    @staticmethod
    def _filter_watched_dir(files, watch_dir: str, file_ext: str = ""):
        return [
            f["filename"] for f in files
            if f["filename"].startswith(watch_dir)
            and f["status"] == "added"
            and f["filename"].endswith(file_ext)
        ]

    def get_file_contents(self, repo_path: str, file_path: str, ref: str) -> str:
        response = self.client.request(
            "GET", f"repos/{repo_path}/contents/{file_path}",
            params={"ref": ref},
        )
        data = response.json()
        return base64.b64decode(data["content"]).decode("utf-8")

    def add_pull_request_comment(self, repo_path: str, pr_number: int, body: str):
        response = self.client.request(
            "POST", f"repos/{repo_path}/issues/{pr_number}/comments",
            json={"body": body},
        )
        return response.json()

    def branch_exists(self, repo_path: str, branch: str) -> bool:
        """Check if a branch exists on the remote."""
        response = self.client.request(
            "GET", f"repos/{repo_path}/branches/{branch}", raise_for_status=False
        )
        return response.status_code == 200

    def create_pull_request(
        self, repo_path: str, head: str, base: str, title: str, body: str
    ) -> str:
        """Create a pull request and return its URL."""
        response = self.client.request(
            "POST",
            f"repos/{repo_path}/pulls",
            json={"title": title, "body": body, "head": head, "base": base},
        )
        return response.json()["html_url"]
