import logging
from http import HTTPStatus

from app.utils import BackendSession
from app.models import TriggerRepository, PullRequest, Project, Task, Dataset

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

    def get_projects(self) -> list[Project]:
        """Get all projects, automatically handling pagination"""
        self.logger.info("Fetching projects")
        projects = []
        page = 1
        while True:
            response = self.session.get("/projects", params={"page": page, "per_page": 100})
            data = response.json()
            projects.extend(Project(**project) for project in data["items"])
            if page >= data["pages"]:
                return projects
            page += 1

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

    def get_pull_requests(self, repo_id: int, state: str) -> list[PullRequest]:
        """Get all pull requests of a repository in a state, automatically handling pagination"""
        self.logger.info(f"Fetching all {state} pull requests for repo {repo_id}")
        all_prs = []
        page = 1
        per_page = 100

        while True:
            params = {"state": state, "page": page, "per_page": per_page}
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

    def create_task_for_pull_request(self, repo_id: int, number: int, payload: dict) -> tuple[Task, bool]:
        """
        Validate the spec of a pull request and create its task, marking the PR YIELDED.
        Returns the task and whether it was created (False: the PR already had one).
        """
        self.logger.info(f"Creating task for PR #{number} in repo {repo_id}")
        response = self.session.post(
            f"/trigger_repositories/{repo_id}/pull_requests/{number}/task",
            json={"payload": payload},
        )
        return Task(**response.json()), response.status_code == HTTPStatus.CREATED

    def get_tasks(self, status: str, project_id: int) -> list[Task]:
        """Get all tasks of a project in a status, automatically handling pagination"""
        self.logger.info(f"Fetching {status} tasks of project {project_id}")
        tasks = []
        page = 1
        while True:
            params = {"status": status, "project_id": project_id, "page": page, "per_page": 100}
            response = self.session.get("/tasks", params=params)
            data = response.json()
            tasks.extend(Task(**task) for task in data["tasks"])
            if page >= data["pages"]:
                return tasks
            page += 1

    def patch_task(self, task_id: int, data: dict) -> Task:
        """Update task"""
        self.logger.info(f"Updating task {task_id}")
        response = self.session.patch(f"/tasks/{task_id}", json=data)
        return Task(**response.json())

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
        secret_label: str,
        read_schema: str,
        db_type: str,
    ) -> Dataset:
        """Create a dataset"""
        self.logger.info(f"Creating dataset {name}")
        data = {
            "name": name,
            "host": host,
            "port": port,
            "secret_label": secret_label,
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
        secret_label: str,
        watch_dir: str,
        base_branch: str,
        project_id: int,
        initial_cursor: str | None = None,
    ) -> TriggerRepository:
        """Create a repository"""
        self.logger.info(f"Creating repository {uri}")
        data = {
            "uri": uri,
            "provider": provider,
            "api_uri": api_uri,
            "secret_label": secret_label,
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
