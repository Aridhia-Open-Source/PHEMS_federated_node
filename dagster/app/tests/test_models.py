import pytest

from app.models import (
    Dataset, GitProvider, NewPullRequest, Project, ProjectTriggerRepository, PullRequest, PullRequestTrigger, Secret,
    SecretProviderType, Task, TaskSpec, TriggerRepository, PullRequestResult,
)
from app.models.pull_request import PROVIDER_FILES_CAP
from app.tests.conftest import (
    SAMPLE_DATASET, SAMPLE_PR, SAMPLE_REPOSITORY_OBJ, SAMPLE_SECRET, SAMPLE_TRIGGER_REPOSITORY,
)


class TestSecret:
    def test_parses_a_nexus_api_payload(self):
        secret = Secret(**SAMPLE_SECRET)

        assert secret.provider is SecretProviderType.K8S
        assert (secret.key, secret.namespace, secret.label) == ("git-token-abc", "fn", "git-token")

    def test_namespace_and_description_are_optional(self):
        secret = Secret(id=1, label="l", provider="K8S", key="k", enabled=True)

        assert secret.namespace is None and secret.description is None

    def test_unknown_provider_is_rejected(self):
        with pytest.raises(ValueError):
            Secret(**{**SAMPLE_SECRET, "provider": "VAULT"})

    def test_unknown_fields_are_kept(self):
        assert Secret(**{**SAMPLE_SECRET, "extra": 1}).extra == 1


class TestDataset:
    def test_secret_is_nested(self):
        dataset = Dataset(**SAMPLE_DATASET)

        assert isinstance(dataset.secret, Secret)
        assert dataset.secret.key == "git-token-abc"

    def test_secret_is_required(self):
        payload = {k: v for k, v in SAMPLE_DATASET.items() if k != "secret"}

        with pytest.raises(ValueError):
            Dataset(**payload)

    def test_schemas_are_optional(self):
        dataset = Dataset(**{**SAMPLE_DATASET, "read_schema": None, "write_schema": None})

        assert dataset.read_schema is None and dataset.write_schema is None

    def test_unknown_backend_fields_are_kept(self):
        dataset = Dataset(**{**SAMPLE_DATASET, "extra_field": "value"})

        assert dataset.extra_field == "value"


class TestProjectTriggerRepository:
    def test_parses_a_nexus_api_payload(self):
        repo = ProjectTriggerRepository(**SAMPLE_REPOSITORY_OBJ)

        assert isinstance(repo.trigger_repository, TriggerRepository)
        assert isinstance(repo.trigger_repository.secret, Secret)
        assert repo.repo_path == "org/repo"
        assert repo.pull_requests == []
        assert repo.pr_count == 0
        assert (repo.enabled, repo.revoked, repo.active) == (True, False, True)

    def test_dataset_id_is_optional(self):
        payload = {k: v for k, v in SAMPLE_REPOSITORY_OBJ.items() if k != "dataset_id"}

        repo = ProjectTriggerRepository(**payload)

        assert repo.dataset_id is None

    def test_nested_pull_requests_are_parsed(self):
        repo = ProjectTriggerRepository(**{**SAMPLE_REPOSITORY_OBJ, "pull_requests": [SAMPLE_PR]})

        assert isinstance(repo.pull_requests[0], PullRequestTrigger)
        assert repo.pull_requests[0].number == 5

    def test_unknown_fields_are_kept(self):
        assert ProjectTriggerRepository(**{**SAMPLE_REPOSITORY_OBJ, "extra": 1}).extra == 1


class TestTriggerRepository:
    def test_parses_a_nexus_api_payload(self):
        repo = TriggerRepository(**SAMPLE_TRIGGER_REPOSITORY)

        assert isinstance(repo.secret, Secret)
        assert isinstance(repo.provider, GitProvider)
        assert (repo.repo_path, repo.uri) == ("org/repo", "https://github.com/org/repo")
        assert (repo.provider.type, repo.provider.api_uri) == ("github", "https://api.github.com")


class TestPullRequest:
    def test_parses_a_nexus_api_payload(self):
        pr = PullRequestTrigger(**{**SAMPLE_PR, "id": 77, "created_at": "x"})

        assert pr.number == 5 and pr.state.value == "UNKNOWN"
        assert pr.task_id is None and pr.state_cause is None
        assert pr.id == 77


class TestNewPullRequest:
    GIT_PR = {
        "number": 12, "title": "Add spec", "user": {"login": "dev"}, "base": {"ref": "main"},
        "merged_at": "2026-06-26T10:00:00Z", "merge_commit_sha": "abc", "extra": "ignored",
    }
    FILES = [
        {"filename": "triggers/spec.json", "status": "added", "patch": "content"},
        {"filename": "README.md", "status": "modified"},
    ]

    def test_from_git_reads_the_provider_response_and_the_files_as_paths_with_status(self):
        pr = NewPullRequest.from_git(self.GIT_PR, self.FILES)

        assert pr.model_dump() == {
            "number": 12, "title": "Add spec", "raised_by": "dev", "merged_at": "2026-06-26T10:00:00Z",
            "merge_commit_sha": "abc", "base_branch": "main", "files_truncated": False,
            "changed_files": [
                {"path": "triggers/spec.json", "status": "added"}, {"path": "README.md", "status": "modified"},
            ],
        }

    def test_a_list_as_long_as_the_providers_cap_is_truncated(self):
        files = [{"filename": f"f{n}.json", "status": "added"} for n in range(PROVIDER_FILES_CAP)]

        assert NewPullRequest.from_git(self.GIT_PR, files).files_truncated is True
        assert NewPullRequest.from_git(self.GIT_PR, files[:-1]).files_truncated is False


class TestPullRequestFacts:
    def test_parses_a_nexus_api_payload(self):
        facts = PullRequest(
            id=3, trigger_repository_id=1, number=5, title="t", raised_by="u", merged_at="2026-01-01T10:00:00",
            merge_commit_sha="a" * 40, base_branch="main", files_truncated=False,
        )

        assert (facts.id, facts.base_branch, facts.files_truncated) == (3, "main", False)


class TestRevokedOnTheGlobalSide:
    """The backend's `revoked` flag on a global resource, a provider and a project is kept; the launcher reads it through /config."""

    def test_the_flag_is_kept_on_a_dataset_a_repository_its_provider_and_a_project(self):
        dataset = Dataset(**{**SAMPLE_DATASET, "revoked": True})
        repo = TriggerRepository(**{
            **SAMPLE_TRIGGER_REPOSITORY, "revoked": True, "provider": {**SAMPLE_TRIGGER_REPOSITORY["provider"], "revoked": True},
        })
        project = Project(id=1, name="p", enabled=True, revoked=True)

        assert (dataset.revoked, repo.revoked, repo.provider.revoked, project.revoked) == (True, True, True, True)


class TestUnknownFieldsAreKept:
    """nexus-api may add fields to a response: every wire model keeps what it does not know."""

    def test_a_task(self):
        task = Task(
            id=1, name="t", spec={"image": "i", "env": {}}, attempt=1, requested_by="u", project_id=1, trigger_id=2,
            added_later="x",
        )

        assert task.added_later == "x"

    def test_a_task_spec(self):
        assert TaskSpec(image="i", env={}, added_later="x").added_later == "x"

    def test_a_project(self):
        assert Project(id=1, name="p", added_later="x").added_later == "x"

    def test_a_git_provider(self):
        assert GitProvider(**{**SAMPLE_TRIGGER_REPOSITORY["provider"], "added_later": "x"}).added_later == "x"

    def test_a_trigger_repository(self):
        assert TriggerRepository(**{**SAMPLE_TRIGGER_REPOSITORY, "added_later": "x"}).added_later == "x"

    def test_a_pull_request_result(self):
        result = PullRequestResult(
            id=1, type="PR", task_id=2, project_id=3, results_repository_id=4, step="OPENED", state="DELIVERED",
            attempts=1, added_later="x",
        )

        assert result.added_later == "x"

    def test_a_nested_model_keeps_them_too(self):
        repo = ProjectTriggerRepository(**{
            **SAMPLE_REPOSITORY_OBJ,
            "trigger_repository": {**SAMPLE_TRIGGER_REPOSITORY, "secret": {**SAMPLE_SECRET, "added_later": "x"}},
        })

        assert repo.trigger_repository.secret.added_later == "x"
