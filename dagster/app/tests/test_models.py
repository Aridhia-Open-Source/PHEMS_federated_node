import pytest

from app.models import (
    Dataset, NewPullRequest, ProjectTriggerRepository, PullRequest, PullRequestTrigger, Secret, SecretProviderType,
    TriggerRepository,
)
from app.models.pull_request import PROVIDER_FILES_CAP
from app.tests.conftest import (
    SAMPLE_DATASET, SAMPLE_PR, SAMPLE_REPOSITORY_OBJ, SAMPLE_SECRET, SAMPLE_TRIGGER_REPOSITORY,
)


class TestSecret:
    def test_parses_a_webserver_payload(self):
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
    def test_parses_a_webserver_payload(self):
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
    def test_parses_a_webserver_payload(self):
        repo = TriggerRepository(**SAMPLE_TRIGGER_REPOSITORY)

        assert isinstance(repo.secret, Secret)
        assert repo.repo_path == "org/repo"

    @pytest.mark.parametrize("uri,expected", [
        ("github.com/org/repo", "org/repo"),
        ("https://github.com/org/repo", "org/repo"),
        ("http://gitea.fn.svc:3000/org/repo", "org/repo"),
        ("gitea.fn.svc:3000/org/repo", "org/repo"),
    ])
    def test_repo_path_is_the_last_two_segments(self, uri, expected):
        assert TriggerRepository(**{**SAMPLE_TRIGGER_REPOSITORY, "uri": uri}).repo_path == expected

    def test_repo_path_of_a_nested_path_keeps_the_last_two_segments(self):
        repo = TriggerRepository(**{**SAMPLE_TRIGGER_REPOSITORY, "uri": "gitlab.com/group/sub/repo"})

        assert repo.repo_path == "sub/repo"

    @pytest.mark.parametrize("uri", ["github.com/org/repo/", "github.com/org/repo.git"])
    def test_repo_path_ignores_a_trailing_slash_and_git_suffix(self, uri):
        assert TriggerRepository(**{**SAMPLE_TRIGGER_REPOSITORY, "uri": uri}).repo_path == "org/repo"


class TestPullRequest:
    def test_parses_a_webserver_payload(self):
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
    def test_parses_a_webserver_payload(self):
        facts = PullRequest(
            id=3, trigger_repository_id=1, number=5, title="t", raised_by="u", merged_at="2026-01-01T10:00:00",
            merge_commit_sha="a" * 40, base_branch="main", files_truncated=False,
        )

        assert (facts.id, facts.base_branch, facts.files_truncated) == (3, "main", False)
