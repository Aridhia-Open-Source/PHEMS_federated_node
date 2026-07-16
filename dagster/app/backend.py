import logging

from app.utils import HttpClient
from app.models import Repository, PullRequest

default_logger = logging.getLogger(__name__)


class BackendClient(HttpClient):
    def __init__(self, base_uri: str, session=None):
        self._base_uri = base_uri.rstrip("/")
        self._session = session or __import__("requests").Session()
        self._token = ""

    def setup_auth(self):
        if self._token:
            self._set_bearer_token()


class BackendAPI:
    def __init__(self, client: BackendClient, logger=None):
        self.client = client
        self.logger = logger or default_logger

    def login(self, username: str, password: str) -> dict:
        """Login and return token"""
        self.logger.info(f"Logging in as {username}")
        response = self.client.post(
            "/login",
            data={"username": username, "password": password},
        )
        data = response.json()
        token = data.get("refresh_token") or data.get("token")
        if token:
            self.client.token = token
        return data

    def get_repositories(self) -> list[Repository]:
        """Get all repositories"""
        self.logger.info("Fetching repositories")
        response = self.client.get("/repositories")
        repos = response.json()
        return [Repository(**repo) for repo in repos]

    def get_repository(self, repo_id: int) -> Repository:
        """Get single repository"""
        self.logger.info(f"Fetching repository {repo_id}")
        response = self.client.get(f"/repositories/{repo_id}")
        return Repository(**response.json())

    def patch_repository(self, repo_id: int, data: dict) -> Repository:
        """Update repository"""
        self.logger.info(f"Updating repository {repo_id}")
        response = self.client.patch(f"/repositories/{repo_id}", json=data)
        return Repository(**response.json())

    def get_pull_requests(self, repo_id: int, **query_params) -> list[PullRequest]:
        """Get all pull requests for a repository, automatically handling pagination"""
        self.logger.info(f"Fetching all pull requests for repo {repo_id}")
        all_prs = []
        page = 1
        per_page = 100

        while True:
            params = {**query_params, "page": page, "per_page": per_page}
            response = self.client.get(
                f"/repositories/{repo_id}/pull_requests",
                params=params,
            )
            data = response.json()
            items = data.get("items", [])

            if not items:
                break

            all_prs.extend([PullRequest(**pr) for pr in items])
            self.logger.info(f"Fetched page {page}: {len(items)} PRs (total: {len(all_prs)})")

            # Check if there are more pages
            total = data.get("total") if isinstance(data, dict) else None
            if total is None or len(all_prs) >= total:
                break

            page += 1

        self.logger.info(f"Fetched all {len(all_prs)} pull requests for repo {repo_id}")
        return all_prs

    def create_pull_request(
        self,
        repository_id: int,
        number: int,
        title: str,
        raised_by: str,
        merged_at: str,
        merge_commit_sha: str,
        spec: dict,
        is_valid: bool,
        status: str = "unprocessed",
    ) -> PullRequest:
        """Create a pull request"""
        self.logger.info(f"Creating PR #{number} in repo {repository_id}")
        data = {
            "repository_id": repository_id,
            "number": number,
            'title': title,
            "raised_by": raised_by,
            "merged_at": merged_at,
            "merge_commit_sha": merge_commit_sha,
            "spec": spec,
            "is_valid": is_valid,
            "status": status,
        }
        response = self.client.post("/pull_requests", json=data)
        return PullRequest(**response.json())

    def create_pull_requests_batch(self, repo_id: int, pull_requests: list[dict]) -> list[PullRequest]:
        """Create multiple pull requests for a repository in one request (up to 100)"""
        if len(pull_requests) > 100:
            raise ValueError("Maximum 100 pull requests per batch")

        self.logger.info(f"Creating batch of {len(pull_requests)} pull requests for repo {repo_id}")
        response = self.client.post(f"/repositories/{repo_id}/pull_requests/batch", json=pull_requests)
        return [PullRequest(**pr) for pr in response.json()]

    def patch_pull_request(
        self,
        repo_id: int,
        number: int,
        data: dict,
    ) -> PullRequest:
        """Update pull request"""
        self.logger.info(f"Updating PR #{number} in repo {repo_id}")
        response = self.client.patch(
            f"/repositories/{repo_id}/pull_requests/{number}",
            json=data,
        )
        return PullRequest(**response.json())

    def update_pull_request_status(
        self,
        repo_id: int,
        number: int,
        status: str,
    ) -> PullRequest:
        """Update pull request"""
        self.logger.info(f"Updating PR #{number} in repo {repo_id}")
        response = self.client.patch(
            f"/repositories/{repo_id}/pull_requests/{number}",
            json={"status": status},
        )
        return PullRequest(**response.json())