import logging

from fncli.dagster.git_uri import normalise_repo_uri
from fncli.dagster.utils import BackendSession
from fncli.dagster.models import (
    Dataset, Project, ProjectDataset, ProjectResultsRepository, ProjectTriggerRepository, PullRequestResult,
    PullRequestTrigger, ResultsRepository, Task, TriggerRepository,
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

    def get_repositories(self) -> list[ProjectTriggerRepository]:
        """Get every project's trigger repository assignments"""
        self.logger.info("Fetching repositories")
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

    def get_pull_requests(self, project_id: int, repo_id: int, **query_params) -> list[PullRequestTrigger]:
        """Get all pull requests for a trigger repository assignment, automatically handling pagination"""
        self.logger.info(f"Fetching all pull requests for repo {repo_id}")
        all_prs = []
        page = 1
        per_page = 100

        while True:
            params = {**query_params, "page": page, "per_page": per_page}
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

        self.logger.info(f"Fetched all {len(all_prs)} pull requests for repo {repo_id}")
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

    def create_pull_requests_batch(
        self, project_id: int, repo_id: int, pull_requests: list[dict]
    ) -> list[PullRequestTrigger]:
        """Create multiple pull requests for a trigger repository assignment in one request (up to 100)"""
        if len(pull_requests) > 100:
            raise ValueError("Maximum 100 pull requests per batch")

        self.logger.info(f"Creating batch of {len(pull_requests)} pull requests for repo {repo_id}")
        response = self.session.post(
            f"/projects/{project_id}/trigger_repositories/{repo_id}/pull_requests/batch",
            json={"pull_requests": pull_requests}
        )
        return [PullRequestTrigger(**pr) for pr in response.json()]

    def create_repository_pull_requests_batch(self, repository_id: int, pull_requests: list[dict]) -> dict:
        """
        Ingest up to 100 pull requests on a global trigger repository, once for all projects: the numbers
        stored and those already there. Not used until the ingest polls per repository.
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

    def get_task(self, task_id: int) -> Task:
        """Get single task"""
        self.logger.info(f"Fetching task {task_id}")
        return Task(**self.session.get(f"/tasks/{task_id}").json())

    def get_task_results(self, task_id: int) -> list[PullRequestResult]:
        """The task's result deliveries, one per results repository"""
        self.logger.info(f"Fetching results of task {task_id}")
        return [PullRequestResult(**result) for result in self.session.get(f"/tasks/{task_id}/results").json()]

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

    def _get_all_pages(self, path: str) -> list[dict]:
        """Every item of a paginated list endpoint"""
        items = []
        page = 1
        while True:
            data = self.session.get(path, params={"page": page, "per_page": 100}).json()
            items.extend(data["items"])
            if page >= data["pages"]:
                return items
            page += 1

    def get_datasets(self) -> list[Dataset]:
        """Get all datasets"""
        self.logger.info("Fetching datasets")
        return [Dataset(**ds) for ds in self._get_all_pages("/datasets")]

    def find_dataset(self, name: str) -> Dataset | None:
        """The global dataset of that name, if any"""
        for dataset in self.get_datasets():
            if dataset.name.lower() == name.lower():
                return dataset
        return None

    def get_or_create_dataset(self, name: str, **kwargs) -> Dataset:
        """Reuse the dataset of that name if there is one, else create it from kwargs"""
        dataset = self.find_dataset(name)
        if dataset:
            self.logger.info(f"Reusing existing dataset {name} ({dataset.id})")
            return dataset
        return self.create_dataset(name=name, **kwargs)

    def get_project_datasets(self, project_id: int) -> list[ProjectDataset]:
        """The project's dataset assignments, inactive ones included"""
        self.logger.info(f"Fetching datasets of project {project_id}")
        return [ProjectDataset(**a) for a in self.session.get(f"/projects/{project_id}/datasets").json()]

    def find_project_dataset(self, name: str, project_id: int) -> ProjectDataset | None:
        """The project's assignment of the dataset of that name, if any"""
        for assignment in self.get_project_datasets(project_id):
            if assignment.dataset.name.lower() == name.lower():
                return assignment
        return None

    def get_or_assign_dataset(self, project_id: int, dataset: Dataset) -> ProjectDataset:
        """Reuse the project's assignment of the dataset if there is one, else assign it"""
        assignment = self.find_project_dataset(dataset.name, project_id)
        if assignment:
            self.logger.info(f"Reusing existing assignment {assignment.id} of dataset {dataset.name}")
            return assignment
        self.logger.info(f"Assigning dataset {dataset.name} to project {project_id}")
        response = self.session.post(f"/projects/{project_id}/datasets", json={"dataset_id": dataset.id})
        return ProjectDataset(**response.json())

    def get_dataset(self, dataset_id: int) -> Dataset:
        """Get single dataset"""
        self.logger.info(f"Fetching dataset {dataset_id}")
        response = self.session.get(f"/datasets/{dataset_id}")
        return Dataset(**response.json())

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

    def delete_repository(self, repo_id: int) -> None:
        """Delete a global trigger repository, and with it every project's assignment of it"""
        self.session.delete(f"/trigger_repositories/{repo_id}")

    def get_projects(self) -> list[Project]:
        """Get all projects"""
        self.logger.info("Fetching projects")
        return [Project(**p) for p in self._get_all_pages("/projects")]

    def find_project(self, name: str) -> Project | None:
        """The project of that name, if any"""
        return next((p for p in self.get_projects() if p.name == name), None)

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
        return self.session.get("/secrets").json()

    def get_secret(self, label: str) -> dict:
        return self.session.get(f"/secrets/{label}").json()

    def upsert_secret(self, label: str, values: dict[str, str]) -> dict:
        """
        The backend keeps only the label, so a re-run rotates the values in the secret store.
        Returns the secret, whose key is what it is called in the store.
        """
        if any(secret["label"] == label for secret in self.get_secrets()):
            self.logger.info(f"Updating secret {label}")
            response = self.session.patch(f"/secrets/{label}", json={"values": values})
        else:
            self.logger.info(f"Creating secret {label}")
            response = self.session.post(
                "/secrets", json={"label": label, "provider": "K8S", "values": values}
            )
        return response.json()

    def delete_secret(self, label: str) -> bool:
        """Delete the secret. Returns whether there was one to delete."""
        if not any(secret["label"] == label for secret in self.get_secrets()):
            return False
        self.logger.info(f"Deleting secret {label}")
        self.session.delete(f"/secrets/{label}")
        return True

    def get_trigger_repositories(self) -> list[TriggerRepository]:
        """The global trigger repositories"""
        response = self.session.get("/trigger_repositories")
        return [TriggerRepository(**repo) for repo in response.json()]

    def find_trigger_repository(self, uri: str) -> TriggerRepository | None:
        """The global trigger repository with that uri, if any"""
        stored_uri = normalise_repo_uri(uri)
        for repo in self.get_trigger_repositories():
            if repo.uri == stored_uri:
                return repo
        return None

    def get_or_create_trigger_repository(self, uri: str, **kwargs) -> TriggerRepository:
        """Reuse the global trigger repository with that uri if there is one, else create it from kwargs"""
        repo = self.find_trigger_repository(uri)
        if repo:
            self.logger.info(f"Reusing existing repository {repo.uri} ({repo.id})")
            return repo
        return self.create_repository(uri=uri, **kwargs)

    def find_repository(self, uri: str, project_id: int) -> ProjectTriggerRepository | None:
        """The project's assignment of the trigger repository with that uri, if any"""
        stored_uri = normalise_repo_uri(uri)
        for assignment in self.get_repositories():
            if assignment.project_id == project_id and assignment.trigger_repository.uri == stored_uri:
                return assignment
        return None

    def get_or_assign_repository(
        self,
        project_id: int,
        repo: TriggerRepository,
        watch_dir: str,
        base_branch: str,
        initial_cursor: str | None = None,
    ) -> ProjectTriggerRepository:
        """Reuse the project's assignment of the repository if there is one, else assign it"""
        assignment = self.find_repository(repo.uri, project_id)
        if assignment:
            self.logger.info(f"Reusing existing repository assignment {assignment.id} of project {project_id}")
            return assignment
        self.logger.info(f"Assigning repository {repo.uri} to project {project_id}")
        data = {
            "trigger_repository_id": repo.id,
            "watch_dir": watch_dir,
            "base_branch": base_branch,
            "initial_cursor": initial_cursor,
        }
        response = self.session.post(f"/projects/{project_id}/trigger_repositories", json=data)
        return ProjectTriggerRepository(**response.json())

    def get_results_repositories(self) -> list[ResultsRepository]:
        """The global results repositories"""
        response = self.session.get("/results_repositories")
        return [ResultsRepository(**repo) for repo in response.json()]

    def find_results_repository(self, uri: str) -> ResultsRepository | None:
        """The global results repository with that uri, if any"""
        stored_uri = normalise_repo_uri(uri)
        for repo in self.get_results_repositories():
            if repo.uri == stored_uri:
                return repo
        return None

    def create_results_repository(
        self,
        uri: str,
        provider: str,
        api_uri: str,
        secret_label: str,
    ) -> ResultsRepository:
        """Create a global results repository"""
        self.logger.info(f"Creating results repository {uri}")
        data = {"uri": uri, "provider": provider, "api_uri": api_uri, "secret_label": secret_label}
        response = self.session.post("/results_repositories", json=data)
        return ResultsRepository(**response.json())

    def get_or_create_results_repository(self, uri: str, **kwargs) -> ResultsRepository:
        """Reuse the global results repository with that uri if there is one, else create it from kwargs"""
        repo = self.find_results_repository(uri)
        if repo:
            self.logger.info(f"Reusing existing results repository {repo.uri} ({repo.id})")
            return repo
        return self.create_results_repository(uri=uri, **kwargs)

    def get_project_results_repositories(self, project_id: int) -> list[ProjectResultsRepository]:
        """The project's results repository assignments (it has at most one), inactive ones included"""
        response = self.session.get(f"/projects/{project_id}/results_repositories")
        return [ProjectResultsRepository(**a) for a in response.json()]

    def get_or_assign_results_repository(
        self, project_id: int, repo: ResultsRepository, target_dir: str, owned_by_federated_node: bool | None = None
    ) -> ProjectResultsRepository:
        """Reuse the project's results repository assignment if there is one, else assign the repository"""
        assignments = self.get_project_results_repositories(project_id)
        if assignments:
            self.logger.info(
                f"Reusing existing results repository assignment {assignments[0].id} of project {project_id}"
            )
            return assignments[0]
        self.logger.info(f"Assigning results repository {repo.uri} to project {project_id}")
        data = {"results_repository_id": repo.id, "target_dir": target_dir}
        if owned_by_federated_node is not None:
            data["owned_by_federated_node"] = owned_by_federated_node
        response = self.session.post(f"/projects/{project_id}/results_repositories", json=data)
        return ProjectResultsRepository(**response.json())

    def delete_results_repository(self, repo_id: int) -> None:
        """Delete a global results repository, and with it every project's assignment of it"""
        self.logger.info(f"Deleting results repository {repo_id}")
        self.session.delete(f"/results_repositories/{repo_id}")
