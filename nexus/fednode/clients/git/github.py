"""GitHub's REST API, and GitHub Enterprise's on its own base URI."""

import base64
import logging
from datetime import datetime, timedelta, timezone

import jwt

from fednode.clients.git.provider import GitProvider, MintedToken, Permission, post_for_token
from fednode.http import DEFAULT_TIMEOUT

logger = logging.getLogger(__name__)

GH_API_BASE_URL = "https://api.github.com"
GH_PAGE_SIZE = 100
# GitHub takes an App JWT of at most 10 minutes; issued a minute in the past for clock drift
JWT_LIFETIME = timedelta(minutes=9)
JWT_BACKDATE = timedelta(seconds=60)


class GitHubClient(GitProvider):
    name = "GitHub"
    pulls_order = {"sort": "updated", "direction": "desc"}
    CREDENTIAL_KEYS = frozenset({"APP_ID", "INSTALLATION_ID", "PRIVATE_KEY"})

    def __init__(self, base_uri: str, token: str, session=None, timeout: tuple[float, float] = DEFAULT_TIMEOUT):
        super().__init__(base_uri, token=token, session=session, timeout=timeout)
        self._session.headers.update({"Accept": "application/vnd.github+json"})

    @classmethod
    def mint_token(
        cls, uri: str, api_uri: str, repo_path: str, credentials: dict[str, str], permission: Permission
    ) -> MintedToken:
        """An installation token of the GitHub App, restricted to the repository and permission, with GitHub's expiry."""
        now = datetime.now(tz=timezone.utc)
        app_jwt = jwt.encode(
            {"iss": credentials["APP_ID"], "iat": now - JWT_BACKDATE, "exp": now + JWT_LIFETIME},
            credentials["PRIVATE_KEY"],
            algorithm="RS256",
        )
        body = post_for_token(
            f"{api_uri.rstrip('/')}/app/installations/{credentials['INSTALLATION_ID']}/access_tokens",
            headers={"Authorization": f"Bearer {app_jwt}", "Accept": "application/vnd.github+json"},
            # GitHub takes the repository's name, not owner/name
            json={
                "repositories": [repo_path.split("/")[1]],
                "permissions": {"contents": permission, "pull_requests": permission},
            },
        )
        return MintedToken(body["token"], datetime.fromisoformat(body["expires_at"]))

    def page_params(self, page: int) -> dict:
        return {"per_page": GH_PAGE_SIZE, "page": page}

    def is_last_page(self, items: list[dict]) -> bool:
        return len(items) < GH_PAGE_SIZE

    def get_file_contents(self, repo_path: str, file_path: str, ref: str) -> str:
        data = self.request("GET", f"repos/{repo_path}/contents/{file_path}", params={"ref": ref}).json()
        return base64.b64decode(data["content"]).decode("utf-8")

    def create_branch(self, repo_path: str, new_branch: str, old_branch: str) -> None:
        logger.info(f"Creating branch {new_branch} from {old_branch} in {repo_path}")
        ref = self.request("GET", f"repos/{repo_path}/git/ref/heads/{old_branch}").json()
        self.request(
            "POST", f"repos/{repo_path}/git/refs",
            json={"ref": f"refs/heads/{new_branch}", "sha": ref["object"]["sha"]},
        )

    def create_file(self, repo_path: str, file_path: str, content: str, message: str, branch: str):
        """Commit a NEW file to branch. Fails if the file exists: modifying needs its sha."""
        logger.info(f"Committing {file_path} to {branch} in {repo_path}")
        self.request(
            "PUT", f"repos/{repo_path}/contents/{file_path}",
            json={
                "content": base64.b64encode(content.encode()).decode(),
                "message": message,
                "branch": branch,
            },
        )

    def _merge(self, repo_path: str, pr_number: int) -> None:
        self.request("PUT", f"repos/{repo_path}/pulls/{pr_number}/merge", json={"merge_method": "merge"})
