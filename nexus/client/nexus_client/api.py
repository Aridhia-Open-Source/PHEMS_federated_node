import logging
from http import HTTPStatus
from typing import Literal

from nexus_client.git_uri import normalise_repo_uri, repo_path_of
from nexus_client.http import BackendSession
from nexus_client.models import (
    GitProvider, GitToken, ProjectTriggerRepository, TriggerRepository, PullRequestTrigger, Project, ProjectResultsRepository,
    ResultsRepository, Task,
    TaskTrigger, PullRequestResult, Dataset, ProjectDataset, LaunchDecision, TaskResources
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
        """Get all projects, automatically handling pagination. Filters are nexus-api's, e.g. enabled=True."""
        self.logger.info("Fetching projects")
        query = {name: str(value).lower() for name, value in filters.items()}
        projects = []
        page = 1
        while True:
            response = self.session.get("/projects", params={**query, "page": page, "size": 100})
            data = response.json()
            projects.extend(Project(**project) for project in data["items"])
            if page >= data["pages"]:
                return projects
            page += 1

    def get_pollable_trigger_repositories(self) -> list[TriggerRepository]:
        """
        Get the global trigger repositories to poll: enabled, on an enabled provider, with an enabled
        secret, whatever their project resources. Each carries the cursor to poll from, as pr_cursor.
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
        """Get a project's trigger repositories, inactive ones included unless active is set"""
        self.logger.info(f"Fetching trigger repositories of project {project_id}")
        params = {"active": "true"} if active else None
        response = self.session.get(f"/projects/{project_id}/repositories/triggers", params=params)
        return [ProjectTriggerRepository(**repo) for repo in response.json()]

    def get_project_trigger_repository(self, project_id: int, repository_id: int) -> ProjectTriggerRepository:
        """Get a project's trigger repository, by the repository's id"""
        self.logger.info(f"Fetching trigger repository {repository_id} of project {project_id}")
        response = self.session.get(f"/projects/{project_id}/repositories/triggers/{repository_id}")
        return ProjectTriggerRepository(**response.json())

    def patch_project_trigger_repository(self, project_id: int, repository_id: int, data: dict) -> ProjectTriggerRepository:
        """Update a project's trigger repository"""
        self.logger.info(f"Updating trigger repository {repository_id} of project {project_id}")
        response = self.session.patch(f"/projects/{project_id}/repositories/triggers/{repository_id}", json=data)
        return ProjectTriggerRepository(**response.json())

    def get_pull_requests(self, project_id: int, repository_id: int, **filters: str | int) -> list[PullRequestTrigger]:
        """
        Get all pull requests of a project's trigger repository, automatically handling pagination.
        Filters are nexus-api's, e.g. state=.
        """
        self.logger.info(f"Fetching pull requests for repo {repository_id} matching {filters}")
        all_prs = []
        page = 1
        size = 100

        while True:
            params = {**filters, "page": page, "size": size}
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

    def get_tasks(self, status: str | list[str], project_enabled: bool = True) -> list[Task]:
        """
        Get the tasks of all projects in a status (or any of several), ordered by id, automatically handling
        pagination. With project_enabled, only those of enabled projects, as get_projects(enabled=True) lists them.
        """
        statuses = [status] if isinstance(status, str) else status
        self.logger.info(f"Fetching {','.join(statuses)} tasks")
        query = {"status": ",".join(statuses)}
        if project_enabled:
            query["project_enabled"] = "true"
        tasks = []
        page = 1
        while True:
            response = self.session.get("/tasks", params={**query, "page": page, "size": 100})
            data = response.json()
            tasks.extend(Task(**task) for task in data["items"])
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

    def launch_task(self, project_id: int, task_id: int) -> LaunchDecision | None:
        """
        The launcher's one call for a PENDING task. The backend decides: on "fail" it has already moved the task
        to FAILED with the cause; on "launch" it returns the task and its dataset, what the run request needs, and
        changes nothing. None when the task is no longer PENDING (409). 404 if it is not in the project.
        """
        self.logger.info(f"Launching task {task_id}")
        response = self.session.post(f"/projects/{project_id}/tasks/{task_id}/launch", raise_for_status=False)
        if response.status_code == HTTPStatus.CONFLICT:
            self.logger.info(f"Task {task_id} is no longer pending: {response.text}")
            return None
        response.raise_for_status()
        return LaunchDecision(**response.json())

    def create_task_resources(self, project_id: int, task_id: int, run_id: str) -> TaskResources:
        """
        The run calls this before it starts the task pod. The backend creates the run's Secret (the dataset's credentials,
        read by the backend and never returned) and ConfigMap (the config file) in the tasks namespace, labelled with the
        run and the task, deletes them when the task finishes, and returns their names. 409 if the run has them already.
        """
        self.logger.info(f"Creating the Secret and ConfigMap of run {run_id} of task {task_id}")
        response = self.session.post(f"/projects/{project_id}/tasks/{task_id}/runs/{run_id}/resources")
        return TaskResources(**response.json())

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
        """Get a project's results repository, by the repository's id"""
        self.logger.info(f"Fetching results repository {repository_id} of project {project_id}")
        response = self.session.get(f"/projects/{project_id}/repositories/results/{repository_id}")
        return ProjectResultsRepository(**response.json())

    def get_repository_token(
        self, kind: Literal["trigger", "results"], repository_id: int, project_id: int | None = None
    ) -> GitToken:
        """
        Get a short-lived git token for a global trigger or results repository, from the backend, which is the only
        reader of the repository's secret. project_id names the project the token is for, None for work on the
        repository as a whole. 403 if the repository, its provider or its secret is disabled or revoked, or that
        project or its assignment is revoked (a disabled project still gets one), 404 if the repository is unknown.
        Never stored: ask again when the token is needed.
        """
        self.logger.info(f"Fetching a token for {kind} repository {repository_id}")
        segment = "triggers" if kind == "trigger" else "results"
        response = self.session.post(
            f"/global/repositories/{segment}/{repository_id}/token", json={"project_id": project_id}
        )
        return GitToken(**response.json())

    def get_task_results(self, project_id: int, task_id: int) -> list[PullRequestResult]:
        """Get the deliveries of a task's results"""
        self.logger.info(f"Fetching results of task {task_id}")
        response = self.session.get(f"/projects/{project_id}/tasks/{task_id}/results")
        return [PullRequestResult(**result) for result in response.json()]

    def create_result(self, project_id: int, task_id: int, results_repository_id: int) -> PullRequestResult:
        """Create the delivery of a task's results to a results repository its project is assigned, or return the existing one"""
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

    def get_results_by_state(self, project_id: int, state: str, active_resource: bool = False) -> list[PullRequestResult]:
        """Get the project's results in a state, only those whose project results repository is active if active_resource"""
        self.logger.info(f"Fetching {state} results of project {project_id}")
        params = {"state": state, "active_resource": "true"} if active_resource else {"state": state}
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

    def get_dataset(self, dataset_id: int) -> Dataset:
        """Get single dataset"""
        self.logger.info(f"Fetching dataset {dataset_id}")
        response = self.session.get(f"/global/datasets/{dataset_id}")
        return Dataset(**response.json())

    def get_project_dataset(self, project_id: int, dataset_id: int) -> ProjectDataset:
        """The project's dataset, active or not, by the dataset's id"""
        self.logger.info(f"Fetching dataset {dataset_id} of project {project_id}")
        response = self.session.get(f"/projects/{project_id}/datasets/{dataset_id}")
        return ProjectDataset(**response.json())

    def delete_dataset(self, dataset_id: int) -> None:
        """Delete a dataset, and with it (force) every project's resource for it"""
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
        """Assign a global trigger repository to a project"""
        self.logger.info(f"Assigning repository {trigger_repository_id} to project {project_id}")
        data = {"watch_dir": watch_dir, "base_branch": base_branch}
        response = self.session.put(f"/projects/{project_id}/repositories/triggers/{trigger_repository_id}", json=data)
        return ProjectTriggerRepository(**response.json())

    def delete_repository(self, repo_id: int) -> None:
        """Delete a repository, and with it (force) every project's resource for it"""
        self.session.delete(f"/global/repositories/triggers/{repo_id}", params={"force": "true"})

    def _get_all_pages(self, path: str, **filters: str) -> list[dict]:
        """Every item of a paginated list endpoint, filtered by nexus-api's query options"""
        items = []
        page = 1
        while True:
            data = self.session.get(path, params={**filters, "page": page, "size": 100}).json()
            items.extend(data["items"])
            if page >= data["pages"]:
                return items
            page += 1

    def get_dataset_healthcheck(self, dataset_id: int) -> dict:
        """Whether the node can connect to the dataset's database with its secret: {"status": "ok", "health_check": {"message", ...}, ...}"""
        self.logger.info(f"Checking health of dataset {dataset_id}")
        return self.session.get(f"/global/datasets/{dataset_id}/healthcheck").json()

    def find_dataset(self, name: str) -> Dataset | None:
        """The global dataset of that name, if any"""
        for dataset in self.get_datasets():
            if dataset.name.lower() == name.lower():
                return dataset
        return None

    def get_datasets(self) -> list[Dataset]:
        """Get all datasets, over every page"""
        self.logger.info("Fetching datasets")
        return [Dataset(**ds) for ds in self._get_all_pages("/global/datasets")]

    def get_project_datasets(self, project_id: int) -> list[ProjectDataset]:
        """The project's datasets, inactive ones included"""
        self.logger.info(f"Fetching datasets of project {project_id}")
        return [ProjectDataset(**a) for a in self.session.get(f"/projects/{project_id}/datasets").json()]

    def find_project_dataset(self, name: str, project_id: int) -> ProjectDataset | None:
        """The project's dataset of that name, if any"""
        for assignment in self.get_project_datasets(project_id):
            if assignment.dataset.name.lower() == name.lower():
                return assignment
        return None

    def patch_dataset(self, dataset_id: int, data: dict) -> Dataset:
        """Update a global dataset: any of name, host, port, type, read_schema, write_schema, secret_label"""
        self.logger.info(f"Updating dataset {dataset_id}")
        return Dataset(**self.session.patch(f"/global/datasets/{dataset_id}", json=data).json())

    def get_or_assign_dataset(self, project_id: int, dataset: Dataset) -> ProjectDataset:
        """Reuse the project's dataset if there is one, else assign it"""
        assignment = self.find_project_dataset(dataset.name, project_id)
        if assignment:
            self.logger.info(f"Reusing existing dataset {dataset.name} in project {project_id}")
            return assignment
        self.logger.info(f"Assigning dataset {dataset.name} to project {project_id}")
        response = self.session.put(f"/projects/{project_id}/datasets/{dataset.id}", json={})
        return ProjectDataset(**response.json())

    def find_project(self, name: str) -> Project | None:
        """The project of that name, if any"""
        projects = self._get_all_pages("/projects", name=name)
        return Project(**projects[0]) if projects else None

    def get_or_create_project(
        self, name: str, description: str | None = None, enabled: bool = False
    ) -> Project:
        """Reuse the project of that name if there is one, else create it with enabled"""
        project = self.find_project(name)
        if project:
            self.logger.info(f"Reusing existing project {name} ({project.id})")
            return project

        self.logger.info(f"Creating project {name}")
        data = {"name": name, "description": description, "enabled": enabled}
        response = self.session.post("/projects", json=data)
        return self.get_project(response.json()["id"])

    def get_project(self, project_id: int) -> Project:
        """Get single project"""
        self.logger.info(f"Fetching project {project_id}")
        return Project(**self.session.get(f"/projects/{project_id}").json())

    def delete_project(self, project_id: int) -> None:
        """Delete the project and everything under it"""
        self.logger.info(f"Deleting project {project_id}")
        self.session.delete(f"/projects/{project_id}")

    def get_project_healthcheck(self, project_id: int) -> dict:
        """Whether the project's trigger repositories can be reached with their tokens"""
        self.logger.info(f"Checking health of project {project_id}")
        return self.session.get(f"/projects/{project_id}/healthcheck").json()

    def patch_project(self, project_id: int, data: dict) -> Project:
        """Update project"""
        self.logger.info(f"Updating project {project_id}")
        response = self.session.patch(f"/projects/{project_id}", json=data)
        return Project(**response.json())

    def get_secrets(self) -> list[dict]:
        """The secrets, without their values. They belong to no project."""
        return self.session.get("/global/secrets").json()

    def get_secret(self, label: str) -> dict:
        return self.session.get(f"/global/secrets/{label}").json()

    def upsert_secret(self, label: str, values: dict[str, str]) -> dict:
        """
        The backend keeps only the label, so a re-run rotates the values in the secret store.
        Returns the secret, whose key is what it is called in the store.
        """
        if any(secret["label"] == label for secret in self.get_secrets()):
            self.logger.info(f"Updating secret {label}")
            response = self.session.patch(f"/global/secrets/{label}", json={"values": values})
        else:
            self.logger.info(f"Creating secret {label}")
            response = self.session.post(
                "/global/secrets", json={"label": label, "provider": "K8S", "values": values}
            )
        return response.json()

    def delete_secret(self, label: str) -> bool:
        """Delete the secret. Returns whether there was one to delete."""
        if not any(secret["label"] == label for secret in self.get_secrets()):
            return False
        self.logger.info(f"Deleting secret {label}")
        self.session.delete(f"/global/secrets/{label}")
        return True

    def get_git_providers(self) -> list[GitProvider]:
        """The global git providers"""
        return [GitProvider(**provider) for provider in self.session.get("/global/providers").json()]

    def find_git_provider(self, uri: str) -> GitProvider | None:
        """The global git provider with that uri (as the backend keeps it: scheme and host), if any"""
        for provider in self.get_git_providers():
            if provider.uri == uri:
                return provider
        return None

    def get_or_create_git_provider(self, uri: str, name: str, type: str, api_uri: str) -> GitProvider:
        """Reuse the global git provider with that uri if there is one, else create it"""
        provider = self.find_git_provider(uri)
        if provider:
            self.logger.info(f"Reusing existing git provider {provider.name} ({provider.id})")
            return provider
        self.logger.info(f"Creating git provider {name}")
        data = {"name": name, "type": type, "uri": uri, "api_uri": api_uri}
        return GitProvider(**self.session.post("/global/providers", json=data).json())

    def patch_git_provider(self, provider_id: int, data: dict) -> GitProvider:
        """Update a global git provider: any of name, type, uri, api_uri"""
        self.logger.info(f"Updating git provider {provider_id}")
        return GitProvider(**self.session.patch(f"/global/providers/{provider_id}", json=data).json())

    def delete_git_provider(self, provider_id: int) -> None:
        """Delete a global git provider, which no repository may be on"""
        self.logger.info(f"Deleting git provider {provider_id}")
        self.session.delete(f"/global/providers/{provider_id}")

    def get_trigger_repositories(self) -> list[TriggerRepository]:
        """The global trigger repositories"""
        response = self.session.get("/global/repositories/triggers")
        return [TriggerRepository(**repo) for repo in response.json()]

    def find_trigger_repository(self, uri: str) -> TriggerRepository | None:
        """The global trigger repository with that uri, if any"""
        stored_uri = normalise_repo_uri(uri)
        for repo in self.get_trigger_repositories():
            if normalise_repo_uri(repo.uri) == stored_uri:
                return repo
        return None

    def get_or_create_trigger_repository(self, uri: str, provider_id: int, secret_label: str) -> TriggerRepository:
        """Reuse the global trigger repository with that uri if there is one, else create it on the provider"""
        repo = self.find_trigger_repository(uri)
        if repo:
            self.logger.info(f"Reusing existing repository {repo.uri} ({repo.id})")
            return repo
        return self.create_repository(provider_id, repo_path_of(uri), secret_label)

    def patch_trigger_repository(self, repository_id: int, data: dict) -> TriggerRepository:
        """Update a global trigger repository: any of provider_id and secret_label (its uri cannot change)"""
        self.logger.info(f"Updating trigger repository {repository_id}")
        return TriggerRepository(**self.session.patch(f"/global/repositories/triggers/{repository_id}", json=data).json())

    def find_repository(self, uri: str, project_id: int) -> ProjectTriggerRepository | None:
        """The project's trigger repository with that uri, if any"""
        stored_uri = normalise_repo_uri(uri)
        for assignment in self.get_project_trigger_repositories(project_id):
            if normalise_repo_uri(assignment.trigger_repository.uri) == stored_uri:
                return assignment
        return None

    def get_or_assign_repository(
        self,
        project_id: int,
        repo: TriggerRepository,
        watch_dir: str,
        base_branch: str,
    ) -> ProjectTriggerRepository:
        """Reuse the project's repository if there is one, else assign it"""
        assignment = self.find_repository(repo.uri, project_id)
        if assignment:
            self.logger.info(f"Reusing existing repository {repo.uri} in project {project_id}")
            return assignment
        self.logger.info(f"Assigning repository {repo.uri} to project {project_id}")
        data = {"watch_dir": watch_dir, "base_branch": base_branch}
        response = self.session.put(f"/projects/{project_id}/repositories/triggers/{repo.id}", json=data)
        return ProjectTriggerRepository(**response.json())

    def put_project_trigger_repository(
        self, project_id: int, repository_id: int, watch_dir: str, base_branch: str, enabled: bool
    ) -> ProjectTriggerRepository:
        """
        Assign a global trigger repository to a project, with enabled as given. A PUT also replaces the settings
        of an assignment that exists: change one with patch_project_trigger_repository.
        """
        self.logger.info(f"Assigning repository {repository_id} to project {project_id}")
        data = {"watch_dir": watch_dir, "base_branch": base_branch, "enabled": enabled}
        response = self.session.put(f"/projects/{project_id}/repositories/triggers/{repository_id}", json=data)
        return ProjectTriggerRepository(**response.json())

    def get_results_repositories(self) -> list[ResultsRepository]:
        """The global results repositories"""
        response = self.session.get("/global/repositories/results")
        return [ResultsRepository(**repo) for repo in response.json()]

    def find_results_repository(self, uri: str) -> ResultsRepository | None:
        """The global results repository with that uri, if any"""
        stored_uri = normalise_repo_uri(uri)
        for repo in self.get_results_repositories():
            if normalise_repo_uri(repo.uri) == stored_uri:
                return repo
        return None

    def create_results_repository(self, provider_id: int, repo_path: str, secret_label: str) -> ResultsRepository:
        """Create a global results repository"""
        self.logger.info(f"Creating results repository {repo_path} on provider {provider_id}")
        data = {"provider_id": provider_id, "repo_path": repo_path, "secret_label": secret_label}
        response = self.session.post("/global/repositories/results", json=data)
        return ResultsRepository(**response.json())

    def patch_results_repository(self, repository_id: int, data: dict) -> ResultsRepository:
        """Update a global results repository: any of provider_id and secret_label (its uri cannot change)"""
        self.logger.info(f"Updating results repository {repository_id}")
        return ResultsRepository(**self.session.patch(f"/global/repositories/results/{repository_id}", json=data).json())

    def get_or_create_results_repository(self, uri: str, provider_id: int, secret_label: str) -> ResultsRepository:
        """Reuse the global results repository with that uri if there is one, else create it on the provider"""
        repo = self.find_results_repository(uri)
        if repo:
            self.logger.info(f"Reusing existing results repository {repo.uri} ({repo.id})")
            return repo
        return self.create_results_repository(provider_id, repo_path_of(uri), secret_label)

    def get_sensor_status(self, name: str) -> str:
        """The sensor's status on the node, RUNNING or STOPPED: nexus-api's GET /dagster/sensors/<name>"""
        self.logger.info(f"Fetching the status of sensor {name}")
        return self.session.get(f"/dagster/sensors/{name}").json()["status"]

    def get_project_results_repositories(self, project_id: int) -> list[ProjectResultsRepository]:
        """The project's results repositories (it has at most one), inactive ones included"""
        response = self.session.get(f"/projects/{project_id}/repositories/results")
        return [ProjectResultsRepository(**a) for a in response.json()]

    def put_project_results_repository(
        self, project_id: int, repository_id: int, target_dir: str, base_branch: str, enabled: bool
    ) -> ProjectResultsRepository:
        """
        Assign a global results repository to a project that has none, with enabled as given, which needs the
        project disabled. A PUT also resets what the body omits (enabled, owned_by_federated_node) of an assignment
        that exists: change one with patch_project_results_repository.
        """
        self.logger.info(f"Assigning results repository {repository_id} to project {project_id}")
        data = {"target_dir": target_dir, "base_branch": base_branch, "enabled": enabled}
        response = self.session.put(f"/projects/{project_id}/repositories/results/{repository_id}", json=data)
        return ProjectResultsRepository(**response.json())

    def patch_project_results_repository(self, project_id: int, repository_id: int, data: dict) -> ProjectResultsRepository:
        """Update a project's results repository: any of target_dir, base_branch, enabled"""
        self.logger.info(f"Updating results repository {repository_id} of project {project_id}")
        response = self.session.patch(f"/projects/{project_id}/repositories/results/{repository_id}", json=data)
        return ProjectResultsRepository(**response.json())

    def get_or_assign_results_repository(
        self, project_id: int, repo: ResultsRepository, target_dir: str, base_branch: str,
        owned_by_federated_node: bool | None = None,
    ) -> ProjectResultsRepository:
        """Reuse the project's results repository if there is one, else assign the repository"""
        assignments = self.get_project_results_repositories(project_id)
        if assignments:
            self.logger.info(
                f"Reusing existing results repository {assignments[0].results_repository.id} in project {project_id}"
            )
            return assignments[0]
        self.logger.info(f"Assigning results repository {repo.uri} to project {project_id}")
        data = {"target_dir": target_dir, "base_branch": base_branch}
        if owned_by_federated_node is not None:
            data["owned_by_federated_node"] = owned_by_federated_node
        response = self.session.put(f"/projects/{project_id}/repositories/results/{repo.id}", json=data)
        return ProjectResultsRepository(**response.json())
