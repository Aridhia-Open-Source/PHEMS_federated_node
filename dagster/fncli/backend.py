from app.backend import BackendAPI
from app.git_uri import normalise_repo_uri
from app.models import (
    Dataset, GitProvider, Project, ProjectDataset, ProjectResultsRepository, ProjectTriggerRepository, ResultsRepository,
    TriggerRepository,
)


def repo_path_of(uri: str) -> str:
    """Where the repository is on its provider (owner/name): the last two segments of its uri"""
    return "/".join(normalise_repo_uri(uri).split("/")[-2:])


class FncliBackendAPI(BackendAPI):
    """The Dagster code location's backend client, plus the setup and teardown calls only the dev CLI makes."""

    def _get_all_pages(self, path: str, **filters: str) -> list[dict]:
        """Every item of a paginated list endpoint, filtered by the webserver's query options"""
        items = []
        page = 1
        while True:
            data = self.session.get(path, params={**filters, "page": page, "per_page": 100}).json()
            items.extend(data["items"])
            if page >= data["pages"]:
                return items
            page += 1

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

    def get_or_create_dataset(self, name: str, **kwargs) -> Dataset:
        """Reuse the dataset of that name if there is one, else create it from kwargs"""
        dataset = self.find_dataset(name)
        if dataset:
            self.logger.info(f"Reusing existing dataset {name} ({dataset.id})")
            return dataset
        return self.create_dataset(name=name, **kwargs)

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

    def get_or_create_results_repository(self, uri: str, provider_id: int, secret_label: str) -> ResultsRepository:
        """Reuse the global results repository with that uri if there is one, else create it on the provider"""
        repo = self.find_results_repository(uri)
        if repo:
            self.logger.info(f"Reusing existing results repository {repo.uri} ({repo.id})")
            return repo
        return self.create_results_repository(provider_id, repo_path_of(uri), secret_label)

    def get_project_results_repositories(self, project_id: int) -> list[ProjectResultsRepository]:
        """The project's results repositories (it has at most one), inactive ones included"""
        response = self.session.get(f"/projects/{project_id}/repositories/results")
        return [ProjectResultsRepository(**a) for a in response.json()]

    def get_or_assign_results_repository(
        self, project_id: int, repo: ResultsRepository, target_dir: str, owned_by_federated_node: bool | None = None
    ) -> ProjectResultsRepository:
        """Reuse the project's results repository if there is one, else assign the repository"""
        assignments = self.get_project_results_repositories(project_id)
        if assignments:
            self.logger.info(
                f"Reusing existing results repository {assignments[0].results_repository.id} in project {project_id}"
            )
            return assignments[0]
        self.logger.info(f"Assigning results repository {repo.uri} to project {project_id}")
        data = {"target_dir": target_dir}
        if owned_by_federated_node is not None:
            data["owned_by_federated_node"] = owned_by_federated_node
        response = self.session.put(f"/projects/{project_id}/repositories/results/{repo.id}", json=data)
        return ProjectResultsRepository(**response.json())

    def delete_results_repository(self, repo_id: int) -> None:
        """Delete a global results repository, and with it (force) every project's resource for it"""
        self.logger.info(f"Deleting results repository {repo_id}")
        self.session.delete(f"/global/repositories/results/{repo_id}", params={"force": "true"})
