from unittest.mock import MagicMock

import pytest
import requests

from fednode.clients.dagster.client import LOCATION, REPOSITORY, DagsterClient
from fednode.http import ClientError, ClientTimeout


def reply(data=None, errors=None, status_code=200):
    resp = MagicMock(spec=requests.Response)
    resp.status_code = status_code
    resp.ok = status_code < 400
    resp.json.return_value = {k: v for k, v in {"data": data, "errors": errors}.items() if v is not None}
    return resp


@pytest.fixture
def session():
    return MagicMock()


@pytest.fixture
def dagster(session):
    return DagsterClient("http://dagster:3000/", session=session)


def sent(session, call=-1):
    return session.request.call_args_list[call].kwargs["json"]


def test_no_connection_is_reused(session, dagster):
    session.headers.__setitem__.assert_called_once_with("Connection", "close")


def test_the_query_is_posted_to_graphql_with_the_default_timeout(session, dagster):
    session.request.return_value = reply({"runsOrError": {"__typename": "Runs", "results": []}})

    dagster.get_task_run(7)

    assert session.request.call_args.args == ("POST", "http://dagster:3000/graphql")
    assert session.request.call_args.kwargs["timeout"] == (3, 10)


def test_the_timeout_can_be_overridden(session):
    session.request.return_value = reply({"runsOrError": {"__typename": "Runs", "results": []}})

    DagsterClient("http://dagster:3000", session=session, timeout=(3, 30)).get_task_run(7)

    assert session.request.call_args.kwargs["timeout"] == (3, 30)


class TestErrors:
    def test_a_timeout_is_a_client_timeout(self, session, dagster):
        session.request.side_effect = requests.ReadTimeout("slow")

        with pytest.raises(ClientTimeout):
            dagster.list_sensors()

    def test_an_unreachable_dagster_is_a_client_error(self, session, dagster):
        session.request.side_effect = requests.ConnectionError("refused")

        with pytest.raises(ClientError, match="unreachable"):
            dagster.list_sensors()

    def test_a_status_error_is_a_client_error(self, session, dagster):
        resp = reply(status_code=503)
        resp.json.return_value = {}
        session.request.return_value = resp

        with pytest.raises(ClientError, match="503"):
            dagster.list_sensors()

    def test_an_answer_that_is_not_json_is_a_client_error(self, session, dagster):
        resp = reply(status_code=502)
        resp.json.side_effect = ValueError("not json")
        session.request.return_value = resp

        with pytest.raises(ClientError, match="502 without JSON"):
            dagster.list_sensors()

    def test_graphql_errors_are_a_client_error_with_the_first_message(self, session, dagster):
        session.request.return_value = reply(errors=[{"message": "bad query"}, {"message": "other"}])

        with pytest.raises(ClientError, match="bad query"):
            dagster.list_sensors()

    def test_an_error_type_is_a_client_error_with_its_message(self, session, dagster):
        session.request.return_value = reply({"startSensor": {"__typename": "SensorNotFoundError", "message": "no x"}})

        with pytest.raises(ClientError, match="SensorNotFoundError: no x"):
            dagster.start_sensor("x")


class TestSensors:
    def test_listing_gives_status_last_tick_and_the_ids_to_change_it(self, session, dagster):
        session.request.return_value = reply({"repositoriesOrError": {"__typename": "RepositoryConnection", "nodes": [{
            "name": "repo",
            "location": {"name": "loc"},
            "sensors": [
                {"name": "ticked", "sensorState": {"id": "i1", "status": "RUNNING", "ticks": [
                    {"timestamp": 0, "status": "FAILURE"}]}},
                {"name": "fresh", "sensorState": {"id": "i2", "status": "STOPPED", "ticks": []}},
            ],
        }]}})

        sensors = dagster.list_sensors()

        assert sensors == [
            {
                "name": "ticked", "status": "RUNNING", "last_tick": "1970-01-01T00:00:00+00:00", "error": True,
                "state_id": "i1",
                "selector": {"repositoryLocationName": "loc", "repositoryName": "repo", "sensorName": "ticked"},
            },
            {
                "name": "fresh", "status": "STOPPED", "last_tick": None, "error": False, "state_id": "i2",
                "selector": {"repositoryLocationName": "loc", "repositoryName": "repo", "sensorName": "fresh"},
            },
        ]

    def test_starting_a_listed_sensor_sends_its_own_selector(self, session, dagster):
        session.request.return_value = reply({"startSensor": {"__typename": "Sensor", "sensorState": {"status": "RUNNING"}}})
        sensor = {"selector": {"repositoryLocationName": "loc", "repositoryName": "repo", "sensorName": "s"}}

        dagster.set_sensor_status(sensor, "RUNNING")

        assert sent(session)["variables"] == {"selector": sensor["selector"]}

    def test_stopping_a_listed_sensor_sends_its_state_id(self, session, dagster):
        session.request.return_value = reply({"stopSensor": {
            "__typename": "StopSensorMutationResult", "instigationState": {"status": "STOPPED"}}})

        dagster.set_sensor_status({"state_id": "i1"}, "STOPPED")

        assert sent(session)["variables"] == {"id": "i1"}

    def test_a_sensor_is_selected_by_name_in_the_code_location(self, session, dagster):
        session.request.return_value = reply({"sensorOrError": {"__typename": "Sensor", "sensorState": {"id": "i1"}}})

        assert dagster.get_sensor_state("s") == {"id": "i1"}
        assert sent(session)["variables"] == {
            "selector": {"repositoryLocationName": LOCATION, "repositoryName": REPOSITORY, "sensorName": "s"}
        }

    def test_ticks_are_asked_for_with_a_limit(self, session, dagster):
        session.request.return_value = reply({"sensorOrError": {
            "__typename": "Sensor", "sensorState": {"ticks": [{"id": "t1"}]}}})

        assert dagster.get_sensor_ticks("s", limit=5) == [{"id": "t1"}]
        assert sent(session)["variables"]["limit"] == 5

    def test_stopping_by_name_looks_up_the_state_id_first(self, session, dagster):
        session.request.side_effect = [
            reply({"sensorOrError": {"__typename": "Sensor", "sensorState": {"id": "i1"}}}),
            reply({"stopSensor": {"__typename": "StopSensorMutationResult", "instigationState": {"status": "STOPPED"}}}),
        ]

        assert dagster.stop_sensor("s") == "STOPPED"
        assert sent(session) == {"query": sent(session)["query"], "variables": {"id": "i1"}}

    def test_starting_by_name_returns_the_new_status(self, session, dagster):
        session.request.return_value = reply({"startSensor": {"__typename": "Sensor", "sensorState": {"status": "RUNNING"}}})

        assert dagster.start_sensor("s") == "RUNNING"


class TestTaskRun:
    def test_the_run_is_found_by_the_task_id_tag(self, session, dagster):
        run = {"runId": "r1", "status": "SUCCESS", "jobName": "job", "tags": []}
        session.request.return_value = reply({"runsOrError": {"__typename": "Runs", "results": [run]}})

        assert dagster.get_task_run(7) == run
        assert sent(session)["variables"] == {"filter": {"tags": [{"key": "fn/task_id", "value": "7"}]}}

    def test_a_task_without_a_run_has_none(self, session, dagster):
        session.request.return_value = reply({"runsOrError": {"__typename": "Runs", "results": []}})

        assert dagster.get_task_run(7) is None
