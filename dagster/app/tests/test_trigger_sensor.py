"""
Test suite for pull_request_trigger_sensor.

Tests the flow:
1. Fetch unprocessed valid PRs from database
2. Extract executors from PR spec
3. Yield RunRequest to github_task_monitor_job
4. Idempotency: same PR shouldn't trigger multiple runs
"""

import json

import pytest
import requests
from unittest.mock import MagicMock
from dagster import SkipReason, RunRequest

from app.definitions.sensors.github.pr_trigger import PullRequestTriggerSensor
from app.models import Dataset, PullRequest, PullRequestStatus, Registry
from app.tests.conftest import SAMPLE_REPO, SAMPLE_PR


class TestPullRequestTriggerSensor:
    """Tests for PullRequestTriggerSensor."""

    def test_skips_when_no_repositories(self):
        """Sensor should skip if no repositories are configured."""
        mock_backend_api = MagicMock()
        mock_backend_api.get_repositories.return_value = []

        sensor = PullRequestTriggerSensor(
            context=MagicMock(),
            backend_api=mock_backend_api,
            github_api=MagicMock(),
        )
        result = list(sensor())

        assert len(result) == 1
        assert isinstance(result[0], SkipReason)
        assert "No repositories" in str(result[0])

    def test_skips_when_no_unprocessed_prs(self):
        """Sensor should skip if all PRs are already processed."""
        repo = MagicMock()
        repo.id = SAMPLE_REPO["id"]

        mock_backend_api = MagicMock()
        mock_backend_api.get_repositories.return_value = [repo]
        mock_backend_api.get_pull_requests.return_value = []

        sensor = PullRequestTriggerSensor(
            context=MagicMock(),
            backend_api=mock_backend_api,
            github_api=MagicMock(),
        )
        result = list(sensor())

        assert len(result) == 1
        assert isinstance(result[0], SkipReason)
        assert "No unknown pull requests found" in str(result[0])

    def test_yields_run_requests_for_valid_and_unprocessed_prs(self):
        """Sensor should return list of RunRequests for unprocessed valid PRs."""
        from app.models import PullRequest
        import json

        repo = MagicMock()
        repo.id = SAMPLE_REPO["id"]
        repo.uri = SAMPLE_REPO["uri"]
        repo.path = SAMPLE_REPO["path"]
        repo.watch_dir = SAMPLE_REPO["watch_dir"]

        pr = MagicMock(spec=PullRequest)
        pr.number = SAMPLE_PR["number"]
        pr.title = SAMPLE_PR["title"]
        pr.repository_id = SAMPLE_REPO["id"]
        pr.spec = SAMPLE_PR["spec"]
        pr.merge_commit_sha = SAMPLE_PR["merge_commit_sha"]

        mock_backend_api = MagicMock()
        mock_backend_api.get_repositories.return_value = [repo]
        mock_backend_api.get_pull_requests.return_value = [pr]

        mock_github_api = MagicMock()
        # Mock PR files endpoint
        mock_github_api.get_pull_request_files.return_value = [
            {"filename": "specs/test.json", "status": "added"}
        ]
        # Mock file contents endpoint
        mock_github_api.get_file_contents.return_value = json.dumps({
            "spec": {
                "docker_image": "ghcr.io/org/experiment:latest",
                "env": {"KEY": "value"},
            }
        })

        sensor = PullRequestTriggerSensor(
            context=MagicMock(),
            backend_api=mock_backend_api,
            github_api=mock_github_api,
        )
        result = list(sensor())

        assert len(result) == 1
        assert isinstance(result[0], RunRequest)
        assert result[0].run_key == f"{repo.id}/{pr.number}"
        assert result[0].tags["pr_number"] == str(pr.number)
        assert result[0].tags["repo_id"] == str(repo.id)
        assert result[0].tags["trigger"] == "github"

    def test_continues_on_backend_api_error(self):
        """Sensor should continue processing other repos if one fails."""
        repo1 = MagicMock()
        repo1.id = 1

        repo2 = MagicMock()
        repo2.id = 2

        mock_backend_api = MagicMock()
        mock_backend_api.get_repositories.return_value = [repo1, repo2]
        # First repo raises HTTP error, second succeeds
        mock_backend_api.get_pull_requests.side_effect = [
            requests.HTTPError("500 Server Error"),
            []
        ]

        sensor = PullRequestTriggerSensor(
            context=MagicMock(),
            backend_api=mock_backend_api,
            github_api=MagicMock(),
        )
        result = list(sensor())

        # Should skip (no work found) and not crash
        assert len(result) == 1
        assert isinstance(result[0], SkipReason)


SPEC_DATASET = {
    "id": 1,
    "name": "cdm",
    "host": "db.host",
    "port": 5432,
    "schema": "cdm",
    "schema_write": "results",
    "type": "postgres",
    "slug": "cdm",
    "url": "https://db.host/cdm",
}


def make_sensor(backend_api=None, github_api=None):
    return PullRequestTriggerSensor(
        context=MagicMock(),
        backend_api=backend_api or MagicMock(),
        github_api=github_api or MagicMock(),
    )


def make_repo():
    repo = MagicMock()
    repo.id = 1
    repo.uri = "github.com/org/repo"
    repo.path = "org/repo"
    repo.watch_dir = "specs/"
    repo.dataset_id = 1
    return repo


def make_pr(spec, number=5):
    pr = MagicMock(spec=PullRequest)
    pr.number = number
    pr.title = "Add experiment spec"
    pr.repository_id = 1
    pr.spec = spec
    pr.merge_commit_sha = "abc123"
    return pr


class TestSpecValidation:
    def test_image_key(self):
        sensor = make_sensor()

        assert sensor._validate_spec({"spec": {"image": "ghcr.io/org/img:1"}})

    def test_docker_image_key_is_also_accepted(self):
        sensor = make_sensor()

        assert sensor._validate_spec({"spec": {"docker_image": "ghcr.io/org/img:1"}})

    def test_a_spec_without_an_image_is_rejected(self):
        with pytest.raises(ValueError, match="must contain 'image'"):
            make_sensor()._validate_spec({"spec": {"env": {}}})

    def test_a_non_dict_spec_is_rejected(self):
        with pytest.raises(ValueError, match="must be a dictionary"):
            make_sensor()._validate_spec({"spec": ["image"]})


class TestWatchedFiles:
    def test_only_added_json_files_under_the_watch_dir(self):
        files = [
            {"filename": "specs/new.json", "status": "added"},
            {"filename": "specs/edited.json", "status": "modified"},
            {"filename": "specs/new.yaml", "status": "added"},
            {"filename": "docs/new.json", "status": "added"},
        ]

        watched = make_sensor()._filter_watched_files("specs/", files)

        assert [f["filename"] for f in watched] == ["specs/new.json"]


class TestPullRequestSetup:
    def _github_api(self, files, contents=None):
        api = MagicMock()
        api.get_pull_request_files.return_value = files
        api.get_file_contents.return_value = contents or json.dumps(
            {"spec": {"image": "ghcr.io/org/img:1"}}
        )
        return api

    def test_a_pr_touching_nothing_watched_is_ignored(self):
        github_api = self._github_api([{"filename": "docs/readme.md", "status": "added"}])
        sensor = make_sensor(github_api=github_api)

        status, spec = sensor._setup_pull_request(make_repo(), make_pr({}))

        assert status == PullRequestStatus.IGNORED.value
        assert spec == {}

    def test_more_than_one_spec_file_is_invalid(self):
        github_api = self._github_api([
            {"filename": "specs/a.json", "status": "added"},
            {"filename": "specs/b.json", "status": "added"},
        ])
        repo = make_repo()
        sensor = make_sensor(github_api=github_api)

        status, _ = sensor._setup_pull_request(repo, make_pr({}))

        assert status == PullRequestStatus.INVALID.value

    def test_an_unparsable_spec_is_invalid(self):
        github_api = self._github_api(
            [{"filename": "specs/a.json", "status": "added"}], contents="not json"
        )
        repo = make_repo()
        sensor = make_sensor(github_api=github_api)

        status, _ = sensor._setup_pull_request(repo, make_pr({}))

        assert status == PullRequestStatus.INVALID.value

    def test_a_valid_spec_is_ready(self):
        github_api = self._github_api([{"filename": "specs/a.json", "status": "added"}])
        repo = make_repo()
        sensor = make_sensor(github_api=github_api)

        status, spec = sensor._setup_pull_request(repo, make_pr({}))

        assert status == PullRequestStatus.READY.value
        assert spec == {"image": "ghcr.io/org/img:1"}

    def test_the_spec_is_read_at_the_merge_commit(self):
        github_api = self._github_api([{"filename": "specs/a.json", "status": "added"}])
        repo = make_repo()
        sensor = make_sensor(github_api=github_api)

        sensor._setup_pull_request(repo, make_pr({}))

        assert github_api.get_file_contents.call_args.kwargs["ref"] == "abc123"


class TestRunRequestConfig:
    def _backend_api(self, registries=()):
        api = MagicMock()
        api.get_dataset.return_value = Dataset(**SPEC_DATASET)
        api.get_registries.return_value = list(registries)
        return api

    def test_dataset_fields_are_passed_to_the_op(self):
        backend_api = self._backend_api()

        request = make_sensor(backend_api)._make_run_request(
            make_repo(), make_pr({"image": "ghcr.io/org/img:1"})
        )

        config = request.run_config["ops"]["k8s_pipes_op"]["config"]
        assert config["dataset_name"] == "cdm"
        assert config["dataset_secret_name"] == "db.host-cdm-creds"
        assert config["docker_image"] == "ghcr.io/org/img:1"

    def test_the_docker_image_key_is_accepted(self):
        backend_api = self._backend_api()

        request = make_sensor(backend_api)._make_run_request(
            make_repo(), make_pr({"docker_image": "ghcr.io/org/img:1"})
        )

        config = request.run_config["ops"]["k8s_pipes_op"]["config"]
        assert config["docker_image"] == "ghcr.io/org/img:1"

    def test_a_spec_without_an_image_raises(self):
        with pytest.raises(ValueError, match="missing 'image'"):
            make_sensor(self._backend_api())._make_run_request(make_repo(), make_pr({}))

    def test_a_private_registry_image_carries_its_pull_secret(self):
        backend_api = self._backend_api([Registry(id=1, url="ghcr.io")])

        request = make_sensor(backend_api)._make_run_request(
            make_repo(), make_pr({"image": "ghcr.io/org/img:1"})
        )

        config = request.run_config["ops"]["k8s_pipes_op"]["config"]
        assert config["image_pull_secret"] == "ghcr-io"

    def test_an_unconfigured_registry_leaves_the_key_out(self):
        backend_api = self._backend_api([Registry(id=1, url="ghcr.io")])

        request = make_sensor(backend_api)._make_run_request(
            make_repo(), make_pr({"image": "docker.io/library/alpine:3"})
        )

        assert "image_pull_secret" not in request.run_config["ops"]["k8s_pipes_op"]["config"]

    def test_a_registry_lookup_failure_does_not_stop_the_run(self):
        backend_api = self._backend_api()
        backend_api.get_registries.side_effect = requests.HTTPError("500")
        sensor = make_sensor(backend_api)

        request = sensor._make_run_request(make_repo(), make_pr({"image": "ghcr.io/org/img:1"}))

        assert "image_pull_secret" not in request.run_config["ops"]["k8s_pipes_op"]["config"]
        sensor.log.warning.assert_called_once()

    def test_the_run_key_is_the_pr(self):
        request = make_sensor(self._backend_api())._make_run_request(
            make_repo(), make_pr({"image": "ghcr.io/org/img:1"}, number=7)
        )

        assert request.run_key == "1/7"
