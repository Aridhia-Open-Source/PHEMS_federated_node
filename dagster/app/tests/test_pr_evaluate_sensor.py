import re
from unittest.mock import MagicMock

import dagster as dg

from app.definitions.sensors.git.pr_evaluate import IN_FLIGHT, PullRequestEvaluateSensor
from app.models import Project, TriggerState


def project(id, enabled=True):
    return Project(id=id, name=f"proj{id}", enabled=enabled)


def repo(id, project_id):
    return MagicMock(id=id, project_id=project_id)


def run(projects, repos, unknown=None, in_flight=()):
    backend_api = MagicMock()
    backend_api.get_projects.return_value = projects
    backend_api.get_repositories.return_value = repos
    backend_api.get_pull_requests.side_effect = lambda repo_id, state: (unknown or {}).get(repo_id, [])
    context = MagicMock()
    context.instance.get_runs.side_effect = lambda filters, limit: [MagicMock()] if filters.tags["repo_id"] in in_flight else []
    sensor = PullRequestEvaluateSensor(context=context, backend_api=backend_api, git_apis=MagicMock())
    return list(sensor()), backend_api, context


def test_one_run_per_repository_with_unknown_prs():
    result, backend_api, _ = run(
        [project(1)], [repo(10, 1), repo(11, 1), repo(12, 1)], unknown={10: ["a", "b"], 12: ["c"]}
    )

    assert [r.tags["repo_id"] for r in result] == ["10", "12"]
    assert all(isinstance(r, dg.RunRequest) for r in result)
    backend_api.get_pull_requests.assert_any_call(10, TriggerState.UNKNOWN.value)


def test_the_run_is_configured_and_tagged_for_its_repository():
    result, _, _ = run([project(3)], [repo(10, 3)], unknown={10: ["a"]})

    assert result[0].tags == {"repo_id": "10", "project_id": "3"}
    assert result[0].run_config == {"ops": {"load_unknown_pull_requests": {"config": {"repo_id": 10}}}}


def test_the_run_key_includes_the_minute():
    result, _, _ = run([project(1)], [repo(10, 1)], unknown={10: ["a"]})

    assert re.fullmatch(r"evaluate/10/\d{12}", result[0].run_key)


def test_only_enabled_projects_are_evaluated():
    result, _, _ = run(
        [project(1, enabled=False), project(2)], [repo(10, 1), repo(11, 2)], unknown={10: ["a"], 11: ["b"]}
    )

    assert [r.tags["repo_id"] for r in result] == ["11"]


def test_a_repository_with_a_run_in_flight_is_skipped():
    result, _, context = run(
        [project(1)], [repo(10, 1), repo(11, 1)], unknown={10: ["a"], 11: ["b"]}, in_flight={"10"}
    )

    assert [r.tags["repo_id"] for r in result] == ["11"]
    filters = context.instance.get_runs.call_args.kwargs["filters"]
    assert filters.job_name == "evaluate_repository_pull_requests_job"
    assert filters.statuses == IN_FLIGHT
    assert dg.DagsterRunStatus.QUEUED in IN_FLIGHT and dg.DagsterRunStatus.STARTED in IN_FLIGHT


def test_skips_when_nothing_is_unknown():
    result, _, _ = run([project(1)], [repo(10, 1)])

    assert len(result) == 1 and isinstance(result[0], dg.SkipReason)
