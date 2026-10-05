import pytest

from app.models import Dataset, PullRequest, Secret, SecretProviderType, TriggerRepository
from app.tests.conftest import SAMPLE_DATASET, SAMPLE_PR, SAMPLE_REPOSITORY_OBJ, SAMPLE_SECRET


class TestSecret:
    def test_parses_a_webserver_payload(self):
        secret = Secret(**SAMPLE_SECRET)

        assert secret.provider is SecretProviderType.K8S
        assert (secret.key, secret.namespace, secret.label) == ("git-token-abc", "fn", "git-token")

    def test_namespace_and_description_are_optional(self):
        secret = Secret(id=1, project_id=1, label="l", provider="K8S", key="k")

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


class TestTriggerRepository:
    def test_parses_a_webserver_payload(self):
        repo = TriggerRepository(**SAMPLE_REPOSITORY_OBJ)

        assert isinstance(repo.secret, Secret)
        assert repo.repo_path == "org/repo"
        assert repo.pull_requests == []
        assert repo.pr_count == 0

    def test_dataset_id_and_initial_cursor_are_optional(self):
        payload = {k: v for k, v in SAMPLE_REPOSITORY_OBJ.items() if k not in ("dataset_id", "initial_cursor")}

        repo = TriggerRepository(**payload)

        assert repo.dataset_id is None and repo.initial_cursor is None

    def test_nested_pull_requests_are_parsed(self):
        repo = TriggerRepository(**{**SAMPLE_REPOSITORY_OBJ, "pull_requests": [SAMPLE_PR]})

        assert isinstance(repo.pull_requests[0], PullRequest)
        assert repo.pull_requests[0].number == 5

    def test_unknown_fields_are_kept(self):
        assert TriggerRepository(**{**SAMPLE_REPOSITORY_OBJ, "extra": 1}).extra == 1

    @pytest.mark.parametrize("uri,expected", [
        ("github.com/org/repo", "org/repo"),
        ("https://github.com/org/repo", "org/repo"),
        ("http://gitea.fn.svc:3000/org/repo", "org/repo"),
        ("gitea.fn.svc:3000/org/repo", "org/repo"),
        ("org/repo", "org/repo"),
    ])
    def test_repo_path_is_the_last_two_segments(self, uri, expected):
        assert TriggerRepository(**{**SAMPLE_REPOSITORY_OBJ, "uri": uri}).repo_path == expected

    def test_repo_path_of_a_nested_path_keeps_the_last_two_segments(self):
        repo = TriggerRepository(**{**SAMPLE_REPOSITORY_OBJ, "uri": "gitlab.com/group/sub/repo"})

        assert repo.repo_path == "sub/repo"

    @pytest.mark.parametrize("uri", ["github.com/org/repo/", "github.com/org/repo.git"])
    @pytest.mark.xfail(reason="BUG: repo_path keeps a trailing slash or .git suffix", strict=False)
    def test_repo_path_ignores_a_trailing_slash_and_git_suffix(self, uri):
        assert TriggerRepository(**{**SAMPLE_REPOSITORY_OBJ, "uri": uri}).repo_path == "org/repo"


class TestPullRequest:
    def test_parses_a_webserver_payload(self):
        pr = PullRequest(**{**SAMPLE_PR, "id": 77, "created_at": "x"})

        assert pr.number == 5 and pr.state.value == "UNKNOWN"
        assert pr.task_id is None and pr.state_cause is None
        assert pr.id == 77

    def test_from_git_reads_the_provider_response(self):
        git_pr = {
            "number": 12, "title": "Add spec", "user": {"login": "dev"},
            "merged_at": "2026-06-26T10:00:00Z", "merge_commit_sha": "abc", "extra": "ignored",
        }

        pr = PullRequest.from_git(4, git_pr)

        assert (pr.trigger_repository_id, pr.number, pr.raised_by) == (4, 12, "dev")
        assert pr.state.value == "UNKNOWN" and pr.payload == {}

    def test_dump_new_leaves_out_the_server_fields(self):
        pr = PullRequest.from_git(4, {
            "number": 12, "title": "t", "user": {"login": "dev"},
            "merged_at": "2026-06-26T10:00:00Z", "merge_commit_sha": "abc",
        })

        assert pr.dump_new() == {
            "number": 12, "title": "t", "raised_by": "dev",
            "merged_at": "2026-06-26T10:00:00Z", "merge_commit_sha": "abc", "payload": {},
        }
