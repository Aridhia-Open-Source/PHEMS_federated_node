import json
import re
import subprocess
import zipfile
from unittest.mock import MagicMock, patch

import dagster as dg
import pytest
import requests

from app.config import ResultsDeliveryConfig
from app.definitions.sensors.task import JOBS, SENSORS
from app.definitions.sensors.task import delivery as delivery_sensors
from app.definitions.sensors.task.delivery import (
    ResultsDeliveryRetrySensor,
    deliver_results_job,
    results_delivery_retry_sensor,
    task_results_delivery_sensor,
)
from app.delivery import git_push
from app.delivery.results import ResultsDelivery
from app.models import (
    GitProvider, Project, PullRequestResult, ResultsRepository, Secret, Task, TaskTrigger,
    TriggerRepositoryRef,
)
from app.tests.conftest import SAMPLE_SECRET

RUN_ID = "run-1"
TASK = Task(
    id=7, name="t", spec={"image": "img", "dataset_id": None, "env": {}}, attempt=1, requested_by="u",
    project_id=1, trigger_id=3, executor_run_id="stale-run",
)
GLOBAL_REPOSITORY = ResultsRepository(
    id=2, uri="http://gitea.fn.svc:3000/fn/results", repo_path="fn/results",
    provider=GitProvider(
        id=1, name="gitea", type="gitea", uri="http://gitea.fn.svc:3000", api_uri="http://gitea.fn.svc:3000/api/v1",
        enabled=True,
    ),
    secret=SAMPLE_SECRET, enabled=True,
)
CONFIG = {
    "current": True, "changes": [], "config_hash": "h",
    "config_snapshot": {"version": 1, "results": {
        "repository_id": 2, "repository": "http://gitea.fn.svc:3000/fn/results",
        "api_uri": "http://gitea.fn.svc:3000/api/v1", "target_dir": "/results/",
    }, "dataset": None},
}
TRIGGER_REPOSITORY = TriggerRepositoryRef(id=2, repo_path="fn/analysis", uri="gitea.fn.svc:3000/fn/analysis")
PULL_REQUEST = TaskTrigger(
    project_id=1, trigger_repository_id=2, number=12, title="t", raised_by="u", merged_at="2026-01-01T00:00:00Z",
    merge_commit_sha="abc", state="YIELDED", task_id=7, spec_files=["spec.json"], trigger_repository=TRIGGER_REPOSITORY,
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
        "id": 9, "type": "PR", "task_id": 7, "project_id": 1, "results_repository_id": 5, "step": "UNKNOWN",
        "state": "IN_PROGRESS", "attempts": 0,
        **fields,
    })


@pytest.fixture
def backend_api():
    api = MagicMock()
    api.get_task.return_value = TASK
    api.get_task_config.return_value = CONFIG
    api.get_global_results_repository.return_value = GLOBAL_REPOSITORY
    api.get_task_trigger.return_value = PULL_REQUEST
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
    with patch("app.secrets.SecretProvider") as provider, \
            patch.object(git_push, "clone_url", return_value=str(remote)):
        provider.return_value.get.return_value = "tok"
        ResultsDelivery(backend_api, git_apis or MagicMock(), config, MagicMock())(1, 7, RUN_ID)
    return provider


def patches(backend_api):
    """The fields of each patch of the result, in order."""
    calls = backend_api.patch_result.call_args_list
    assert {c.args[:2] for c in calls} <= {(1, 9)}
    return [c.args[2] for c in calls]


def test_success_pushes_a_branch_with_the_layout_and_records_pushed_then_opened(
    backend_api, remote, artifacts, tmp_path, git_apis
):
    provider = deliver(backend_api, remote, artifacts, git_apis)

    provider.return_value.get.assert_called_once_with(SAMPLE_SECRET["key"], "fn", "TOKEN")
    check = tmp_path / "check"
    git("clone", "--branch", BRANCH, str(remote), str(check), cwd=tmp_path)
    commit_sha = git("rev-parse", "HEAD", cwd=check)
    pushed, opened = patches(backend_api)
    assert pushed == {"step": "PUSHED", "branch": BRANCH, "commit_sha": commit_sha}
    assert opened == {
        "step": "OPENED", "state": "DELIVERED", "attempts": 1, "error": None, "number": 3, "url": "http://gitea/fn/results/pulls/3",
        "merged_at": None, "merge_commit_sha": None,
    }
    out = check / LAYOUT
    with zipfile.ZipFile(out / "results.zip") as zf:
        assert sorted(zf.namelist()) == ["out.txt", "sub/b.csv"]
    assert json.loads((out / "spec.json").read_text()) == {"image": "img", "dataset_id": None, "env": {}}
    assert git("rev-list", "--count", "main", cwd=remote) == "1"
    metadata = json.loads((out / "metadata.json").read_text())
    assert metadata["branch"] == BRANCH
    assert metadata["merge_commit_sha"] == "abc"
    assert metadata["task_id"] == 7
    assert metadata["executor_run_id"] == RUN_ID
    assert metadata["trigger_repository_uri"] == TRIGGER_REPOSITORY.uri
    assert metadata["number"] == 12
    assert metadata["zip_size_bytes"] == (out / "results.zip").stat().st_size
    assert metadata["delivered_at"]


def test_pushed_is_recorded_before_the_pull_request_is_opened(backend_api, remote, artifacts, git_api, git_apis):
    def open_pull_request(*args):
        assert patches(backend_api)[-1]["step"] == "PUSHED"
        return RESULTS_PR
    git_api.create_pull_request.side_effect = open_pull_request

    deliver(backend_api, remote, artifacts, git_apis)

    assert [fields["step"] for fields in patches(backend_api)] == ["PUSHED", "OPENED"]


def test_over_the_cap_fails_the_delivery_and_pushes_nothing(backend_api, remote, artifacts, tmp_path):
    with pytest.raises(ValueError, match="over the 10 byte limit"):
        deliver(backend_api, remote, artifacts, max_zip_bytes=10)

    (fields,) = patches(backend_api)
    assert (fields["state"], "step" in fields) == ("FAILED", False)
    assert fields["attempts"] == 1
    assert "over the 10 byte limit" in fields["error"]
    assert git("rev-list", "--count", "main", cwd=remote) == "1"


def test_a_git_failure_records_the_error_and_raises(backend_api, tmp_path, artifacts):
    with pytest.raises(RuntimeError, match="git clone failed"):
        deliver(backend_api, tmp_path / "missing.git", artifacts)

    (fields,) = patches(backend_api)
    assert (fields["state"], "step" in fields) == ("FAILED", False)
    assert fields["error"].startswith("RuntimeError: git clone failed")


def test_missing_artifacts_fail_the_delivery(backend_api, remote, tmp_path):
    with pytest.raises(FileNotFoundError):
        deliver(backend_api, remote, tmp_path / "nowhere")

    (fields,) = patches(backend_api)
    assert fields["error"].startswith("FileNotFoundError")


def test_a_task_without_a_pull_request_fails_the_delivery(backend_api, remote, artifacts):
    backend_api.get_task_trigger.side_effect = requests.HTTPError(response=MagicMock(status_code=404))

    with pytest.raises(requests.HTTPError):
        deliver(backend_api, remote, artifacts)

    (fields,) = patches(backend_api)
    assert fields["error"].startswith("HTTPError")


def test_delivery_takes_the_target_dir_from_the_pinned_configuration_and_reads_no_resource(
    backend_api, remote, artifacts, git_apis
):
    deliver(backend_api, remote, artifacts, git_apis)

    backend_api.get_task_config.assert_called_once_with(1, 7)
    backend_api.create_result.assert_called_once_with(1, 7, 2)
    backend_api.get_global_results_repository.assert_called_once_with(2)
    assert not backend_api.get_results_repository.called
    assert not backend_api.get_results_repository_by_id.called


@pytest.mark.parametrize("gone", ["get_task", "get_task_config", "create_result", "get_global_results_repository"])
def test_a_404_is_final_logged_and_never_raised(backend_api, remote, artifacts, gone):
    response = MagicMock(status_code=404, text="not found")
    getattr(backend_api, gone).side_effect = requests.HTTPError(response=response)

    deliver(backend_api, remote, artifacts)

    backend_api.patch_result.assert_not_called()
    assert git("rev-list", "--count", "main", cwd=remote) == "1"


@pytest.mark.parametrize("step, error", [
    ("REVOKED", "results repository resource revoked"),
    ("STALE", "task configuration changed since the task was created: image changed"),
])
def test_a_result_the_backend_created_as_final_without_delivery_is_left_alone(backend_api, remote, artifacts, step, error):
    backend_api.create_result.return_value = result(step=step, state="FAILED", error=error)

    deliver(backend_api, remote, artifacts)

    backend_api.patch_result.assert_not_called()
    assert git("rev-list", "--count", "main", cwd=remote) == "1"


def test_a_result_just_recorded_as_switched_off_counts_an_attempt_and_waits_for_the_retry_sensor(
    backend_api, remote, artifacts
):
    backend_api.create_result.return_value = result(state="FAILED", error="results resource switched off")

    deliver(backend_api, remote, artifacts)

    assert patches(backend_api) == [{"attempts": 1}]
    backend_api.get_global_results_repository.assert_not_called()


def test_the_pull_request_is_found_with_one_call(backend_api, remote, artifacts, git_apis):
    deliver(backend_api, remote, artifacts, git_apis)

    assert patches(backend_api)[-1]["state"] == "DELIVERED"
    backend_api.get_task_trigger.assert_called_once_with(1, 7)


@pytest.mark.parametrize("step", ["OPENED", "MERGED", "CLOSED"])
def test_a_result_past_pushed_is_left_alone(backend_api, remote, artifacts, step):
    backend_api.create_result.return_value = result(step=step, state="DELIVERED", attempts=1)

    deliver(backend_api, remote, artifacts)

    backend_api.patch_result.assert_not_called()
    assert git("rev-list", "--count", "main", cwd=remote) == "1"


def test_a_retry_after_a_failure_delivers_and_counts_the_attempt(backend_api, remote, artifacts, git_apis):
    backend_api.create_result.return_value = result(attempts=1, error="boom", state="FAILED")

    deliver(backend_api, remote, artifacts, git_apis)

    relaunched, *_, opened = patches(backend_api)
    assert relaunched == {"state": "IN_PROGRESS"}
    assert (opened["step"], opened["state"], opened["attempts"], opened["error"]) == ("OPENED", "DELIVERED", 2, None)


def test_the_pull_request_is_opened_into_the_default_branch_and_recorded(backend_api, remote, artifacts, git_api, git_apis):
    deliver(backend_api, remote, artifacts, git_apis)

    git_apis.for_repository.assert_called_once_with(GLOBAL_REPOSITORY)
    git_api.find_pull_request_by_branch.assert_called_once_with("fn/results", BRANCH, "main")
    repo_path, head, base, title, _ = git_api.create_pull_request.call_args.args
    assert (repo_path, head, base) == ("fn/results", BRANCH, "main")
    assert title == "fn/analysis PR12 - task 7 - results"
    opened = patches(backend_api)[-1]
    assert (opened["step"], opened["state"]) == ("OPENED", "DELIVERED")
    assert opened["number"] == 3
    assert opened["url"] == "http://gitea/fn/results/pulls/3"
    assert (opened["merged_at"], opened["merge_commit_sha"]) == (None, None)


def test_a_pull_request_failure_keeps_the_step_pushed_and_fails_the_state_with_the_branch_recorded(
    backend_api, remote, artifacts, git_api, git_apis
):
    git_api.create_pull_request.side_effect = RuntimeError("provider down")

    with pytest.raises(RuntimeError, match="provider down"):
        deliver(backend_api, remote, artifacts, git_apis)

    pushed, failed = patches(backend_api)
    assert pushed["step"] == "PUSHED"
    assert (failed["state"], "step" in failed) == ("FAILED", False)
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
        step="PUSHED", state="FAILED", attempts=1, error="boom", branch=BRANCH, commit_sha=pushed_sha,
    )
    backend_api.patch_result.reset_mock()
    git_api.create_pull_request.side_effect = None

    deliver(backend_api, remote, artifacts, git_apis)

    relaunched, pushed, opened = patches(backend_api)
    assert relaunched == {"state": "IN_PROGRESS"}
    assert pushed == {"step": "PUSHED", "branch": BRANCH, "commit_sha": pushed_sha}
    assert (opened["step"], opened["attempts"], opened["error"], opened["number"]) == ("OPENED", 2, None, 3)
    assert git("rev-list", "--count", f"main..{BRANCH}", cwd=remote) == "1"


def test_a_retry_records_the_pull_request_an_earlier_attempt_opened(backend_api, remote, artifacts, git_api, git_apis):
    backend_api.create_result.return_value = result(step="PUSHED", attempts=1)
    git_api.find_pull_request_by_branch.return_value = RESULTS_PR

    deliver(backend_api, remote, artifacts, git_apis)

    git_api.create_pull_request.assert_not_called()
    opened = patches(backend_api)[-1]
    assert (opened["step"], opened["number"]) == ("OPENED", 3)


def test_a_retry_records_the_merge_of_a_pull_request_merged_before_it(backend_api, remote, artifacts, git_api, git_apis):
    git_api.find_pull_request_by_branch.return_value = {
        **RESULTS_PR, "state": "closed", "merged_at": "2026-10-08T10:00:00Z", "merge_commit_sha": "def",
    }

    deliver(backend_api, remote, artifacts, git_apis)

    git_api.create_pull_request.assert_not_called()
    merged = patches(backend_api)[-1]
    assert (merged["step"], merged["state"], merged["number"]) == ("MERGED", "DELIVERED", 3)
    assert (merged["merged_at"], merged["merge_commit_sha"]) == ("2026-10-08T10:00:00Z", "def")


def test_a_retry_records_a_pull_request_closed_before_it(backend_api, remote, artifacts, git_api, git_apis):
    git_api.find_pull_request_by_branch.return_value = {**RESULTS_PR, "state": "closed", "merge_commit_sha": "x"}

    deliver(backend_api, remote, artifacts, git_apis)

    closed = patches(backend_api)[-1]
    assert (closed["step"], closed["merged_at"], closed["merge_commit_sha"]) == ("CLOSED", None, None)


def test_an_open_pull_request_records_no_github_test_merge_sha(backend_api, remote, artifacts, git_api, git_apis):
    git_api.create_pull_request.return_value = {**RESULTS_PR, "merge_commit_sha": "test-merge"}

    deliver(backend_api, remote, artifacts, git_apis)

    assert patches(backend_api)[-1]["merge_commit_sha"] is None


def test_the_token_stays_out_of_the_command_line():
    env = git_push.auth_env("secret-token")

    assert env["GIT_CONFIG_KEY_0"] == "http.extraHeader"
    assert git_push.clone_url("http://gitea.fn.svc:3000", "fn/results") == "http://gitea.fn.svc:3000/fn/results.git"
    assert "secret-token" not in git_push.clone_url("https://h", "o/r")


def test_the_sensor_requests_a_delivery_run_for_a_successful_task_run():
    run = MagicMock(tags={"trigger": "task", "task_id": "7", "attempt": "2", "project_id": "1"}, run_id=RUN_ID)
    context = MagicMock(dagster_run=run)

    result = task_results_delivery_sensor._run_status_sensor_fn(context)

    assert result.run_key == "deliver/7/2"
    assert result.tags == {"trigger": "delivery", "delivery_task_id": "7"}
    assert result.run_config == {"ops": {"deliver_results": {"config": {"project_id": 1, "task_id": 7, "run_id": RUN_ID}}}}


def test_a_hung_git_command_fails_with_a_timeout():
    with patch.object(subprocess, "run", side_effect=subprocess.TimeoutExpired("git", 60)) as run:
        with pytest.raises(RuntimeError, match="git clone timed out after 60s"):
            git_push.git(["clone", "url"])

    assert run.call_args.kwargs["timeout"] == git_push.GIT_TIMEOUT_SECONDS


def test_the_sensor_ignores_runs_that_are_not_task_runs():
    context = MagicMock(dagster_run=MagicMock(tags={"trigger": "delivery", "delivery_task_id": "7"}))

    assert task_results_delivery_sensor._run_status_sensor_fn(context) is None


def test_the_sensor_defaults_to_stopped_and_targets_the_delivery_job():
    assert task_results_delivery_sensor.default_status == dg.DefaultSensorStatus.STOPPED
    assert task_results_delivery_sensor in SENSORS
    assert deliver_results_job in JOBS


def test_a_refused_result_is_skipped_not_failed(backend_api, remote, artifacts):
    response = MagicMock(status_code=409, text="Task 7 is RUNNING, only a SUCCESS task has results")
    backend_api.create_result.side_effect = requests.HTTPError(response=response)

    deliver(backend_api, remote, artifacts)

    backend_api.patch_result.assert_not_called()


def test_any_other_result_error_raises(backend_api, remote, artifacts):
    backend_api.create_result.side_effect = requests.HTTPError(response=MagicMock(status_code=500))

    with pytest.raises(requests.HTTPError):
        deliver(backend_api, remote, artifacts)


def test_a_disabled_secret_fails_the_delivery_before_its_token_is_read(backend_api, remote, artifacts):
    disabled = SAMPLE_SECRET | {"enabled": False}
    global_repository = GLOBAL_REPOSITORY.model_copy(update={"secret": Secret(**disabled)})
    backend_api.get_global_results_repository.return_value = global_repository

    with pytest.raises(PermissionError):
        deliver(backend_api, remote, artifacts)

    (fields,) = patches(backend_api)
    assert fields["state"] == "FAILED" and fields["error"].startswith("PermissionError")


def retry_sensor(results, tasks=None, in_flight=False):
    backend_api = MagicMock()
    backend_api.get_projects.return_value = [Project(id=1, name="p")]
    backend_api.get_results_by_state.return_value = results
    backend_api.get_task.side_effect = lambda project_id, task_id: MagicMock(executor_run_id=f"run-{task_id}")
    context = MagicMock()
    context.instance.get_runs.return_value = [MagicMock()] if in_flight else []
    return list(ResultsDeliveryRetrySensor(context=context, backend_api=backend_api)()), backend_api, context


def test_the_retry_sensor_relaunches_a_failed_delivery_with_its_task_run():
    requests_, backend_api, context = retry_sensor([result(state="FAILED", step="PUSHED", attempts=2)])

    (request,) = requests_
    assert re.fullmatch(r"deliver-retry/9/\d+", request.run_key)
    assert request.tags == {"trigger": "delivery", "delivery_task_id": "7"}
    assert request.run_config == {"ops": {"deliver_results": {"config": {
        "project_id": 1, "task_id": 7, "run_id": "run-7"
    }}}}
    backend_api.get_results_by_state.assert_called_once_with(1, "FAILED", active_resource=True)
    backend_api.get_task.assert_called_once_with(1, 7)
    assert context.instance.get_runs.call_args.kwargs["filters"].job_name == "deliver_results_job"


@pytest.mark.parametrize("step", ["OPENED", "MERGED", "CLOSED", "REVOKED", "STALE"])
def test_the_retry_sensor_ignores_final_steps(step):
    (skip,), _, _ = retry_sensor([result(state="FAILED", step=step)])

    assert isinstance(skip, dg.SkipReason)


def test_the_retry_sensor_gives_up_at_the_max_attempts(monkeypatch):
    monkeypatch.setattr(delivery_sensors, "DELIVERY_MAX_ATTEMPTS", 3)

    (request,), _, _ = retry_sensor([result(state="FAILED", attempts=2)])
    (skip,), _, _ = retry_sensor([result(state="FAILED", attempts=3)])

    assert isinstance(request, dg.RunRequest) and isinstance(skip, dg.SkipReason)


def test_the_retry_sensor_skips_a_delivery_in_flight():
    (skip,), backend_api, _ = retry_sensor([result(state="FAILED")], in_flight=True)

    assert isinstance(skip, dg.SkipReason)
    backend_api.get_task.assert_not_called()


def test_the_retry_run_key_does_not_change_with_the_attempts():
    first, _, _ = retry_sensor([result(state="FAILED", attempts=1)])
    second, _, _ = retry_sensor([result(state="FAILED", attempts=2)])

    assert first[0].run_key == second[0].run_key


def test_the_retry_sensor_is_registered_stopped_by_default():
    assert results_delivery_retry_sensor.default_status == dg.DefaultSensorStatus.STOPPED
    assert results_delivery_retry_sensor in SENSORS
