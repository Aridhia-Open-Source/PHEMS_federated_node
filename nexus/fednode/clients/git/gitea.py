"""Gitea's REST API."""

import base64
import logging

from fednode.clients.git.provider import GitProvider

logger = logging.getLogger(__name__)

# Gitea caps a page at 50 by default (it ignores per_page and takes limit).
GITEA_PAGE_SIZE = 50


class GiteaClient(GitProvider):
    name = "Gitea"
    pulls_order = {"sort": "recentupdate"}

    def page_params(self, page: int) -> dict:
        return {"limit": GITEA_PAGE_SIZE, "page": page}

    def is_last_page(self, items: list[dict]) -> bool:
        # Gitea's page cap is configurable, so only an empty page ends the listing
        return not items

    def get_file_contents(self, repo_path: str, file_path: str, ref: str) -> str:
        logger.info(f"Fetching file {file_path} from {repo_path} at {ref}")
        data = self.request("GET", f"repos/{repo_path}/contents/{file_path}", params={"ref": ref}).json()
        if "content" in data:
            return base64.b64decode(data["content"]).decode("utf-8")
        return ""

    def create_branch(self, repo_path: str, new_branch: str, old_branch: str) -> None:
        logger.info(f"Creating branch {new_branch} from {old_branch} in {repo_path}")
        self.request(
            "POST",
            f"repos/{repo_path}/branches",
            json={"new_branch_name": new_branch, "old_branch_name": old_branch},
        )

    def create_file(self, repo_path: str, file_path: str, content: str, message: str, branch: str):
        logger.info(f"Committing {file_path} to {branch} in {repo_path}")
        self.request(
            "POST",
            f"repos/{repo_path}/contents/{file_path}",
            json={
                "content": base64.b64encode(content.encode()).decode(),
                "message": message,
                "branch": branch,
            },
        )

    def _merge(self, repo_path: str, pr_number: int) -> None:
        self.request("POST", f"repos/{repo_path}/pulls/{pr_number}/merge", json={"Do": "merge"})
