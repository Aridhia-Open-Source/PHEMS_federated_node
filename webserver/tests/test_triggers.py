import pytest
from sqlalchemy.exc import IntegrityError

from app.helpers.base_model import db
from app.helpers.exceptions import InvalidRequest
from app.models.api_request_trigger import ApiRequestTrigger
from app.models.pull_request_trigger import PullRequestTrigger
from app.models.task import Task
from app.models.trigger import Trigger
from tests.helpers.pull_requests import add_pull_request_trigger


def make_pull_request(project, repo) -> PullRequestTrigger:
    return add_pull_request_trigger(repo, 1, title="t")


class TestTriggerModels:
    def test_polymorphic_load(self, project):
        api = ApiRequestTrigger(project_id=project.id, user_id="user")
        api.add()
        loaded = Trigger.query.filter_by(id=api.id).one()
        assert isinstance(loaded, ApiRequestTrigger)
        assert loaded.type == "API"
        assert loaded.state == "UNKNOWN"
        assert loaded.requested_by == "user"

    def test_pull_request_requested_by_is_raiser(self, project, default_repo):
        pr = make_pull_request(project, default_repo)
        assert Trigger.query.filter_by(id=pr.id).one().type == "PR"
        assert pr.requested_by == "user"

    @pytest.mark.parametrize("state,state_cause", [
        ("REJECTED", None), ("UNKNOWN", "why"), ("YIELDED", "why"),
    ])
    def test_check_ties_state_cause_to_state(self, project, state, state_cause):
        api = ApiRequestTrigger(project_id=project.id, user_id="user")
        api.add()
        api.state = state
        api.state_cause = state_cause
        with pytest.raises(IntegrityError):
            api.add()
        db.session.rollback()

    def test_one_task_per_trigger(self, make_task, project):
        task = make_task()
        duplicate = Task(
            name="task", requested_by="user", project_id=project.id, trigger_id=task.trigger_id,
            spec={"image": "img:1", "dataset_id": None, "env": {}}
        )
        with pytest.raises(IntegrityError):
            duplicate.add()
        db.session.rollback()


class TestTriggerSetState:
    @pytest.fixture
    def api(self, project):
        api = ApiRequestTrigger(project_id=project.id, user_id="user")
        api.add()
        return api

    @pytest.mark.parametrize("state", ["REJECTED"])
    def test_needs_a_cause(self, api, state):
        with pytest.raises(InvalidRequest):
            api.set_state(state, None)

    @pytest.mark.parametrize("state", ["UNKNOWN", "YIELDED"])
    def test_cause_not_allowed(self, api, state):
        with pytest.raises(InvalidRequest):
            api.set_state(state, "why")

    @pytest.mark.parametrize("state", ["DONE", "IGNORED"])
    def test_unknown_state(self, api, state):
        with pytest.raises(InvalidRequest):
            api.set_state(state, None)

    @pytest.mark.parametrize("state,cause", [("REJECTED", "bad spec"), ("YIELDED", None)])
    def test_valid_transitions_persist(self, api, state, cause):
        api.set_state(state, cause)
        api.add()
        assert Trigger.query.filter_by(id=api.id).one().state_cause == cause


    def test_rejected_is_final(self, api):
        api.set_state("REJECTED", "bad spec")
        with pytest.raises(InvalidRequest) as error:
            api.set_state("UNKNOWN", None)
        assert error.value.code == 409
