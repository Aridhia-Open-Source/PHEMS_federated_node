"""
Fan-out and backfill: the triggers a stored pull request gives each project that watches its repository.
Every (assignment, pull request) pair has exactly one trigger, however it came about.
"""
from http import HTTPStatus

import pytest

from app.helpers.base_model import db
from app.models.project import Project
from app.models.project_trigger_repository import ProjectTriggerRepository
from app.models.pull_request import PullRequest
from app.models.pull_request_trigger import PullRequestTrigger
from app.models.trigger import Trigger
from tests.helpers.pull_requests import pr_body

T = "2026-02-01T10:00:00Z"
EARLY = "2026-01-01T00:00:00"
UNKNOWN, IGNORED = "UNKNOWN", "IGNORED"


@pytest.fixture
def both_locked(project, other_project):
    """Both projects locked and drained, as changing an assignment needs."""
    for p in (project, other_project):
        p.locked = True
    db.session.commit()


def assign(client, headers, project, repo, **body):
    response = client.post(
        f"/projects/{project.id}/trigger_repositories",
        json={"trigger_repository_id": repo.id, "watch_dir": "", **body}, headers=headers,
    )
    assert response.status_code == HTTPStatus.CREATED, response.json
    return response.json


def patch(client, headers, project, assignment, **body):
    response = client.patch(f"/projects/{project.id}/trigger_repositories/{assignment['id']}", json=body, headers=headers)
    assert response.status_code == HTTPStatus.OK, response.json
    return response.json


def ingest(client, headers, repo, *pull_requests):
    response = client.post(f"/trigger_repositories/{repo.id}/pull_requests/batch", json={"pull_requests": list(pull_requests)}, headers=headers)
    assert response.status_code == HTTPStatus.CREATED, response.json
    return response.json


def triggers(assignment) -> dict[int, str]:
    """The state of each trigger of the assignment, by pull request number."""
    db.session.rollback()
    found = PullRequestTrigger.query.join(PullRequest).filter(PullRequestTrigger.project_trigger_repository_id == assignment["id"])
    return {t.number: t.state for t in found}


def assert_one_trigger_per_pair():
    pairs = [(t.project_trigger_repository_id, t.pull_request_id) for t in PullRequestTrigger.query]
    assert len(pairs) == len(set(pairs))
    assert Trigger.query.count() == len(pairs)


@pytest.fixture
def admin(post_json_admin_header):
    return post_json_admin_header


class TestFanOut:
    def test_two_projects_on_one_repository_each_get_one_trigger_per_pull_request(
        self, client, admin, project, other_project, trigger_repo
    ):
        mine = assign(client, admin, project, trigger_repo, initial_cursor=EARLY)
        theirs = assign(client, admin, other_project, trigger_repo, initial_cursor=EARLY)
        ingest(client, admin, trigger_repo, pr_body(1, "2026-01-05T10:00:00Z"), pr_body(2, "2026-01-06T10:00:00Z"))
        ingest(client, admin, trigger_repo, pr_body(2, "2026-01-06T10:00:00Z"), pr_body(3, "2026-01-07T10:00:00Z"))
        assert triggers(mine) == triggers(theirs) == {1: UNKNOWN, 2: UNKNOWN, 3: UNKNOWN}
        assert PullRequest.query.count() == 3
        assert PullRequestTrigger.query.count() == 6
        assert {t.project_id for t in PullRequestTrigger.query} == {project.id, other_project.id}
        assert_one_trigger_per_pair()

    def test_each_project_sees_its_own_triggers_only(self, client, admin, simple_admin_header, project, other_project, trigger_repo):
        mine = assign(client, admin, project, trigger_repo, initial_cursor=EARLY)
        assign(client, admin, other_project, trigger_repo, initial_cursor=EARLY)
        ingest(client, admin, trigger_repo, pr_body(1, "2026-01-05T10:00:00Z"))
        response = client.get(f"/projects/{project.id}/trigger_repositories/{mine['id']}/pull_requests", headers=simple_admin_header)
        assert [(pr["project_id"], pr["number"]) for pr in response.json["items"]] == [(project.id, 1)]

    def test_a_locked_project_still_gets_its_trigger(self, client, admin, project, trigger_repo):
        mine = assign(client, admin, project, trigger_repo, initial_cursor=EARLY)
        project.locked = True
        db.session.commit()
        ingest(client, admin, trigger_repo, pr_body(1, "2026-01-05T10:00:00Z"))
        assert triggers(mine) == {1: UNKNOWN}

    def test_a_pull_request_before_the_assignments_cursor_gets_no_trigger(self, client, admin, project, trigger_repo):
        mine = assign(client, admin, project, trigger_repo, initial_cursor="2026-02-01T00:00:00")
        ingest(client, admin, trigger_repo, pr_body(1, "2026-01-05T10:00:00Z"), pr_body(2, "2026-02-05T10:00:00Z"))
        assert triggers(mine) == {2: UNKNOWN}

    def test_disabled_and_revoked_assignments_get_no_trigger(self, client, admin, project, other_project, trigger_repo):
        third = Project(name="Third")
        third.add()
        disabled = assign(client, admin, project, trigger_repo, initial_cursor=EARLY, enabled=False)
        revoked = assign(client, admin, other_project, trigger_repo, initial_cursor=EARLY)
        patch(client, admin, other_project, revoked, revoked=True)
        active = assign(client, admin, third, trigger_repo, initial_cursor=EARLY)
        ingest(client, admin, trigger_repo, pr_body(1, "2026-01-05T10:00:00Z"))
        assert triggers(disabled) == {}
        assert triggers(revoked) == {}
        assert triggers(active) == {1: UNKNOWN}
        assert PullRequest.query.count() == 1

    def test_the_pull_request_merged_while_inactive_is_backfilled_on_re_enable(
        self, client, admin, project, trigger_repo, both_locked
    ):
        mine = assign(client, admin, project, trigger_repo, initial_cursor=EARLY)
        ingest(client, admin, trigger_repo, pr_body(1, "2026-01-05T10:00:00Z"))
        patch(client, admin, project, mine, enabled=False)
        ingest(client, admin, trigger_repo, pr_body(2, "2026-01-06T10:00:00Z"))
        assert triggers(mine) == {1: UNKNOWN}
        patch(client, admin, project, mine, enabled=True)
        assert triggers(mine) == {1: UNKNOWN, 2: UNKNOWN}

    def test_the_pull_request_merged_while_revoked_is_backfilled_on_un_revoke(self, client, admin, project, trigger_repo):
        mine = assign(client, admin, project, trigger_repo, initial_cursor=EARLY)
        patch(client, admin, project, mine, revoked=True)
        ingest(client, admin, trigger_repo, pr_body(1, "2026-01-05T10:00:00Z"))
        assert triggers(mine) == {}
        patch(client, admin, project, mine, revoked=False)
        assert triggers(mine) == {1: UNKNOWN}


class TestIgnored:
    def test_a_pull_request_touching_no_watched_file_is_ignored_for_every_active_assignment(
        self, client, admin, simple_admin_header, project, other_project, trigger_repo
    ):
        mine = assign(client, admin, project, trigger_repo, initial_cursor=EARLY, watch_dir="triggers")
        theirs = assign(client, admin, other_project, trigger_repo, initial_cursor=EARLY, watch_dir="specs")
        ingest(client, admin, trigger_repo, pr_body(1, "2026-01-05T10:00:00Z", changed_files=[{"path": "README.md", "status": "added"}]))
        assert triggers(mine) == triggers(theirs) == {1: IGNORED}
        response = client.get(f"/projects/{project.id}/trigger_repositories/{mine['id']}/pull_requests/1", headers=simple_admin_header)
        assert response.json["state"] == IGNORED
        assert response.json["state_cause"] == "No new spec file under triggers"

    @pytest.mark.parametrize("files,state", [
        ([{"path": "triggers/spec.json", "status": "added"}], UNKNOWN),
        ([{"path": "triggers/deep/spec.json", "status": "added"}], UNKNOWN),
        ([{"path": "triggers/spec.json", "status": "modified"}], IGNORED),
        ([{"path": "triggers/spec.json", "status": "removed"}], IGNORED),
        ([{"path": "triggers/spec.yaml", "status": "added"}], IGNORED),
        ([{"path": "triggers-other/spec.json", "status": "added"}], IGNORED),
        ([{"path": "spec.json", "status": "added"}], IGNORED),
        ([{"path": "src/a.py", "status": "added"}, {"path": "triggers/spec.json", "status": "added"}], UNKNOWN),
        ([], IGNORED),
    ])
    def test_the_watched_file_is_a_json_file_the_pull_request_adds_under_watch_dir(
        self, client, admin, project, trigger_repo, files, state
    ):
        """The rule of the Dagster evaluate step (PullRequestParser), applied to the stored files."""
        mine = assign(client, admin, project, trigger_repo, initial_cursor=EARLY, watch_dir="triggers")
        ingest(client, admin, trigger_repo, pr_body(1, "2026-01-05T10:00:00Z", changed_files=files))
        assert triggers(mine) == {1: state}

    def test_an_empty_watch_dir_watches_the_whole_repository(self, client, admin, project, trigger_repo):
        mine = assign(client, admin, project, trigger_repo, initial_cursor=EARLY, watch_dir="")
        ingest(client, admin, trigger_repo, pr_body(1, "2026-01-05T10:00:00Z", changed_files=[{"path": "a/b/c.json", "status": "added"}]))
        assert triggers(mine) == {1: UNKNOWN}

    def test_a_pull_request_into_another_branch_is_ignored(self, client, admin, simple_admin_header, project, trigger_repo):
        mine = assign(client, admin, project, trigger_repo, initial_cursor=EARLY, base_branch="release")
        ingest(client, admin, trigger_repo, pr_body(1, "2026-01-05T10:00:00Z"), pr_body(2, "2026-01-06T10:00:00Z", base_branch="release"))
        assert triggers(mine) == {1: IGNORED, 2: UNKNOWN}
        cause = client.get(f"/projects/{project.id}/trigger_repositories/{mine['id']}/pull_requests/1", headers=simple_admin_header).json["state_cause"]
        assert cause == "Pull request was merged into main, not release"

    def test_a_truncated_file_list_matches_every_path(self, client, admin, project, trigger_repo):
        mine = assign(client, admin, project, trigger_repo, initial_cursor=EARLY, watch_dir="triggers")
        ingest(client, admin, trigger_repo, pr_body(1, "2026-01-05T10:00:00Z", changed_files=[{"path": "a.md", "status": "added"}], files_truncated=True))
        assert triggers(mine) == {1: UNKNOWN}


class TestBackfill:
    def stored(self, client, admin, repo):
        """Pull requests merged before any project is assigned."""
        ingest(client, admin, repo, pr_body(1, "2026-01-05T10:00:00Z"), pr_body(2, "2026-01-10T10:00:00Z"), pr_body(3, "2026-01-20T10:00:00Z"))

    def test_creating_an_assignment_with_an_early_cursor_backfills_the_pull_requests_at_or_after_it(
        self, client, admin, project, trigger_repo
    ):
        self.stored(client, admin, trigger_repo)
        mine = assign(client, admin, project, trigger_repo, initial_cursor="2026-01-10T10:00:00")
        assert triggers(mine) == {2: UNKNOWN, 3: UNKNOWN}

    def test_creating_an_assignment_without_a_cursor_replays_nothing(self, client, admin, project, trigger_repo):
        self.stored(client, admin, trigger_repo)
        assert triggers(assign(client, admin, project, trigger_repo)) == {}

    def test_creating_a_disabled_assignment_backfills_when_it_is_enabled(self, client, admin, project, trigger_repo, both_locked):
        self.stored(client, admin, trigger_repo)
        mine = assign(client, admin, project, trigger_repo, initial_cursor="2026-01-10T10:00:00", enabled=False)
        assert triggers(mine) == {}
        patch(client, admin, project, mine, enabled=True)
        assert triggers(mine) == {2: UNKNOWN, 3: UNKNOWN}

    def test_moving_the_cursor_earlier_backfills_the_gap_and_none_twice(self, client, admin, project, trigger_repo, both_locked):
        self.stored(client, admin, trigger_repo)
        mine = assign(client, admin, project, trigger_repo, initial_cursor="2026-01-20T10:00:00")
        assert triggers(mine) == {3: UNKNOWN}
        patch(client, admin, project, mine, initial_cursor="2026-01-10T10:00:00")
        assert triggers(mine) == {2: UNKNOWN, 3: UNKNOWN}
        patch(client, admin, project, mine, initial_cursor="2026-01-01T00:00:00")
        assert triggers(mine) == {1: UNKNOWN, 2: UNKNOWN, 3: UNKNOWN}
        patch(client, admin, project, mine, initial_cursor="2026-01-01T00:00:00")
        assert PullRequestTrigger.query.count() == 3
        assert_one_trigger_per_pair()

    def test_moving_the_cursor_later_is_refused_once_triggers_exist(self, client, admin, project, trigger_repo, both_locked):
        self.stored(client, admin, trigger_repo)
        mine = assign(client, admin, project, trigger_repo, initial_cursor=EARLY)
        response = client.patch(
            f"/projects/{project.id}/trigger_repositories/{mine['id']}", json={"initial_cursor": "2026-01-15T00:00:00"}, headers=admin
        )
        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert triggers(mine) == {1: UNKNOWN, 2: UNKNOWN, 3: UNKNOWN}

    def test_moving_the_cursor_earlier_while_inactive_backfills_on_activation(self, client, admin, project, trigger_repo, both_locked):
        self.stored(client, admin, trigger_repo)
        mine = assign(client, admin, project, trigger_repo, initial_cursor="2026-01-20T10:00:00", enabled=False)
        patch(client, admin, project, mine, initial_cursor=EARLY)
        assert triggers(mine) == {}
        patch(client, admin, project, mine, enabled=True)
        assert triggers(mine) == {1: UNKNOWN, 2: UNKNOWN, 3: UNKNOWN}

    def test_pull_requests_merged_in_the_same_second_are_told_apart_by_number(
        self, client, admin, project, other_project, trigger_repo, both_locked
    ):
        """The cursor is (merged_at, number): the latest stored pull request is the one with the highest number."""
        ingest(client, admin, trigger_repo, pr_body(5, T), pr_body(7, T))
        mine = assign(client, admin, project, trigger_repo)
        assert triggers(mine) == {}
        # Same second, a lower number than the cursor: before it. A higher number: after it.
        ingest(client, admin, trigger_repo, pr_body(6, T), pr_body(8, T))
        assert triggers(mine) == {8: UNKNOWN}

        # An explicit timestamp includes every pull request merged at it
        theirs = assign(client, admin, other_project, trigger_repo, initial_cursor="2026-02-01T10:00:00")
        assert triggers(theirs) == {5: UNKNOWN, 6: UNKNOWN, 7: UNKNOWN, 8: UNKNOWN}

        # Moving back to the timestamp resets the number: the tie is included again
        patch(client, admin, project, mine, initial_cursor="2026-02-01T10:00:00")
        assert triggers(mine) == {5: UNKNOWN, 6: UNKNOWN, 7: UNKNOWN, 8: UNKNOWN}
        assert_one_trigger_per_pair()

    def test_a_pull_request_one_second_before_the_cursor_is_left_out(self, client, admin, project, trigger_repo):
        ingest(client, admin, trigger_repo, pr_body(1, "2026-02-01T09:59:59Z"), pr_body(2, T))
        assert triggers(assign(client, admin, project, trigger_repo, initial_cursor="2026-02-01T10:00:00")) == {2: UNKNOWN}


class TestExactlyOnce:
    def test_every_path_in_sequence_leaves_one_trigger_per_pair(self, client, admin, project, other_project, trigger_repo, both_locked):
        """Fan-out, re-posts and every backfill trigger run over the same data."""
        batch = [pr_body(n, f"2026-01-{n + 9:02d}T10:00:00Z") for n in range(1, 7)]
        ingest(client, admin, trigger_repo, *batch[:3])

        mine = assign(client, admin, project, trigger_repo, initial_cursor="2026-01-11T00:00:00")
        theirs = assign(client, admin, other_project, trigger_repo, initial_cursor=EARLY, enabled=False)
        ingest(client, admin, trigger_repo, *batch[2:])
        ingest(client, admin, trigger_repo, *batch)

        patch(client, admin, other_project, theirs, enabled=True)
        patch(client, admin, other_project, theirs, revoked=True)
        ingest(client, admin, trigger_repo, pr_body(7, "2026-01-30T10:00:00Z"))
        patch(client, admin, other_project, theirs, revoked=False)
        patch(client, admin, project, mine, enabled=False)
        patch(client, admin, project, mine, enabled=True)
        patch(client, admin, project, mine, initial_cursor="2026-01-01T00:00:00")
        patch(client, admin, project, mine, initial_cursor="2026-01-01T00:00:00")
        ingest(client, admin, trigger_repo, *batch)

        everything = {n: UNKNOWN for n in range(1, 8)}
        assert triggers(mine) == triggers(theirs) == everything
        assert PullRequest.query.count() == 7
        assert PullRequestTrigger.query.count() == 14
        assert_one_trigger_per_pair()
        assert ProjectTriggerRepository.query.count() == 2
