import logging
from enum import Enum

from dotenv import load_dotenv
import requests as req
from pydantic import BaseModel, ConfigDict

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


load_dotenv('.dev.env')
default_logger = logging.getLogger(__name__)


class PullRequestStatus(str, Enum):
    """Status of a pull request in the ingestion and processing pipeline."""

    UNPROCESSED = "unprocessed"
    IN_PROGRESS = "in_progress"
    SUCCESS = "success"
    FAILED = "failed"

    def __str__(self):
        return self.value


class PullRequest(BaseModel):
    """Pull Request data from backend API."""
    model_config = ConfigDict(extra="allow")

    repository_id: int
    number: int
    title: str
    raised_by: str
    merged_at: str
    spec: dict
    merge_commit_sha: str
    is_valid: bool
    status: str


class Repository(BaseModel):
    """Repository data from backend API retrieval."""

    model_config = ConfigDict(extra="allow")

    id: int
    uri: str
    path: str
    watch_dir: str
    base_branch: str
    last_merged_at: str
    pull_requests: list[PullRequest] = []


class HttpClient:
    auth_type: str = "bearer"

    SUPPORTED_AUTH_TYPES = ["bearer"]

    def __init__(self, base_uri: str, token: str = "", session=None, logger=None):
        self._base_uri = base_uri.rstrip("/")
        self._session = session or req.Session()
        self._token = token
        self.logger = logger or logging.getLogger(__name__)
        self.setup_auth()

    @property
    def token(self) -> str:
        return self._token

    @token.setter
    def token(self, value: str):
        self._token = value
        self.setup_auth()

    def setup_auth(self):
        if not self._token:
            return

        if not self.auth_type:
            raise ValueError("Auth type must be specified for setup")

        if not self.auth_type.lower() in self.SUPPORTED_AUTH_TYPES:
            raise ValueError(f"Unsupported auth type: {self.auth_type}")

        if self.auth_type.lower() == "bearer":
            self._set_bearer_token()

    def _set_bearer_token(self):
        self._session.headers.update(
            {"Authorization": f"Bearer {self._token}"}
        )

    def request(
        self,
        method: str,
        path: str,
        raise_for_status: bool = True,
        **kwargs,
    ) -> req.Response:
        url = f"{self._base_uri}/{path.lstrip('/')}"
        response = self._session.request(method, url, timeout=10, **kwargs)
        if raise_for_status:
            response.raise_for_status()
        return response

    def get(self, path: str, **kwargs) -> req.Response:
        return self.request("GET", path, **kwargs)

    def post(self, path: str, **kwargs) -> req.Response:
        return self.request("POST", path, **kwargs)

    def patch(self, path: str, **kwargs) -> req.Response:
        return self.request("PATCH", path, **kwargs)

    def put(self, path: str, **kwargs) -> req.Response:
        return self.request("PUT", path, **kwargs)

    def delete(self, path: str, **kwargs) -> req.Response:
        return self.request("DELETE", path, **kwargs)


class KeycloakHttpClient(HttpClient):
    """HTTP client with automatic Keycloak token refresh on 401"""

    def __init__(self, base_uri: str, token: str = "", session=None, logger=None):
        super().__init__(base_uri, token, session, logger)
        self._refresh_callback = None
        self._is_refreshing = False

    def set_token_refresh_callback(self, callback):
        """Set a callback to refresh the token. Callback should return new token."""
        self._refresh_callback = callback

    def request(
        self,
        method: str,
        path: str,
        raise_for_status: bool = True,
        **kwargs,
    ) -> req.Response:
        url = f"{self._base_uri}/{path.lstrip('/')}"
        response = self._session.request(method, url, timeout=10, **kwargs)

        if response.status_code == 401 and self._refresh_callback:
            try:
                # self._is_refreshing = True
                self.token = self._refresh_callback()
                response = self._session.request(method, url, timeout=10, **kwargs)
            except Exception:
                if raise_for_status:
                    response.raise_for_status()
                return response
            finally:
                self._is_refreshing = False

        if raise_for_status:
            response.raise_for_status()
        return response


class BackendClient(KeycloakHttpClient):
    def __init__(self, base_uri: str, session=None):
        super().__init__(base_uri, "", session)
        self._username = None
        self._password = None
        self.set_token_refresh_callback(self._refresh_token)

    def set_credentials(self, username: str, password: str):
        """Store credentials for automatic token refresh"""
        self._username = username
        self._password = password

    def _refresh_token(self) -> str:
        """Refresh the token using stored credentials"""
        if not self._username or not self._password:
            raise ValueError("Credentials not set. Call set_credentials() first.")

        self.logger.info(f"Refreshing token for user {self._username}")
        response = self.post(
            "/login",
            data={"username": self._username, "password": self._password},
        )
        data = response.json()
        return data.get("refresh_token") or data.get("token")


class BackendAPI:
    def __init__(self, client: BackendClient, logger=None):
        self.client = client
        self.logger = logger or default_logger

    # def login(self, username: str, password: str) -> dict:
    #     """Login and return token"""
    #     self.logger.info(f"Logging in as {username}")
    #     self.client.set_credentials(username, password)
    #     response = self.client.post(
    #         "/login",
    #         data={"username": username, "password": password},
    #     )
    #     data = response.json()
    #     token = data.get("refresh_token") or data.get("token")
    #     if token:
    #         self.client.token = token
    #     return data

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


def main():
    pass


class EnvConfig(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=None,
        case_sensitive=True,
        populate_by_name=True,
    )

    @field_validator("*", mode="after")
    @classmethod
    def validate_required(cls, v: str) -> str:
        if not v:
            raise ValueError("required")
        return v


class BackendConfig(EnvConfig):
    uri: str = Field(default="", alias="BACKEND_API_URI")
    user: str = Field(default="", alias="DAGSTER_KC_USER")
    password: str = Field(default="", alias="DAGSTER_KC_PASSWORD")


class GithubConfig(EnvConfig):
    token: str = Field(default="", alias="GH_TOKEN")
    base_uri: str = Field(
        default="https://api.github.com",
        alias="GH_API_URI",
    )


if __name__ == '__main__':
    main()
