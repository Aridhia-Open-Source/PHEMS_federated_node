import logging

from app.utils import BackendSession
from app.models import Repository, PullRequest, Dataset, Registry, Request

default_logger = logging.getLogger(__name__)


class BackendAPI:
    """Backend API client. All requests auto-refresh tokens on 401/403."""

    def __init__(self, session: BackendSession, logger=None):
        self.session = session
        self.logger = logger or default_logger

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

    def get_repositories(self) -> list[Repository]:
        """Get all repositories"""
        self.logger.info("Fetching repositories")
        response = self.session.get("/repositories")
        repos = response.json()
        return [Repository(**repo) for repo in repos]

    def get_repository(self, repo_id: int) -> Repository:
        """Get single repository"""
        self.logger.info(f"Fetching repository {repo_id}")
        response = self.session.get(f"/repositories/{repo_id}")
        return Repository(**response.json())

    def patch_repository(self, repo_id: int, data: dict) -> Repository:
        """Update repository"""
        self.logger.info(f"Updating repository {repo_id}")
        response = self.session.patch(f"/repositories/{repo_id}", json=data)
        return Repository(**response.json())

    def get_pull_requests(self, repo_id: int, **query_params) -> list[PullRequest]:
        """Get all pull requests for a repository, automatically handling pagination"""
        self.logger.info(f"Fetching all pull requests for repo {repo_id}")
        all_prs = []
        page = 1
        per_page = 100

        while True:
            params = {**query_params, "page": page, "per_page": per_page}
            response = self.session.get(
                f"/repositories/{repo_id}/pull_requests",
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
        repository_id: int,
        number: int,
        title: str,
        raised_by: str,
        merged_at: str,
        merge_commit_sha: str,
        spec: dict,
        status: str = "UNKNOWN",
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
            "status": status,
        }
        response = self.session.post("/pull_requests", json=data)
        return PullRequest(**response.json())

    def create_pull_requests_batch(self, repo_id: int, pull_requests: list[dict]) -> list[PullRequest]:
        """Create multiple pull requests for a repository in one request (up to 100)"""
        if len(pull_requests) > 100:
            raise ValueError("Maximum 100 pull requests per batch")

        self.logger.info(f"Creating batch of {len(pull_requests)} pull requests for repo {repo_id}")
        response = self.session.post(f"/repositories/{repo_id}/pull_requests/batch", json=pull_requests)
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
        """Update pull request status"""
        self.logger.info(f"Updating PR #{number} status in repo {repo_id}")
        response = self.session.patch(
            f"/repositories/{repo_id}/pull_requests/{number}",
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

    def create_dataset(
        self,
        name: str,
        host: str,
        port: int,
        username: str,
        password: str,
        schema: str,
        db_type: str,
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
        }
        response = self.session.post("/datasets", json=data)
        return Dataset(**response.json())

    def get_datasets(self) -> list[Dataset]:
        """Get all datasets"""
        self.logger.info("Fetching datasets")
        response = self.session.get("/datasets")
        data = response.json()
        items = data.get("items", data) if isinstance(data, dict) else data
        return [Dataset(**ds) for ds in items]

    def get_registries(self) -> list[Registry]:
        """Get all container registries"""
        self.logger.info("Fetching registries")
        response = self.session.get("/registries")
        data = response.json()
        items = data.get("items", data) if isinstance(data, dict) else data
        return [Registry(**reg) for reg in items]

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
        dataset_id: int,
    ) -> Repository:
        """Create a repository"""
        self.logger.info(f"Creating repository {uri}")
        data = {
            "uri": uri,
            "watch_dir": watch_dir,
            "base_branch": base_branch,
            "initial_cursor": initial_cursor,
            "dataset_id": dataset_id,
        }
        response = self.session.post("/repositories", json=data)
        return Repository(**response.json())

    def delete_repository(self, repo_id: int) -> None:
        """Delete a repository"""
        self.session.delete(f"/repositories/{repo_id}")

    def create_request(
        self,
        title: str,
        description: str,
        project_name: str,
        requested_by: str,
        proj_start: str,
        proj_end: str,
        dataset_id: int,
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
            "dataset_id": dataset_id,
        }
        response = self.session.post("/requests", json=data, raise_for_status=False)
        return response

    def approve_request(self, request_id: int) -> bool:
        """Approve a Data Access Request"""
        self.logger.info(f"Approving request {request_id}")
        self.session.patch(f"/requests/{request_id}", json={"status": "approved"})
        return True
