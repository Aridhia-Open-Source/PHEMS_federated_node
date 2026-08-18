"""HTTP session and adapter classes for backend API communication."""

import logging
import time

from urllib3.util import Retry
import requests
from requests import Session
from requests.adapters import HTTPAdapter

from models import TriggerRepository, PullRequest, Dataset, Request, Project

logger = logging.getLogger(__name__)


class BaseHttpAdapter(HTTPAdapter):
    """Base HTTP adapter with default retry logic."""

    retry_limit = 3
    backoff_factor = 0.5
    default_timeout = 10
    retry_status_forcelist = {429}

    def __init__(
        self,
        base_url: str = '',
        timeout: int | None = None,
        max_retries: Retry | None = None,
        **kwargs
    ):
        self.base_url = base_url
        self.timeout = timeout or self.default_timeout
        super().__init__(**{**kwargs, 'max_retries': max_retries})

    @property
    def default_retry(self):
        return Retry(
            total=self.retry_limit,
            backoff_factor=self.backoff_factor,
            status_forcelist=self.retry_status_forcelist
        )

    def send(self, request, **kwargs):
        kwargs["timeout"] = kwargs.pop("timeout", self.timeout)
        return super().send(request, **kwargs)


class BaseSession(Session):
    """Base session with base URL support."""

    timeout = 10
    default_raise_for_status = True

    @property
    def base_url(self) -> str:
        return self.adapter.base_url

    def __init__(
        self,
        adapter: BaseHttpAdapter,
        *args,
        **kwargs
    ):
        super().__init__(*args, **kwargs)
        self.mount_adapters(adapter)

    def send(self, request, **kwargs):
        kwargs["timeout"] = kwargs.pop("timeout", self.timeout)
        return super().send(request, **kwargs)

    def request(self, method, url, raise_for_status: bool | None = None, **kwargs):
        full_url = f"{self.base_url}/{url.lstrip('/')}"
        response = super().request(method, full_url, **kwargs)
        return self.handle_response(response, raise_for_status)

    def handle_response(self, response, raise_for_status: bool | None = None):
        if raise_for_status is None:
            raise_for_status = self.default_raise_for_status
        if raise_for_status:
            response.raise_for_status()
        return response

    def mount_adapters(self, adapter):
        self.adapter = adapter
        self.mount("http://", self.adapter)
        self.mount("https://", self.adapter)


class OAuthAdapter(BaseHttpAdapter):
    """HTTP adapter that handles login and automatic token refresh on 401/403/429."""

    oauth_status_codes = {401, 403, 429}
    oauth_backoff_factor = 0.5
    oauth_retry_limit = 1

    def __init__(self, base_url: str, username: str, password: str):
        super().__init__(base_url=base_url)
        self.username = username
        self.password = password
        self._access_token = None

    @property
    def access_token(self):
        if not self._access_token:
            self.refresh_tokens()
        return self._access_token

    @access_token.setter
    def access_token(self, value):
        self._access_token = value

    def refresh_tokens(self):
        """Refresh tokens"""
        raise NotImplementedError

    def send(self, request, **kwargs):
        if self.access_token:
            request.headers["Authorization"] = f"Bearer {self.access_token}"

        timeout = kwargs.pop("timeout", self.timeout)
        response = super().send(request, timeout=timeout, **kwargs)
        if response.status_code not in self.oauth_status_codes:
            return response

        return self._retry_on_auth_failure(request, response, timeout, **kwargs)

    def _send_request(self, request, **kwargs):
        """Send request without OAuth refresh logic."""
        kwargs['timeout'] = kwargs.get("timeout", self.timeout)
        return super().send(request, **kwargs)

    def _retry_on_auth_failure(self, request, response, timeout, **kwargs):
        for attempt in range(1, self.oauth_retry_limit + 1):
            backoff = self.oauth_backoff_factor * (2 ** (attempt - 1))
            self._log_refresh_error(response, attempt, backoff)
            time.sleep(backoff)
            self.refresh_tokens()

            request.headers["Authorization"] = f"Bearer {self.access_token}"
            response = super().send(request, timeout=timeout, **kwargs)
            if response.status_code not in self.oauth_status_codes:
                response.raise_for_status()

        return response

    def _log_refresh_error(self, response, attempt, backoff):
        tpl = "Auth failure (%d), refresh token retry %d/%d in %.1fs"
        logger.error(tpl, response.status_code, attempt, self.oauth_retry_limit, backoff)


class BackendAdapter(OAuthAdapter):
    """Adapter for backend API authentication."""

    def login(self):
        """Exchange username/password for token."""
        response = requests.post(
            f"{self.base_url}/login",
            data={'username': self.username, 'password': self.password},
            headers={'Accept': 'application/json'},
            timeout=self.timeout
        )
        response.raise_for_status()
        return response

    def refresh_tokens(self):
        """Refresh token by logging in again."""
        response = self.login()
        data = response.json()
        self.access_token = data['token']


class BackendSession(BaseSession):
    """Session for backend API with automatic token refresh."""


class BackendAPI:
    """Backend API client. All requests auto-refresh tokens on 401/403."""

    def __init__(self, session: BackendSession, api_logger=None):
        self.session = session
        self.logger = api_logger or logger

    def login(self, username: str, password: str) -> dict:
        """Login and return token"""
        self.logger.info(f"Logging in as {username}")
        response = self.session.post(
            "/login",
            data={"username": username, "password": password},
        )
        data = response.json()
        token = data.get("refresh_token") or data.get("token")
        if token:
            self.session.adapter.access_token = token
        return data

    def get_repositories(self) -> list[TriggerRepository]:
        """Get all repositories"""
        self.logger.info("Fetching repositories")
        response = self.session.get("/trigger_repositories")
        repos = response.json()
        return [TriggerRepository(**repo) for repo in repos]

    def get_repository(self, repo_id: int) -> TriggerRepository:
        """Get single repository"""
        self.logger.info(f"Fetching repository {repo_id}")
        response = self.session.get(f"/trigger_repositories/{repo_id}")
        return TriggerRepository(**response.json())

    def patch_repository(self, repo_id: int, data: dict) -> TriggerRepository:
        """Update repository"""
        self.logger.info(f"Updating repository {repo_id}")
        response = self.session.patch(f"/trigger_repositories/{repo_id}", json=data)
        return TriggerRepository(**response.json())

    def get_pull_requests(self, repo_id: int, **query_params) -> list[PullRequest]:
        """Get all pull requests for a repository, automatically handling pagination"""
        self.logger.info(f"Fetching all pull requests for repo {repo_id}")
        all_prs = []
        page = 1
        per_page = 100
        response = None

        while True:
            params = {**query_params, "page": page, "per_page": per_page}
            response = self.session.get(
                f"/trigger_repositories/{repo_id}/pull_requests",
                params=params,
            )
            data = response.json()
            items = data.get("items", [])

            if not items:
                break

            all_prs.extend([PullRequest(**pr) for pr in items])
            self.logger.info(f"Fetched page {page}: {len(items)} PRs (total: {len(all_prs)})")

            total = data.get("total") if isinstance(data, dict) else None
            if total is None or len(all_prs) >= total:
                break

            page += 1

        self.logger.info(f"Fetched all {len(all_prs)} pull requests for repo {repo_id}")
        return all_prs

    def create_pull_request(
        self,
        trigger_repository_id: int,
        number: int,
        title: str,
        raised_by: str,
        merged_at: str,
        merge_commit_sha: str,
        spec: dict,
        status: str = "UNKNOWN",
    ) -> PullRequest:
        """Create a pull request"""
        self.logger.info(f"Creating PR #{number} in repo {trigger_repository_id}")
        data = {
            "trigger_repository_id": trigger_repository_id,
            "number": number,
            'title': title,
            "raised_by": raised_by,
            "merged_at": merged_at,
            "merge_commit_sha": merge_commit_sha,
            "spec": spec,
            "status": status,
        }
        response = self.session.post("/trigger_repositories/pull_requests", json=data)
        return PullRequest(**response.json())

    def create_pull_requests_batch(self, repo_id: int, pull_requests: list[dict]) -> list[PullRequest]:
        """Create multiple pull requests for a repository in one request (up to 100)"""
        if len(pull_requests) > 100:
            raise ValueError("Maximum 100 pull requests per batch")

        self.logger.info(f"Creating batch of {len(pull_requests)} pull requests for repo {repo_id}")
        response = self.session.post(f"/trigger_repositories/{repo_id}/pull_requests/batch", json=pull_requests)
        return [PullRequest(**pr) for pr in response.json()]

    def patch_pull_request(
        self,
        repo_id: int,
        number: int,
        data: dict,
    ) -> PullRequest:
        """Update pull request"""
        self.logger.info(f"Updating PR #{number} in repo {repo_id}")
        response = self.session.patch(
            f"/trigger_repositories/{repo_id}/pull_requests/{number}",
            json=data,
        )
        return PullRequest(**response.json())

    def update_pull_request_status(
        self,
        repo_id: int,
        number: int,
        status: str,
    ) -> PullRequest:
        """Update pull request status"""
        self.logger.info(f"Updating PR #{number} status in repo {repo_id}")
        response = self.session.patch(
            f"/trigger_repositories/{repo_id}/pull_requests/{number}",
            json={"status": status},
        )
        return PullRequest(**response.json())

    def get_dataset_by_name(self, name: str) -> Dataset | None:
        """Get dataset by name"""
        try:
            response = self.session.get(f"/datasets/{name}")
            return Dataset(**response.json())
        except Exception as e:
            self.logger.warning(f"Failed to fetch dataset {name}: {e}")
            return None

    def get_projects(self) -> list[Project]:
        """Get all projects"""
        self.logger.info("Fetching projects")
        response = self.session.get("/projects")
        data = response.json()
        items = data.get("items", data) if isinstance(data, dict) else data
        return [Project(**p) for p in items]

    def get_or_create_project(self, name: str, description: str | None = None) -> Project:
        """
        A project owns the datasets, so one has to exist before a dataset can be created.
        Re-running the seed should reuse the project rather than fail on the name clash.
        """
        for project in self.get_projects():
            if project.name == name:
                self.logger.info(f"Reusing existing project {name} ({project.id})")
                return project

        self.logger.info(f"Creating project {name}")
        data = {"name": name}
        if description:
            data["description"] = description
        response = self.session.post("/projects", json=data)
        return self.get_project(response.json()["id"])

    def get_project(self, project_id: int) -> Project:
        """Get single project"""
        response = self.session.get(f"/projects/{project_id}")
        return Project(**response.json())

    def create_dataset(
        self,
        name: str,
        host: str,
        port: int,
        username: str,
        password: str,
        schema: str,
        db_type: str,
        project_id: int,
        schema_write: str | None = None,
    ) -> Dataset:
        """Create a dataset"""
        self.logger.info(f"Creating dataset {name}")
        data = {
            "name": name,
            "host": host,
            "port": port,
            "username": username,
            "password": password,
            "schema": schema,
            "type": db_type,
            "project_id": project_id,
        }
        if schema_write:
            data["schema_write"] = schema_write
        response = self.session.post("/datasets", json=data)
        return Dataset(**response.json())

    def get_datasets(self) -> list[Dataset]:
        """Get all datasets"""
        self.logger.info("Fetching datasets")
        response = self.session.get("/datasets")
        data = response.json()
        items = data.get("items", data) if isinstance(data, dict) else data
        return [Dataset(**ds) for ds in items]

    def get_dataset(self, dataset_id: int) -> Dataset:
        """Get single dataset"""
        self.logger.info(f"Fetching dataset {dataset_id}")
        response = self.session.get(f"/datasets/{dataset_id}")
        return Dataset(**response.json())

    def delete_dataset(self, dataset_id: int) -> None:
        """Delete a dataset"""
        self.logger.info(f"Deleting dataset {dataset_id}")
        self.session.delete(f"/datasets/{dataset_id}")

    def create_repository(
        self,
        uri: str,
        watch_dir: str,
        base_branch: str,
        initial_cursor: str,
        project_id: int,
    ) -> TriggerRepository:
        """Create a repository"""
        self.logger.info(f"Creating repository {uri}")
        data = {
            "uri": uri,
            "watch_dir": watch_dir,
            "base_branch": base_branch,
            "initial_cursor": initial_cursor,
            "project_id": project_id,
        }
        response = self.session.post("/trigger_repositories", json=data)
        return TriggerRepository(**response.json())

    def delete_repository(self, repo_id: int) -> None:
        """Delete a repository"""
        self.session.delete(f"/trigger_repositories/{repo_id}")

    def create_request(
        self,
        title: str,
        description: str,
        project_name: str,
        requested_by: str,
        proj_start: str,
        proj_end: str,
        project_id: int,
    ) -> Request:
        """Create a Data Access Request"""
        self.logger.info(f"Creating request {title}")
        data = {
            "title": title,
            "description": description,
            "project_name": project_name,
            "requested_by": requested_by,
            "proj_start": proj_start,
            "proj_end": proj_end,
            "project_id": project_id,
        }
        response = self.session.post("/requests", json=data, raise_for_status=False)
        return response
        # return Request(**response.json())

    def approve_request(self, request_id: int) -> bool:
        """Approve a Data Access Request"""
        self.logger.info(f"Approving request {request_id}")
        self.session.patch(f"/requests/{request_id}", json={"status": "approved"})
        return True
