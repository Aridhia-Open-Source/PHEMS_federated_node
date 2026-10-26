import re
from unittest.mock import MagicMock

import dagster as dg
import pytest

from app.definitions.sensors.base import IN_FLIGHT
from app.definitions.sensors.git.pr_evaluate import PullRequestEvaluateSensor
from app.models import Project, TriggerState


def project(id, enabled=True):
    return Project(id=id, name=f"proj{id}", enabled=enabled)


def repo(id, project_id):
    return MagicMock(project_id=project_id, trigger_repository=MagicMock(id=id))


def unknown_prs(*numbers):
    return [MagicMock(number=n) for n in numbers]


def run(projects, repos, unknown=None, in_flight=()):
    backend_api = MagicMock()
    # The backend filters the projects
    backend_api.get_projects.side_effect = lambda enabled: [p for p in projects if p.enabled == enabled]
    backend_api.get_project_trigger_repositories.side_effect = lambda project_id, active: [
        r for r in repos if r.project_id == project_id
    ]
    backend_api.get_pull_requests.side_effect = lambda project_id, repo_id, state: (unknown or {}).get(repo_id, [])
    context = MagicMock()
    context.instance.get_runs.side_effect = lambda filters, limit: [MagicMock()] if filters.tags["repo_id"] in in_flight else []
    sensor = PullRequestEvaluateSensor(context=context, backend_api=backend_api, git_apis=MagicMock())
    return list(sensor()), backend_api, context


def test_one_run_per_repository_with_unknown_prs():
    result, backend_api, _ = run(
        [project(1)], [repo(10, 1), repo(11, 1), repo(12, 1)], unknown={10: unknown_prs(1, 2), 12: unknown_prs(3)}
    )

    assert [r.tags["repo_id"] for r in result] == ["10", "12"]
    assert all(isinstance(r, dg.RunRequest) for r in result)
    backend_api.get_pull_requests.assert_any_call(1, 10, state=TriggerState.UNKNOWN.value)


def test_the_run_is_configured_and_tagged_for_its_repository():
    result, _, _ = run([project(3)], [repo(10, 3)], unknown={10: unknown_prs(1)})

    assert result[0].tags == {"repo_id": "10", "project_id": "3"}
    assert result[0].run_config == {"ops": {"load_unknown_pull_requests": {"config": {"project_id": 3, "repo_id": 10}}}}


def test_the_run_key_is_the_resource_the_newest_unknown_pr_and_the_retry_slot():
    result, _, _ = run([project(1)], [repo(10, 1)], unknown={10: unknown_prs(4, 9, 6)})

    assert re.fullmatch(r"evaluate/1/10/9/\d+", result[0].run_key)


def test_a_newer_unknown_pr_gives_a_new_run_key():
    old, _, _ = run([project(1)], [repo(10, 1)], unknown={10: unknown_prs(4)})
    new, _, _ = run([project(1)], [repo(10, 1)], unknown={10: unknown_prs(4, 5)})

    assert old[0].run_key != new[0].run_key


def test_only_enabled_projects_are_evaluated():
    result, _, _ = run(
        [project(1, enabled=False), project(2)], [repo(10, 1), repo(11, 2)], unknown={10: unknown_prs(1), 11: unknown_prs(1)}
    )

    assert [r.tags["repo_id"] for r in result] == ["11"]


def test_only_enabled_projects_and_active_assignments_are_requested():
    _, backend_api, _ = run([project(1)], [repo(10, 1)], unknown={10: unknown_prs(1)})

    backend_api.get_projects.assert_called_once_with(enabled=True)
    backend_api.get_project_trigger_repositories.assert_called_once_with(1, active=True)


def test_a_repository_with_a_run_in_flight_is_skipped():
    result, _, context = run(
        [project(1)], [repo(10, 1), repo(11, 1)], unknown={10: unknown_prs(1), 11: unknown_prs(1)}, in_flight={"10"}
    )

    assert [r.tags["repo_id"] for r in result] == ["11"]
    filters = context.instance.get_runs.call_args.kwargs["filters"]
    assert filters.job_name == "evaluate_repository_pull_requests_job"
    assert filters.statuses == IN_FLIGHT
    assert dg.DagsterRunStatus.QUEUED in IN_FLIGHT and dg.DagsterRunStatus.STARTED in IN_FLIGHT


def test_skips_when_nothing_is_unknown():
    result, _, _ = run([project(1)], [repo(10, 1)])

    assert len(result) == 1 and isinstance(result[0], dg.SkipReason)


def test_a_failing_repository_does_not_stop_the_others_and_the_tick_fails_when_none_launched():
    backend_api = MagicMock()
    backend_api.get_projects.return_value = [project(1)]
    backend_api.get_project_trigger_repositories.return_value = [repo(10, 1), repo(11, 1)]
    backend_api.get_pull_requests.side_effect = lambda project_id, repo_id, state: (
        (_ for _ in ()).throw(RuntimeError("down")) if repo_id == 10 else unknown_prs(1)
    )
    context = MagicMock()
    context.instance.get_runs.return_value = []
    sensor = PullRequestEvaluateSensor(context=context, backend_api=backend_api, git_apis=MagicMock())

    assert [r.tags["repo_id"] for r in sensor()] == ["11"]

    backend_api.get_pull_requests.side_effect = RuntimeError("down")
    with pytest.raises(RuntimeError, match="Evaluation failed for Evaluation of repo 10 of project 1"):
        list(PullRequestEvaluateSensor(context=context, backend_api=backend_api, git_apis=MagicMock())())
