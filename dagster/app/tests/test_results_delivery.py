import json
import subprocess
import zipfile
from unittest.mock import MagicMock, patch

import dagster as dg
import pytest

from app.config import ResultsDeliveryConfig
from app.definitions.sensors.task import JOBS, SENSORS
from app.definitions.sensors.task.delivery import deliver_results_job, task_results_delivery_sensor
from app.delivery import git_push
from app.delivery.results import ResultsDelivery
from app.models import PullRequest, ResultsRepository, Task, TaskResult, TriggerRepository
from app.tests.conftest import SAMPLE_SECRET

RUN_ID = "run-1"
TASK = Task(
    id=7, name="t", docker_image="img", spec={"image": "img"}, attempt=1, requested_by="u",
    project_id=1, trigger_id=3, dagster_run_id=RUN_ID,
)
REPOSITORY = ResultsRepository(
    id=5, uri="gitea.fn.svc:3000/fn/results", provider="gitea",
    api_uri="http://gitea.fn.svc:3000/api/v1", secret=SAMPLE_SECRET, target_dir="/results/",
    project_id=1,
)
TRIGGER_REPOSITORY = TriggerRepository(
    id=2, uri="gitea.fn.svc:3000/fn/analysis", provider="gitea", api_uri="http://x/api/v1",
    secret=SAMPLE_SECRET, watch_dir="w", base_branch="main", project_id=1, pr_cursor="c",
)
PULL_REQUEST = PullRequest(
    trigger_repository_id=2, number=12, title="t", raised_by="u", merged_at="2026-01-01T00:00:00Z",
    payload={}, merge_commit_sha="abc", state="YIELDED", task_id=7,
)
LAYOUT = "results/analysis/12/7"
BRANCH = "results/analysis/12/7-abc"


def git(*args, cwd):
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def remote(tmp_path):
    """A bare repository with one commit on main, standing in for the results repository."""
    bare = tmp_path / "remote.git"
    seed = tmp_path / "seed"
    git("init", "--bare", "-b", "main", str(bare), cwd=tmp_path)
    git("init", "-b", "main", str(seed), cwd=tmp_path)
    (seed / "README.md").write_text("results\n")
    git("add", ".", cwd=seed)
    git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-m", "init", cwd=seed)
    git("push", str(bare), "main", cwd=seed)
    return bare


@pytest.fixture
def artifacts(tmp_path):
    root = tmp_path / "artifacts"
    (root / RUN_ID / "sub").mkdir(parents=True)
    (root / RUN_ID / "out.txt").write_text("hello")
    (root / RUN_ID / "sub" / "b.csv").write_text("a,b\n1,2\n")
    return root


@pytest.fixture
def backend_api():
    api = MagicMock()
    api.get_task.return_value = TASK
    api.get_results_repository.return_value = REPOSITORY
    api.get_repositories.return_value = [TRIGGER_REPOSITORY]
    api.get_pull_requests.return_value = [PULL_REQUEST]
    api.create_task_result.return_value = TaskResult(
        id=9, type="PR", task_id=7, results_repository_id=5, status="PENDING", attempts=0,
    )
    return api


RESULTS_PR = {
    "number": 3, "html_url": "http://gitea/fn/results/pulls/3", "state": "open", "merged_at": None,
    "merge_commit_sha": None,
}


@pytest.fixture
def git_api():
    api = MagicMock()
    api.find_pull_request_by_branch.return_value = None
    api.create_pull_request.return_value = RESULTS_PR
    return api


@pytest.fixture
def git_apis(git_api):
    factory = MagicMock()
    factory.for_repository.return_value = git_api
    return factory


def deliver(backend_api, remote, artifacts, git_apis=None, max_zip_bytes=10485760):
    config = ResultsDeliveryConfig(DAGSTER_ARTIFACT_MOUNT_PATH=str(artifacts), RESULTS_MAX_ZIP_BYTES=max_zip_bytes)
    with patch("app.delivery.results.SecretProvider") as provider, \
            patch.object(git_push, "clone_url", return_value=str(remote)):
        provider.return_value.get.return_value = "tok"
        ResultsDelivery(backend_api, git_apis or MagicMock(), config, MagicMock())(7)
    return provider


def patched_fields(backend_api):
    (task_result_id, fields), _ = backend_api.patch_task_result.call_args
    assert task_result_id == 9
    return fields


def test_success_pushes_a_branch_with_the_layout_and_marks_the_row_delivered(
    backend_api, remote, artifacts, tmp_path, git_apis
):
    provider = deliver(backend_api, remote, artifacts, git_apis)

    provider.return_value.get.assert_called_once_with(SAMPLE_SECRET["key"], "fn", "TOKEN")
    fields = patched_fields(backend_api)
    assert fields["status"] == "DELIVERED"
    assert fields["attempts"] == 1
    check = tmp_path / "check"
    git("clone", "--branch", BRANCH, str(remote), str(check), cwd=tmp_path)
    assert fields["commit_sha"] == git("rev-parse", "HEAD", cwd=check)
    assert fields["branch"] == BRANCH
    out = check / LAYOUT
    with zipfile.ZipFile(out / "results.zip") as zf:
        assert sorted(zf.namelist()) == ["out.txt", "sub/b.csv"]
    assert json.loads((out / "spec.json").read_text()) == {"image": "img"}
    assert git("rev-list", "--count", "main", cwd=remote) == "1"
    metadata = json.loads((out / "metadata.json").read_text())
    assert metadata["branch"] == BRANCH
    assert metadata["merge_commit_sha"] == "abc"
    assert metadata["task_id"] == 7
    assert metadata["dagster_run_id"] == RUN_ID
    assert metadata["trigger_repository_uri"] == TRIGGER_REPOSITORY.uri
    assert metadata["pull_request_number"] == 12
    assert metadata["zip_size_bytes"] == (out / "results.zip").stat().st_size
    assert metadata["delivered_at"]


def test_over_the_cap_fails_the_delivery_and_pushes_nothing(backend_api, remote, artifacts, tmp_path):
    with pytest.raises(ValueError, match="over the 10 byte limit"):
        deliver(backend_api, remote, artifacts, max_zip_bytes=10)

    fields = patched_fields(backend_api)
    assert fields["status"] == "FAILED"
    assert fields["attempts"] == 1
    assert "over the 10 byte limit" in fields["error"]
    assert git("rev-list", "--count", "main", cwd=remote) == "1"


def test_a_git_failure_marks_the_row_failed_and_raises(backend_api, tmp_path, artifacts):
    with pytest.raises(RuntimeError, match="git clone failed"):
        deliver(backend_api, tmp_path / "missing.git", artifacts)

    fields = patched_fields(backend_api)
    assert fields["status"] == "FAILED"
    assert fields["error"].startswith("RuntimeError: git clone failed")


def test_missing_artifacts_fail_the_delivery(backend_api, remote, tmp_path):
    with pytest.raises(FileNotFoundError):
        deliver(backend_api, remote, tmp_path / "nowhere")

    assert patched_fields(backend_api)["status"] == "FAILED"


def test_a_task_without_a_pull_request_fails_the_delivery(backend_api, remote, artifacts):
    backend_api.get_pull_requests.return_value = []

    with pytest.raises(LookupError):
        deliver(backend_api, remote, artifacts)

    assert patched_fields(backend_api)["status"] == "FAILED"


def test_a_delivered_row_is_left_alone(backend_api, remote, artifacts):
    backend_api.create_task_result.return_value = TaskResult(
        id=9, type="PR", task_id=7, results_repository_id=5, status="DELIVERED", attempts=1,
    )

    deliver(backend_api, remote, artifacts)

    backend_api.patch_task_result.assert_not_called()
    assert git("rev-list", "--count", "main", cwd=remote) == "1"


def test_a_retry_after_a_failure_delivers_and_counts_the_attempt(backend_api, remote, artifacts, git_apis):
    backend_api.create_task_result.return_value = TaskResult(
        id=9, type="PR", task_id=7, results_repository_id=5, status="FAILED", attempts=1, error="boom",
    )

    deliver(backend_api, remote, artifacts, git_apis)

    fields = patched_fields(backend_api)
    assert (fields["status"], fields["attempts"], fields["error"]) == ("DELIVERED", 2, None)


def test_the_pull_request_is_opened_into_the_default_branch_and_recorded(backend_api, remote, artifacts, git_api, git_apis):
    deliver(backend_api, remote, artifacts, git_apis)

    git_apis.for_repository.assert_called_once_with(REPOSITORY)
    git_api.find_pull_request_by_branch.assert_called_once_with("fn/results", BRANCH, "main")
    repo_path, head, base, title, _ = git_api.create_pull_request.call_args.args
    assert (repo_path, head, base) == ("fn/results", BRANCH, "main")
    assert title == "fn/analysis PR12 - task 7 - results"
    fields = patched_fields(backend_api)
    assert fields["status"] == "DELIVERED"
    assert fields["pull_request_number"] == 3
    assert fields["pull_request_url"] == "http://gitea/fn/results/pulls/3"
    assert fields["pull_request_state"] == "OPEN"


def test_a_pull_request_failure_fails_the_row_with_the_branch_recorded(backend_api, remote, artifacts, git_api, git_apis):
    git_api.create_pull_request.side_effect = RuntimeError("provider down")

    with pytest.raises(RuntimeError, match="provider down"):
        deliver(backend_api, remote, artifacts, git_apis)

    fields = patched_fields(backend_api)
    assert fields["status"] == "FAILED"
    assert fields["error"] == "RuntimeError: provider down"
    assert fields["branch"] == BRANCH
    assert fields["commit_sha"] == git("rev-parse", BRANCH, cwd=remote)
    assert "pull_request_number" not in fields


def test_a_retry_skips_the_push_of_a_pushed_branch_and_opens_its_pull_request(
    backend_api, remote, artifacts, git_api, git_apis
):
    git_api.create_pull_request.side_effect = RuntimeError("provider down")
    with pytest.raises(RuntimeError):
        deliver(backend_api, remote, artifacts, git_apis)
    pushed_sha = git("rev-parse", BRANCH, cwd=remote)
    backend_api.create_task_result.return_value = TaskResult(
        id=9, type="PR", task_id=7, results_repository_id=5, status="FAILED", attempts=1, error="boom",
        branch=BRANCH, commit_sha=pushed_sha,
    )
    git_api.create_pull_request.side_effect = None

    deliver(backend_api, remote, artifacts, git_apis)

    fields = patched_fields(backend_api)
    assert (fields["status"], fields["attempts"], fields["error"]) == ("DELIVERED", 2, None)
    assert (fields["branch"], fields["commit_sha"]) == (BRANCH, pushed_sha)
    assert git("rev-list", "--count", f"main..{BRANCH}", cwd=remote) == "1"
    assert fields["pull_request_number"] == 3


def test_a_retry_records_the_pull_request_an_earlier_attempt_opened(backend_api, remote, artifacts, git_api, git_apis):
    git_api.find_pull_request_by_branch.return_value = {**RESULTS_PR, "state": "closed", "merged_at": "2026-10-08T10:00:00Z"}

    deliver(backend_api, remote, artifacts, git_apis)

    git_api.create_pull_request.assert_not_called()
    fields = patched_fields(backend_api)
    assert (fields["status"], fields["pull_request_number"], fields["pull_request_state"]) == ("DELIVERED", 3, "MERGED")


def test_the_token_stays_out_of_the_command_line():
    env = git_push.auth_env("secret-token")

    assert env["GIT_CONFIG_KEY_0"] == "http.extraHeader"
    assert git_push.clone_url("gitea.fn.svc:3000/fn/results", "http://gitea.fn.svc:3000/api/v1") == (
        "http://gitea.fn.svc:3000/fn/results.git"
    )
    assert "secret-token" not in git_push.clone_url("h/o/r", "https://api.x/v1")


def test_the_sensor_requests_a_delivery_run_for_a_successful_task_run():
    run = MagicMock(tags={"trigger": "task", "task_id": "7", "attempt": "2"})
    context = MagicMock(dagster_run=run)

    result = task_results_delivery_sensor._run_status_sensor_fn(context)

    assert result.run_key == "deliver/7/2"
    assert result.tags == {"trigger": "delivery", "delivery_task_id": "7"}
    assert result.run_config == {"ops": {"deliver_results": {"config": {"task_id": 7}}}}


def test_the_sensor_ignores_runs_that_are_not_task_runs():
    context = MagicMock(dagster_run=MagicMock(tags={"trigger": "delivery", "delivery_task_id": "7"}))

    assert task_results_delivery_sensor._run_status_sensor_fn(context) is None


def test_the_sensor_defaults_to_stopped_and_targets_the_delivery_job():
    assert task_results_delivery_sensor.default_status == dg.DefaultSensorStatus.STOPPED
    assert task_results_delivery_sensor in SENSORS
    assert deliver_results_job in JOBS
