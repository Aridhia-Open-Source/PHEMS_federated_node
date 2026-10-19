import logging
from http import HTTPStatus

from app.utils import BackendSession
from app.models import (
    ProjectTriggerRepository, TriggerRepository, PullRequestTrigger, Project, ProjectResultsRepository,
    ResultsRepository, Task,
    TaskTrigger, PullRequestResult, Dataset, ProjectDataset
)

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

    def get_projects(self, **filters: bool) -> list[Project]:
        """Get all projects, automatically handling pagination. Filters are the webserver's, e.g. enabled=True."""
        self.logger.info("Fetching projects")
        query = {name: str(value).lower() for name, value in filters.items()}
        projects = []
        page = 1
        while True:
            response = self.session.get("/projects", params={**query, "page": page, "per_page": 100})
            data = response.json()
            projects.extend(Project(**project) for project in data["items"])
            if page >= data["pages"]:
                return projects
            page += 1

    def get_pollable_trigger_repositories(self) -> list[TriggerRepository]:
        """
        Get the global trigger repositories to poll: enabled, on an enabled provider, with an enabled
        secret, whatever their project links. Each carries the cursor to poll from, as pr_cursor.
        """
        self.logger.info("Fetching the trigger repositories to poll")
        response = self.session.get("/global/repositories/triggers", params={"pollable": "true"})
        return [TriggerRepository(**repo) for repo in response.json()]

    def get_trigger_repository(self, repository_id: int) -> TriggerRepository:
        """Get a global trigger repository, with its current pr_cursor"""
        self.logger.info(f"Fetching trigger repository {repository_id}")
        response = self.session.get(f"/global/repositories/triggers/{repository_id}")
        return TriggerRepository(**response.json())

    def get_project_trigger_repositories(self, project_id: int, active: bool = False) -> list[ProjectTriggerRepository]:
        """Get a project's links to trigger repositories, inactive ones included unless active is set"""
        self.logger.info(f"Fetching trigger repositories of project {project_id}")
        params = {"active": "true"} if active else None
        response = self.session.get(f"/projects/{project_id}/repositories/triggers", params=params)
        return [ProjectTriggerRepository(**repo) for repo in response.json()]

    def get_project_trigger_repository(self, project_id: int, repository_id: int) -> ProjectTriggerRepository:
        """Get a project's link to a trigger repository, by the repository's id"""
        self.logger.info(f"Fetching trigger repository {repository_id} of project {project_id}")
        response = self.session.get(f"/projects/{project_id}/repositories/triggers/{repository_id}")
        return ProjectTriggerRepository(**response.json())

    def patch_project_trigger_repository(self, project_id: int, repository_id: int, data: dict) -> ProjectTriggerRepository:
        """Update a project's link to a trigger repository"""
        self.logger.info(f"Updating trigger repository {repository_id} of project {project_id}")
        response = self.session.patch(f"/projects/{project_id}/repositories/triggers/{repository_id}", json=data)
        return ProjectTriggerRepository(**response.json())

    def get_pull_requests(self, project_id: int, repository_id: int, **filters: str | int) -> list[PullRequestTrigger]:
        """
        Get all pull requests of a project's trigger repository link, automatically handling pagination.
        Filters are the webserver's, e.g. state=.
        """
        self.logger.info(f"Fetching pull requests for repo {repository_id} matching {filters}")
        all_prs = []
        page = 1
        per_page = 100

        while True:
            params = {**filters, "page": page, "per_page": per_page}
            response = self.session.get(
                f"/projects/{project_id}/repositories/triggers/{repository_id}/pull_requests",
                params=params,
            )
            data = response.json()
            items = data.get("items", [])

            if not items:
                break

            all_prs.extend([PullRequestTrigger(**pr) for pr in items])
            self.logger.info(f"Fetched page {page}: {len(items)} PRs (total: {len(all_prs)})")

            total = data.get("total") if isinstance(data, dict) else None
            if total is None or len(all_prs) >= total:
                break

            page += 1

        self.logger.info("Fetched all %s pull requests for repo %s", len(all_prs), repository_id)
        return all_prs

    def create_pull_requests_batch(self, repository_id: int, pull_requests: list[dict]) -> dict:
        """
        Ingest up to 100 pull requests on a global trigger repository, once for all projects: the numbers
        stored and those already there.
        """
        if len(pull_requests) > 100:
            raise ValueError("Maximum 100 pull requests per batch")

        self.logger.info(f"Creating batch of {len(pull_requests)} pull requests for trigger repository {repository_id}")
        response = self.session.post(
            f"/global/repositories/triggers/{repository_id}/pull_requests", json={"pull_requests": pull_requests}
        )
        return response.json()

    def patch_pull_request(
        self,
        project_id: int,
        repository_id: int,
        number: int,
        data: dict,
    ) -> PullRequestTrigger:
        """Update a project's trigger for a pull request"""
        self.logger.info(f"Updating PR #{number} in repo {repository_id}")
        response = self.session.patch(
            f"/projects/{project_id}/repositories/triggers/{repository_id}/pull_requests/{number}",
            json=data,
        )
        return PullRequestTrigger(**response.json())

    def create_task_for_pull_request(
        self, project_id: int, repository_id: int, number: int, spec_raw: str
    ) -> tuple[Task, bool]:
        """
        Send the spec file of a pull request: the backend keeps it, validates it and creates
        the task, marking the PR YIELDED, or rejects the PR.
        Returns the task and whether it was created (False: the PR already had one).
        """
        self.logger.info(f"Creating task for PR #{number} in repo {repository_id}")
        response = self.session.post(
            f"/projects/{project_id}/repositories/triggers/{repository_id}/pull_requests/{number}/task",
            json={"spec_raw": spec_raw},
        )
        return Task(**response.json()), response.status_code == HTTPStatus.CREATED

    def get_tasks(self, status: str, project_id: int) -> list[Task]:
        """Get all tasks of a project in a status, automatically handling pagination"""
        self.logger.info(f"Fetching {status} tasks of project {project_id}")
        tasks = []
        page = 1
        while True:
            params = {"status": status, "page": page, "per_page": 100}
            response = self.session.get(f"/projects/{project_id}/tasks", params=params)
            data = response.json()
            tasks.extend(Task(**task) for task in data["tasks"])
            if page >= data["pages"]:
                return tasks
            page += 1

    def patch_task(self, project_id: int, task_id: int, data: dict) -> Task:
        """Update task"""
        self.logger.info(f"Updating task {task_id}")
        response = self.session.patch(f"/projects/{project_id}/tasks/{task_id}", json=data)
        return Task(**response.json())

    def get_task(self, project_id: int, task_id: int) -> Task:
        """Get single task"""
        self.logger.info(f"Fetching task {task_id}")
        response = self.session.get(f"/projects/{project_id}/tasks/{task_id}")
        return Task(**response.json())

    def get_task_config(self, project_id: int, task_id: int) -> dict:
        """The backend's decision for a task and the facts behind it: {"outcome": "launch"|"fail", "cause", "current", "changes", "config_hash", "config_snapshot", "revoked"}. 404 if the task is not in the project."""
        self.logger.info(f"Fetching the configuration check of task {task_id}")
        response = self.session.get(f"/projects/{project_id}/tasks/{task_id}/config")
        return response.json()

    def get_task_trigger(self, project_id: int, task_id: int) -> TaskTrigger:
        """Get the pull request that yielded a task, with its trigger repository. 404 if the task has none."""
        self.logger.info(f"Fetching the trigger of task {task_id}")
        response = self.session.get(f"/projects/{project_id}/tasks/{task_id}/trigger")
        return TaskTrigger(**response.json())

    def get_global_results_repository(self, repository_id: int) -> ResultsRepository:
        """Get a global results repository. 404 once it is deleted."""
        self.logger.info(f"Fetching global results repository {repository_id}")
        response = self.session.get(f"/global/repositories/results/{repository_id}")
        return ResultsRepository(**response.json())

    def get_results_repository_by_id(self, project_id: int, repository_id: int) -> ProjectResultsRepository:
        """Get a project's link to a results repository, by the repository's id"""
        self.logger.info(f"Fetching results repository {repository_id} of project {project_id}")
        response = self.session.get(f"/projects/{project_id}/repositories/results/{repository_id}")
        return ProjectResultsRepository(**response.json())

    def get_task_results(self, project_id: int, task_id: int) -> list[PullRequestResult]:
        """Get the deliveries of a task's results"""
        self.logger.info(f"Fetching results of task {task_id}")
        response = self.session.get(f"/projects/{project_id}/tasks/{task_id}/results")
        return [PullRequestResult(**result) for result in response.json()]

    def create_result(self, project_id: int, task_id: int, results_repository_id: int) -> PullRequestResult:
        """Create the delivery of a task's results to a results repository its project is linked to, or return the existing one"""
        self.logger.info(f"Creating result of task {task_id} for results repository {results_repository_id}")
        response = self.session.post(
            f"/projects/{project_id}/results",
            json={"task_id": task_id, "results_repository_id": results_repository_id},
        )
        return PullRequestResult(**response.json())

    def patch_result(self, project_id: int, result_id: int, data: dict) -> PullRequestResult:
        """Update result"""
        self.logger.info(f"Updating result {result_id}")
        response = self.session.patch(f"/projects/{project_id}/results/{result_id}", json=data)
        return PullRequestResult(**response.json())

    def get_results_by_step(self, project_id: int, steps: list[str]) -> list[PullRequestResult]:
        """Get the project's results at any of the steps"""
        self.logger.info(f"Fetching results of project {project_id} at {', '.join(steps)}")
        response = self.session.get(f"/projects/{project_id}/results", params={"step": steps})
        return [PullRequestResult(**result) for result in response.json()]

    def get_results_by_state(self, project_id: int, state: str, active_link: bool = False) -> list[PullRequestResult]:
        """Get the project's results in a state, only those whose link to the results repository is active if active_link"""
        self.logger.info(f"Fetching {state} results of project {project_id}")
        params = {"state": state, "active_link": "true"} if active_link else {"state": state}
        response = self.session.get(f"/projects/{project_id}/results", params=params)
        return [PullRequestResult(**result) for result in response.json()]

    def create_dataset(
        self,
        name: str,
        host: str,
        port: int,
        db_type: str,
        secret_label: str,
        read_schema: str | None = None,
        write_schema: str | None = None,
    ) -> Dataset:
        """Create a global dataset. secret_label names an existing secret."""
        self.logger.info(f"Creating dataset {name}")
        data = {
            "name": name,
            "host": host,
            "port": port,
            "type": db_type,
            "secret_label": secret_label,
            "read_schema": read_schema,
            "write_schema": write_schema,
        }
        response = self.session.post("/global/datasets", json=data)
        return Dataset(**response.json())

    def get_datasets(self) -> list[Dataset]:
        """Get all datasets"""
        self.logger.info("Fetching datasets")
        response = self.session.get("/global/datasets")
        data = response.json()
        items = data.get("items", data) if isinstance(data, dict) else data
        return [Dataset(**ds) for ds in items]

    def get_dataset(self, dataset_id: int) -> Dataset:
        """Get single dataset"""
        self.logger.info(f"Fetching dataset {dataset_id}")
        response = self.session.get(f"/global/datasets/{dataset_id}")
        return Dataset(**response.json())

    def get_project_dataset(self, project_id: int, dataset_id: int) -> ProjectDataset:
        """The project's link to a dataset, active or not, by the dataset's id"""
        self.logger.info(f"Fetching dataset {dataset_id} of project {project_id}")
        response = self.session.get(f"/projects/{project_id}/datasets/{dataset_id}")
        return ProjectDataset(**response.json())

    def delete_dataset(self, dataset_id: int) -> None:
        """Delete a dataset, and with it (force) every project's link to it"""
        self.logger.info(f"Deleting dataset {dataset_id}")
        self.session.delete(f"/global/datasets/{dataset_id}", params={"force": "true"})

    def create_repository(self, provider_id: int, repo_path: str, secret_label: str) -> TriggerRepository:
        """Create a global trigger repository"""
        self.logger.info(f"Creating repository {repo_path} on provider {provider_id}")
        data = {"provider_id": provider_id, "repo_path": repo_path, "secret_label": secret_label}
        response = self.session.post("/global/repositories/triggers", json=data)
        return TriggerRepository(**response.json())

    def assign_repository(
        self,
        project_id: int,
        trigger_repository_id: int,
        watch_dir: str,
        base_branch: str,
    ) -> ProjectTriggerRepository:
        """Link a global trigger repository to a project"""
        self.logger.info(f"Assigning repository {trigger_repository_id} to project {project_id}")
        data = {"watch_dir": watch_dir, "base_branch": base_branch}
        response = self.session.put(f"/projects/{project_id}/repositories/triggers/{trigger_repository_id}", json=data)
        return ProjectTriggerRepository(**response.json())

    def delete_repository(self, repo_id: int) -> None:
        """Delete a repository, and with it (force) every project's link to it"""
        self.session.delete(f"/global/repositories/triggers/{repo_id}", params={"force": "true"})
