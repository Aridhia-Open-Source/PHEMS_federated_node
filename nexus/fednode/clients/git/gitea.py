"""Gitea's REST API."""

import base64
import logging
from datetime import datetime, timedelta, timezone

from fednode.clients.git.provider import GitProvider, MintedToken, Permission, post_for_token

logger = logging.getLogger(__name__)

# Gitea caps a page at 50 by default (it ignores per_page and takes limit).
GITEA_PAGE_SIZE = 50


class GiteaClient(GitProvider):
    name = "Gitea"
    pulls_order = {"sort": "recentupdate"}
    CREDENTIAL_KEYS = frozenset({"CLIENT_ID", "CLIENT_SECRET", "REFRESH_TOKEN"})

    @classmethod
    def mint_token(
        cls, uri: str, api_uri: str, repo_path: str, credentials: dict[str, str], permission: Permission
    ) -> MintedToken:
        """
        An OAuth2 access token of the Gitea application, from its refresh token, which the answer replaces. The
        token acts as the user who authorized the application: Gitea cannot restrict it to one repository or
        permission.
        """
        now = datetime.now(tz=timezone.utc)
        body = post_for_token(
            f"{uri}/login/oauth/access_token",
            headers={"Accept": "application/json"},
            data={
                "grant_type": "refresh_token",
                "client_id": credentials["CLIENT_ID"],
                "client_secret": credentials["CLIENT_SECRET"],
                "refresh_token": credentials["REFRESH_TOKEN"],
            },
        )
        return MintedToken(
            body["access_token"], now + timedelta(seconds=body["expires_in"]), {"REFRESH_TOKEN": body["refresh_token"]}
        )

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
