"""Reading the backend into the diff's snapshot (fncli.nodefile.state), from a fake API."""

from app.models import Dataset, GitProvider, Project, ProjectDataset, ProjectResultsRepository, ProjectTriggerRepository, ResultsRepository, TriggerRepository

from fncli.nodefile.diff import DatasetState, ProjectState, ProviderState, RepositoryState, ResultsState, TriggerState
from fncli.nodefile.state import read_state

PROVIDER = {
    "id": 1, "name": "gitea-local", "type": "gitea", "uri": "http://Gitea.fn.svc:4000/",
    "api_uri": "http://gitea.fn.svc:4000/api/v1", "enabled": True,
}
SECRET = {"id": 5, "label": "trigger-creds", "provider": "K8S", "key": "fn-secret-trigger-creds", "enabled": True}
TRIGGER = {
    "id": 10, "uri": "http://gitea.fn.svc:4000/gitea_admin/Trigger-Repo.git", "repo_path": "gitea_admin/trigger-repo",
    "provider": PROVIDER, "secret": SECRET, "enabled": True, "pr_cursor": "x",
}
RESULTS = {
    "id": 11, "uri": "http://gitea.fn.svc:4000/gitea_admin/results-repo", "repo_path": "gitea_admin/results-repo",
    "provider": PROVIDER, "secret": {**SECRET, "id": 6, "label": "results-creds"}, "enabled": True,
}
DATASET = {
    "id": 20, "secret": {**SECRET, "id": 7, "label": "dataset-creds"}, "name": "Shared", "host": "db.svc", "port": 5432,
    "read_schema": "cdm", "write_schema": None, "type": "postgres", "enabled": True, "slug": "shared", "url": "u",
}


class FakeAPI:
    """The read calls of FncliBackendAPI, over two projects: one with everything, one empty"""

    def get_git_providers(self):
        return [GitProvider(**PROVIDER)]

    def get_secrets(self):
        return [SECRET, {**SECRET, "label": "results-creds"}]

    def get_trigger_repositories(self):
        return [TriggerRepository(**TRIGGER)]

    def get_results_repositories(self):
        return [ResultsRepository(**RESULTS)]

    def get_datasets(self):
        return [Dataset(**DATASET)]

    def get_projects(self):
        return [Project(id=1, name="alpha", enabled=True, default_dataset_id=20), Project(id=2, name="empty")]

    def get_project_datasets(self, project_id):
        if project_id == 2:
            return []
        other = {**DATASET, "id": 21, "name": "Other"}
        return [
            ProjectDataset(project_id=1, dataset=Dataset(**other), enabled=False, revoked=False, active=False),
            ProjectDataset(project_id=1, dataset=Dataset(**DATASET), enabled=True, revoked=False, active=True),
        ]

    def get_project_trigger_repositories(self, project_id):
        if project_id == 2:
            return []
        return [ProjectTriggerRepository(
            project_id=1, trigger_repository=TriggerRepository(**TRIGGER), watch_dir="specs/", base_branch="main",
            pr_cursor="x", enabled=False, revoked=False, active=False,
        )]

    def get_project_results_repositories(self, project_id):
        if project_id == 2:
            return []
        return [ProjectResultsRepository(
            project_id=1, results_repository=ResultsRepository(**RESULTS), base_branch="main", target_dir="results/",
            owned_by_federated_node=True, enabled=True, revoked=False, active=True,
        )]


def test_the_backend_is_read_into_normalised_plain_data():
    state = read_state(FakeAPI())

    assert state.providers == [ProviderState("gitea-local", "gitea", "http://gitea.fn.svc:4000", "http://gitea.fn.svc:4000/api/v1")]
    assert state.secrets == {"trigger-creds", "results-creds"}
    assert state.trigger_repositories == [RepositoryState("gitea.fn.svc:4000/gitea_admin/trigger-repo", "http://gitea.fn.svc:4000", "trigger-creds")]
    assert state.results_repositories == [RepositoryState("gitea.fn.svc:4000/gitea_admin/results-repo", "http://gitea.fn.svc:4000", "results-creds")]
    assert state.datasets == [DatasetState("Shared", "postgres", "db.svc", 5432, "cdm", None, "dataset-creds")]


def test_each_project_is_read_with_its_assignments_and_its_default_dataset():
    alpha, empty = read_state(FakeAPI()).projects

    assert alpha == ProjectState(
        "alpha", True, ["Other", "Shared"], "Shared",
        [TriggerState("gitea.fn.svc:4000/gitea_admin/trigger-repo", "specs/", "main", False)],
        ResultsState("gitea.fn.svc:4000/gitea_admin/results-repo", "results/", "main", True),
    )
    assert empty == ProjectState("empty", False, [], None, [], None)
