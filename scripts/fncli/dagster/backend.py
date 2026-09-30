import logging
from urllib.parse import urlparse

from .utils import BackendSession
from .models import TriggerRepository, PullRequest, TaskRequest, Dataset, Registry, Request, Project

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
        payload: dict,
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
            "payload": payload,
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

    def create_task_request(
        self,
        repo_id: int,
        number: int,
        payload: dict,
    ) -> TaskRequest:
        """Create the task request for a pull request"""
        self.logger.info(f"Creating task request for PR #{number} in repo {repo_id}")
        response = self.session.post(
            f"/trigger_repositories/{repo_id}/pull_requests/{number}/task_request",
            json={"payload": payload},
        )
        return TaskRequest(**response.json())

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
        k8s_secret_name: str,
        read_schema: str,
        db_type: str,
    ) -> Dataset:
        """Create a dataset"""
        self.logger.info(f"Creating dataset {name}")
        data = {
            "name": name,
            "host": host,
            "port": port,
            "k8s_secret_name": k8s_secret_name,
            "read_schema": read_schema,
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
        provider: str,
        api_uri: str,
        k8s_secret_name: str,
        watch_dir: str,
        base_branch: str,
        project_id: int,
        repo_path: str,
        initial_cursor: str | None = None,
    ) -> TriggerRepository:
        """Create a repository"""
        self.logger.info(f"Creating repository {uri}")
        data = {
            "uri": uri,
            "provider": provider,
            "api_uri": api_uri,
            "k8s_secret_name": k8s_secret_name,
            "watch_dir": watch_dir,
            "base_branch": base_branch,
            "initial_cursor": initial_cursor,
            "project_id": project_id,
            "repo_path": repo_path,
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

    def get_projects(self) -> list[Project]:
        """Get all projects"""
        self.logger.info("Fetching projects")
        response = self.session.get("/projects")
        return [Project(**p) for p in response.json()["items"]]

    def get_or_create_project(
        self, name: str, description: str | None = None, enabled: bool = False
    ) -> Project:
        """Reuse the project of that name if there is one, else create it with enabled"""
        for project in self.get_projects():
            if project.name == name:
                self.logger.info(f"Reusing existing project {name} ({project.id})")
                return project

        self.logger.info(f"Creating project {name}")
        data = {"name": name, "description": description, "enabled": enabled}
        response = self.session.post("/projects", json=data)
        return Project(**self.session.get(f"/projects/{response.json()['id']}").json())

    def get_project_healthcheck(self, project_id: int) -> dict:
        """Whether the project's trigger repositories can be reached with their tokens"""
        self.logger.info(f"Checking health of project {project_id}")
        return self.session.get(f"/projects/{project_id}/healthcheck").json()

    def patch_project(self, project_id: int, data: dict) -> Project:
        """Update project"""
        self.logger.info(f"Updating project {project_id}")
        response = self.session.patch(f"/projects/{project_id}", json=data)
        return Project(**response.json())

    def get_k8s_secret(self, project_id: int, name: str) -> dict | None:
        """The project's secret with that project-local name, if there is one"""
        response = self.session.get("/k8s_secrets", params={"project_id": project_id})
        return next((secret for secret in response.json() if secret["name"] == name), None)

    def upsert_k8s_secret(self, project_id: int, name: str, values: dict[str, str]) -> dict:
        """
        The backend keeps only the name, so a re-run rotates the values in the cluster.
        Returns the secret, whose k8s_name is what it is called in the cluster.
        """
        existing = self.get_k8s_secret(project_id, name)
        if existing:
            self.logger.info(f"Updating k8s secret {name} of project {project_id}")
            response = self.session.patch(
                f"/k8s_secrets/{existing['id']}", json={"values": values}
            )
        else:
            self.logger.info(f"Creating k8s secret {name} in project {project_id}")
            response = self.session.post(
                "/k8s_secrets", json={"project_id": project_id, "name": name, "values": values}
            )
        return response.json()

    def get_or_create_repository(self, uri: str, project_id: int, **kwargs) -> TriggerRepository:
        """Reuse the project's repository with that uri if there is one, else create it from kwargs"""
        # The backend stores the host and path only, with the scheme stripped
        parsed = urlparse(uri)
        stored_uri = (parsed.netloc + parsed.path).lower().rstrip("/")
        for repo in self.get_repositories():
            if repo.project_id == project_id and repo.uri == stored_uri:
                self.logger.info(f"Reusing existing repository {repo.uri} ({repo.id})")
                return repo
        return self.create_repository(uri=uri, project_id=project_id, **kwargs)
