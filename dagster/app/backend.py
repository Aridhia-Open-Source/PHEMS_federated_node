import logging
from http import HTTPStatus

from app.utils import BackendSession
from app.models import (
    ProjectTriggerRepository, TriggerRepository, PullRequestTrigger, Project, ProjectResultsRepository, Task,
    PullRequestResult, Dataset, ProjectDataset
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

    def get_repositories(self, active_only: bool = False) -> list[ProjectTriggerRepository]:
        """Get every project's trigger repository assignments, optionally only the active ones (enabled and not revoked)"""
        self.logger.info("Fetching repositories")
        if active_only:
            response = self.session.get("/project_trigger_repositories", params={"active": "true"})
        else:
            response = self.session.get("/project_trigger_repositories")
        repos = response.json()
        return [ProjectTriggerRepository(**repo) for repo in repos]

    def get_repository(self, project_id: int, repo_id: int) -> ProjectTriggerRepository:
        """Get a project's trigger repository assignment"""
        self.logger.info(f"Fetching repository {repo_id} of project {project_id}")
        response = self.session.get(f"/projects/{project_id}/trigger_repositories/{repo_id}")
        return ProjectTriggerRepository(**response.json())

    def patch_repository(self, project_id: int, repo_id: int, data: dict) -> ProjectTriggerRepository:
        """Update a project's trigger repository assignment"""
        self.logger.info(f"Updating repository {repo_id} of project {project_id}")
        response = self.session.patch(f"/projects/{project_id}/trigger_repositories/{repo_id}", json=data)
        return ProjectTriggerRepository(**response.json())

    def get_pull_requests(self, project_id: int, repo_id: int, state: str) -> list[PullRequestTrigger]:
        """Get all pull requests of a trigger repository assignment in a state, automatically handling pagination"""
        self.logger.info(f"Fetching all {state} pull requests for repo {repo_id}")
        all_prs = []
        page = 1
        per_page = 100

        while True:
            params = {"state": state, "page": page, "per_page": per_page}
            response = self.session.get(
                f"/projects/{project_id}/trigger_repositories/{repo_id}/pull_requests",
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

        self.logger.info("Fetched all %s pull requests for repo %s", len(all_prs), repo_id)
        return all_prs

    def create_pull_request(
        self, project_id: int, project_trigger_repository_id: int, pull_request: dict
    ) -> PullRequestTrigger:
        """Ingest a pull request through an assignment: stored on its repository, fanned out to every active assignment"""
        self.logger.info(f"Creating PR #{pull_request['number']} in repo {project_trigger_repository_id}")
        response = self.session.post(
            f"/projects/{project_id}/trigger_repositories/{project_trigger_repository_id}/pull_requests",
            json=pull_request,
        )
        return PullRequestTrigger(**response.json())

    def create_pull_requests_batch(self, repository_id: int, pull_requests: list[dict]) -> dict:
        """
        Ingest up to 100 pull requests on a global trigger repository, once for all projects: the numbers
        stored and those already there.
        """
        if len(pull_requests) > 100:
            raise ValueError("Maximum 100 pull requests per batch")

        self.logger.info(f"Creating batch of {len(pull_requests)} pull requests for trigger repository {repository_id}")
        response = self.session.post(
            f"/trigger_repositories/{repository_id}/pull_requests/batch", json={"pull_requests": pull_requests}
        )
        return response.json()

    def patch_pull_request(
        self,
        project_id: int,
        repo_id: int,
        number: int,
        data: dict,
    ) -> PullRequestTrigger:
        """Update pull request"""
        self.logger.info(f"Updating PR #{number} in repo {repo_id}")
        response = self.session.patch(
            f"/projects/{project_id}/trigger_repositories/{repo_id}/pull_requests/{number}",
            json=data,
        )
        return PullRequestTrigger(**response.json())

    def create_task_for_pull_request(
        self, project_id: int, repo_id: int, number: int, spec_raw: str
    ) -> tuple[Task, bool]:
        """
        Send the spec file of a pull request: the backend keeps it, validates it and creates
        the task, marking the PR YIELDED, or rejects the PR.
        Returns the task and whether it was created (False: the PR already had one).
        """
        self.logger.info(f"Creating task for PR #{number} in repo {repo_id}")
        response = self.session.post(
            f"/projects/{project_id}/trigger_repositories/{repo_id}/pull_requests/{number}/task",
            json={"spec_raw": spec_raw},
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

    def get_task(self, task_id: int) -> Task:
        """Get single task"""
        self.logger.info(f"Fetching task {task_id}")
        response = self.session.get(f"/tasks/{task_id}")
        return Task(**response.json())

    def get_results_repository(self, project_id: int) -> ProjectResultsRepository:
        """Get the project's assignment of a results repository, active or not. A project has exactly one."""
        self.logger.info(f"Fetching the results repository of project {project_id}")
        response = self.session.get(f"/projects/{project_id}/results_repositories")
        (assignment,) = response.json()
        return ProjectResultsRepository(**assignment)

    def get_results_repository_by_id(self, project_id: int, assignment_id: int) -> ProjectResultsRepository:
        """Get a project's assignment of a results repository by its id"""
        self.logger.info(f"Fetching results repository assignment {assignment_id} of project {project_id}")
        response = self.session.get(f"/projects/{project_id}/results_repositories/{assignment_id}")
        return ProjectResultsRepository(**response.json())

    def get_task_results(self, task_id: int) -> list[PullRequestResult]:
        """Get the deliveries of a task's results"""
        self.logger.info(f"Fetching results of task {task_id}")
        response = self.session.get(f"/tasks/{task_id}/results")
        return [PullRequestResult(**result) for result in response.json()]

    def create_result(self, task_id: int, results_repository_id: int) -> PullRequestResult:
        """Create the delivery of a task's results to a project's results repository assignment, or return the existing one"""
        self.logger.info(f"Creating result of task {task_id} for results repository assignment {results_repository_id}")
        response = self.session.post(
            "/results",
            json={"task_id": task_id, "results_repository_id": results_repository_id},
        )
        return PullRequestResult(**response.json())

    def patch_result(self, result_id: int, data: dict) -> PullRequestResult:
        """Update result"""
        self.logger.info(f"Updating result {result_id}")
        response = self.session.patch(f"/results/{result_id}", json=data)
        return PullRequestResult(**response.json())

    def get_results_by_step(self, steps: list[str]) -> list[PullRequestResult]:
        """Get the results at any of the steps"""
        self.logger.info(f"Fetching results at {', '.join(steps)}")
        response = self.session.get("/results", params={"step": steps})
        return [PullRequestResult(**result) for result in response.json()]

    def get_dataset_by_name(self, name: str) -> Dataset | None:
        """Get dataset by name"""
        try:
            response = self.session.get(f"/datasets/{name}")
            return Dataset(**response.json())
        except Exception as e:  # pylint: disable=broad-exception-caught  # deliberate: any failure means "no dataset"
            self.logger.warning(f"Failed to fetch dataset {name}: {e}")
            return None

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

    def get_project_dataset(self, project_id: int, dataset_id: int) -> ProjectDataset:
        """The project's assignment of a dataset, active or not"""
        self.logger.info(f"Fetching dataset {dataset_id} of project {project_id}")
        response = self.session.get(f"/projects/{project_id}/datasets")
        for assignment in response.json():
            if assignment["dataset"]["id"] == dataset_id:
                return ProjectDataset(**assignment)
        raise LookupError(f"Dataset {dataset_id} is not assigned to project {project_id}")

    def delete_dataset(self, dataset_id: int) -> None:
        """Delete a dataset"""
        self.logger.info(f"Deleting dataset {dataset_id}")
        self.session.delete(f"/datasets/{dataset_id}")

    def create_repository(self, uri: str, provider: str, api_uri: str, secret_label: str) -> TriggerRepository:
        """Create a global trigger repository"""
        self.logger.info(f"Creating repository {uri}")
        data = {"uri": uri, "provider": provider, "api_uri": api_uri, "secret_label": secret_label}
        response = self.session.post("/trigger_repositories", json=data)
        return TriggerRepository(**response.json())

    def assign_repository(
        self,
        project_id: int,
        trigger_repository_id: int,
        watch_dir: str,
        base_branch: str,
        initial_cursor: str | None = None,
    ) -> ProjectTriggerRepository:
        """Assign a global trigger repository to a project"""
        self.logger.info(f"Assigning repository {trigger_repository_id} to project {project_id}")
        data = {
            "trigger_repository_id": trigger_repository_id,
            "watch_dir": watch_dir,
            "base_branch": base_branch,
            "initial_cursor": initial_cursor,
        }
        response = self.session.post(f"/projects/{project_id}/trigger_repositories", json=data)
        return ProjectTriggerRepository(**response.json())

    def delete_repository(self, repo_id: int) -> None:
        """Delete a repository"""
        self.session.delete(f"/trigger_repositories/{repo_id}")
