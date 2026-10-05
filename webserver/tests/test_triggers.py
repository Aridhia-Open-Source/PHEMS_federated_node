import pytest
from sqlalchemy.exc import IntegrityError

from app.helpers.base_model import db
from app.models.api_request import ApiRequest
from app.models.pull_request import PullRequest
from app.models.task import Task
from app.models.trigger import Trigger


def make_pull_request(project, repo_id=1) -> PullRequest:
    pr = PullRequest(
        project_id=project.id, trigger_repository_id=repo_id, number=1, title="t",
        raised_by="user", merged_at="2026-01-01T10:00:00Z", merge_commit_sha="a" * 40,
    )
    pr.add()
    return pr


class TestTriggerModels:
    def test_polymorphic_load(self, project):
        api = ApiRequest(project_id=project.id, user_id="user")
        api.add()
        loaded = Trigger.query.filter_by(id=api.id).one()
        assert isinstance(loaded, ApiRequest)
        assert loaded.type == "API"
        assert loaded.state == "UNKNOWN"
        assert loaded.requested_by == "user"

    def test_pull_request_requested_by_is_raiser(self, project, default_repo):
        pr = make_pull_request(project, default_repo.id)
        assert Trigger.query.filter_by(id=pr.id).one().type == "PR"
        assert pr.requested_by == "user"

    @pytest.mark.parametrize("state,state_cause", [
        ("REJECTED", None), ("IGNORED", None), ("UNKNOWN", "why"), ("YIELDED", "why"),
    ])
    def test_check_ties_state_cause_to_state(self, project, state, state_cause):
        api = ApiRequest(project_id=project.id, user_id="user")
        api.add()
        api.state = state
        api.state_cause = state_cause
        with pytest.raises(IntegrityError):
            api.add()
        db.session.rollback()

    def test_one_task_per_trigger(self, make_task, project):
        task = make_task()
        duplicate = Task(
            name="task", docker_image="img:1", requested_by="user", dataset_id=None,
            project_id=project.id, trigger_id=task.trigger_id, spec={"image": "img:1"}
        )
        with pytest.raises(IntegrityError):
            duplicate.add()
        db.session.rollback()
