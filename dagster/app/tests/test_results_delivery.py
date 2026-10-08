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
from app.models import PullRequestResult, PullRequestTrigger, ResultsRepository, Task, TriggerRepository
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
PULL_REQUEST = PullRequestTrigger(
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


def result(**fields):
    return PullRequestResult(**{
        "id": 9, "type": "PR", "task_id": 7, "results_repository_id": 5, "state": "UNKNOWN", "attempts": 0,
        **fields,
    })


@pytest.fixture
def backend_api():
    api = MagicMock()
    api.get_task.return_value = TASK
    api.get_results_repository.return_value = REPOSITORY
    api.get_repositories.return_value = [TRIGGER_REPOSITORY]
    api.get_pull_requests.return_value = [PULL_REQUEST]
    api.create_result.return_value = result()
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


def patches(backend_api):
    """The fields of each patch of the result, in order."""
    calls = backend_api.patch_result.call_args_list
    assert {c.args[0] for c in calls} <= {9}
    return [c.args[1] for c in calls]


def test_success_pushes_a_branch_with_the_layout_and_records_pushed_then_opened(
    backend_api, remote, artifacts, tmp_path, git_apis
):
    provider = deliver(backend_api, remote, artifacts, git_apis)

    provider.return_value.get.assert_called_once_with(SAMPLE_SECRET["key"], "fn", "TOKEN")
    check = tmp_path / "check"
    git("clone", "--branch", BRANCH, str(remote), str(check), cwd=tmp_path)
    commit_sha = git("rev-parse", "HEAD", cwd=check)
    pushed, opened = patches(backend_api)
    assert pushed == {"state": "PUSHED", "branch": BRANCH, "commit_sha": commit_sha}
    assert opened == {
        "state": "OPENED", "attempts": 1, "error": None, "number": 3, "url": "http://gitea/fn/results/pulls/3",
        "merged_at": None, "merge_commit_sha": None,
    }
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
    assert metadata["number"] == 12
    assert metadata["zip_size_bytes"] == (out / "results.zip").stat().st_size
    assert metadata["delivered_at"]


def test_pushed_is_recorded_before_the_pull_request_is_opened(backend_api, remote, artifacts, git_api, git_apis):
    def open_pull_request(*args):
        assert patches(backend_api)[-1]["state"] == "PUSHED"
        return RESULTS_PR
    git_api.create_pull_request.side_effect = open_pull_request

    deliver(backend_api, remote, artifacts, git_apis)

    assert [fields["state"] for fields in patches(backend_api)] == ["PUSHED", "OPENED"]


def test_over_the_cap_fails_the_delivery_and_pushes_nothing(backend_api, remote, artifacts, tmp_path):
    with pytest.raises(ValueError, match="over the 10 byte limit"):
        deliver(backend_api, remote, artifacts, max_zip_bytes=10)

    (fields,) = patches(backend_api)
    assert "state" not in fields
    assert fields["attempts"] == 1
    assert "over the 10 byte limit" in fields["error"]
    assert git("rev-list", "--count", "main", cwd=remote) == "1"


def test_a_git_failure_records_the_error_and_raises(backend_api, tmp_path, artifacts):
    with pytest.raises(RuntimeError, match="git clone failed"):
        deliver(backend_api, tmp_path / "missing.git", artifacts)

    (fields,) = patches(backend_api)
    assert "state" not in fields
    assert fields["error"].startswith("RuntimeError: git clone failed")


def test_missing_artifacts_fail_the_delivery(backend_api, remote, tmp_path):
    with pytest.raises(FileNotFoundError):
        deliver(backend_api, remote, tmp_path / "nowhere")

    (fields,) = patches(backend_api)
    assert fields["error"].startswith("FileNotFoundError")


def test_a_task_without_a_pull_request_fails_the_delivery(backend_api, remote, artifacts):
    backend_api.get_pull_requests.return_value = []

    with pytest.raises(LookupError):
        deliver(backend_api, remote, artifacts)

    (fields,) = patches(backend_api)
    assert fields["error"].startswith("LookupError")


@pytest.mark.parametrize("state", ["OPENED", "MERGED", "CLOSED"])
def test_a_result_past_pushed_is_left_alone(backend_api, remote, artifacts, state):
    backend_api.create_result.return_value = result(state=state, attempts=1)

    deliver(backend_api, remote, artifacts)

    backend_api.patch_result.assert_not_called()
    assert git("rev-list", "--count", "main", cwd=remote) == "1"


def test_a_retry_after_a_failure_delivers_and_counts_the_attempt(backend_api, remote, artifacts, git_apis):
    backend_api.create_result.return_value = result(attempts=1, error="boom")

    deliver(backend_api, remote, artifacts, git_apis)

    opened = patches(backend_api)[-1]
    assert (opened["state"], opened["attempts"], opened["error"]) == ("OPENED", 2, None)


def test_the_pull_request_is_opened_into_the_default_branch_and_recorded(backend_api, remote, artifacts, git_api, git_apis):
    deliver(backend_api, remote, artifacts, git_apis)

    git_apis.for_repository.assert_called_once_with(REPOSITORY)
    git_api.find_pull_request_by_branch.assert_called_once_with("fn/results", BRANCH, "main")
    repo_path, head, base, title, _ = git_api.create_pull_request.call_args.args
    assert (repo_path, head, base) == ("fn/results", BRANCH, "main")
    assert title == "fn/analysis PR12 - task 7 - results"
    opened = patches(backend_api)[-1]
    assert opened["state"] == "OPENED"
    assert opened["number"] == 3
    assert opened["url"] == "http://gitea/fn/results/pulls/3"
    assert (opened["merged_at"], opened["merge_commit_sha"]) == (None, None)


def test_a_pull_request_failure_keeps_the_state_pushed_with_the_branch_recorded(
    backend_api, remote, artifacts, git_api, git_apis
):
    git_api.create_pull_request.side_effect = RuntimeError("provider down")

    with pytest.raises(RuntimeError, match="provider down"):
        deliver(backend_api, remote, artifacts, git_apis)

    pushed, failed = patches(backend_api)
    assert pushed["state"] == "PUSHED"
    assert "state" not in failed
    assert (failed["attempts"], failed["error"]) == (1, "RuntimeError: provider down")
    assert failed["branch"] == BRANCH
    assert failed["commit_sha"] == git("rev-parse", BRANCH, cwd=remote)
    assert "number" not in failed


def test_a_retry_from_pushed_skips_the_push_and_opens_its_pull_request(
    backend_api, remote, artifacts, git_api, git_apis
):
    git_api.create_pull_request.side_effect = RuntimeError("provider down")
    with pytest.raises(RuntimeError):
        deliver(backend_api, remote, artifacts, git_apis)
    pushed_sha = git("rev-parse", BRANCH, cwd=remote)
    backend_api.create_result.return_value = result(
        state="PUSHED", attempts=1, error="boom", branch=BRANCH, commit_sha=pushed_sha,
    )
    backend_api.patch_result.reset_mock()
    git_api.create_pull_request.side_effect = None

    deliver(backend_api, remote, artifacts, git_apis)

    pushed, opened = patches(backend_api)
    assert pushed == {"state": "PUSHED", "branch": BRANCH, "commit_sha": pushed_sha}
    assert (opened["state"], opened["attempts"], opened["error"], opened["number"]) == ("OPENED", 2, None, 3)
    assert git("rev-list", "--count", f"main..{BRANCH}", cwd=remote) == "1"


def test_a_retry_records_the_pull_request_an_earlier_attempt_opened(backend_api, remote, artifacts, git_api, git_apis):
    backend_api.create_result.return_value = result(state="PUSHED", attempts=1)
    git_api.find_pull_request_by_branch.return_value = RESULTS_PR

    deliver(backend_api, remote, artifacts, git_apis)

    git_api.create_pull_request.assert_not_called()
    opened = patches(backend_api)[-1]
    assert (opened["state"], opened["number"]) == ("OPENED", 3)


def test_a_retry_records_the_merge_of_a_pull_request_merged_before_it(backend_api, remote, artifacts, git_api, git_apis):
    git_api.find_pull_request_by_branch.return_value = {
        **RESULTS_PR, "state": "closed", "merged_at": "2026-10-08T10:00:00Z", "merge_commit_sha": "def",
    }

    deliver(backend_api, remote, artifacts, git_apis)

    git_api.create_pull_request.assert_not_called()
    merged = patches(backend_api)[-1]
    assert (merged["state"], merged["number"]) == ("MERGED", 3)
    assert (merged["merged_at"], merged["merge_commit_sha"]) == ("2026-10-08T10:00:00Z", "def")


def test_a_retry_records_a_pull_request_closed_before_it(backend_api, remote, artifacts, git_api, git_apis):
    git_api.find_pull_request_by_branch.return_value = {**RESULTS_PR, "state": "closed", "merge_commit_sha": "x"}

    deliver(backend_api, remote, artifacts, git_apis)

    closed = patches(backend_api)[-1]
    assert (closed["state"], closed["merged_at"], closed["merge_commit_sha"]) == ("CLOSED", None, None)


def test_an_open_pull_request_records_no_github_test_merge_sha(backend_api, remote, artifacts, git_api, git_apis):
    git_api.create_pull_request.return_value = {**RESULTS_PR, "merge_commit_sha": "test-merge"}

    deliver(backend_api, remote, artifacts, git_apis)

    assert patches(backend_api)[-1]["merge_commit_sha"] is None


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
