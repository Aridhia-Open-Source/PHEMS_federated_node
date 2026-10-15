import pytest
import requests

from app.helpers.dagster import START_SENSOR_MUTATION, STOP_SENSOR_MUTATION

TICK_TIME = 1760000000.0
TICK_ISO = "2025-10-09T08:53:20+00:00"


def graphql_sensor(name, status, tick_status=None):
    ticks = [{"timestamp": TICK_TIME, "status": tick_status}] if tick_status else []
    return {
        "name": name,
        "sensorState": {"id": f"{name}-id", "status": status, "ticks": ticks},
    }


@pytest.fixture
def dagster(mocker):
    """
    A fake Dagster GraphQL endpoint. `sensors` is its state; mutations update it
    """
    sensors = {
        "task_launcher_sensor": graphql_sensor("task_launcher_sensor", "STOPPED", "SUCCESS"),
        "task_queued_sensor": graphql_sensor("task_queued_sensor", "RUNNING", "FAILURE"),
        "task_failure_sensor": graphql_sensor("task_failure_sensor", "RUNNING"),
    }
    mutations = []

    def post(url, json, timeout):
        assert url.endswith("/graphql")
        query, variables = json["query"], json["variables"]
        if query == START_SENSOR_MUTATION:
            name = variables["selector"]["sensorName"]
            assert variables["selector"]["repositoryLocationName"] == "dagster-fn"
            assert variables["selector"]["repositoryName"] == "__repository__"
            sensors[name]["sensorState"]["status"] = "RUNNING"
            mutations.append(("start", name))
            data = {"startSensor": {"__typename": "Sensor"}}
        elif query == STOP_SENSOR_MUTATION:
            name = variables["id"].removesuffix("-id")
            sensors[name]["sensorState"]["status"] = "STOPPED"
            mutations.append(("stop", name))
            data = {"stopSensor": {"__typename": "StopSensorMutationResult"}}
        else:
            data = {"repositoriesOrError": {
                "__typename": "RepositoryConnection",
                "nodes": [{
                    "name": "__repository__",
                    "location": {"name": "dagster-fn"},
                    "sensors": list(sensors.values()),
                }],
            }}
        response = mocker.Mock()
        response.json.return_value = {"data": data}
        return response

    mocker.patch("app.helpers.dagster.requests.post", side_effect=post)
    return mutations


def sensor_json(name, status, last_tick, error):
    return {"name": name, "status": status, "last_tick": last_tick, "error": error}


LAUNCHER = sensor_json("task_launcher_sensor", "STOPPED", TICK_ISO, False)
QUEUED = sensor_json("task_queued_sensor", "RUNNING", TICK_ISO, True)
FAILURE = sensor_json("task_failure_sensor", "RUNNING", None, False)


class TestGetSensors:
    def test_list(self, client, simple_admin_header, dagster):
        response = client.get("/dagster/sensors", headers=simple_admin_header)

        assert response.status_code == 200, response.json
        assert response.json == [LAUNCHER, QUEUED, FAILURE]

    def test_single(self, client, simple_admin_header, dagster):
        response = client.get("/dagster/sensors/task_queued_sensor", headers=simple_admin_header)

        assert response.status_code == 200, response.json
        assert response.json == QUEUED

    def test_unknown_sensor_404(self, client, simple_admin_header, dagster):
        response = client.get("/dagster/sensors/nope", headers=simple_admin_header)

        assert response.status_code == 404

    def test_non_admin_denied(self, client, simple_user_header, mock_kc_client, dagster):
        mock_kc_client["wrappers_kc"].return_value.is_token_valid.side_effect = None
        mock_kc_client["wrappers_kc"].return_value.is_token_valid.return_value = False

        response = client.get("/dagster/sensors", headers=simple_user_header)

        assert response.status_code == 403


class TestPatchSensors:
    def test_patch_all(self, client, post_json_admin_header, dagster):
        response = client.patch(
            "/dagster/sensors", json={"status": "RUNNING"}, headers=post_json_admin_header
        )

        assert response.status_code == 200, response.json
        assert [s["status"] for s in response.json] == ["RUNNING"] * 3
        # Sensors already in the status are left alone
        assert dagster == [("start", "task_launcher_sensor")]

    def test_patch_subset(self, client, post_json_admin_header, dagster):
        response = client.patch(
            "/dagster/sensors",
            json={"status": "STOPPED", "names": ["task_queued_sensor", "task_launcher_sensor"]},
            headers=post_json_admin_header,
        )

        assert response.status_code == 200, response.json
        assert [s["status"] for s in response.json] == ["STOPPED", "STOPPED", "RUNNING"]
        assert dagster == [("stop", "task_queued_sensor")]

    def test_patch_single(self, client, post_json_admin_header, dagster):
        response = client.patch(
            "/dagster/sensors/task_launcher_sensor",
            json={"status": "RUNNING"},
            headers=post_json_admin_header,
        )

        assert response.status_code == 200, response.json
        assert response.json == {**LAUNCHER, "status": "RUNNING"}
        assert dagster == [("start", "task_launcher_sensor")]

    def test_unknown_name_changes_nothing(self, client, post_json_admin_header, dagster):
        response = client.patch(
            "/dagster/sensors",
            json={"status": "RUNNING", "names": ["task_launcher_sensor", "nope"]},
            headers=post_json_admin_header,
        )

        assert response.status_code == 404
        assert "nope" in response.json["error"]
        assert dagster == []

    def test_unknown_single_sensor_404(self, client, post_json_admin_header, dagster):
        response = client.patch(
            "/dagster/sensors/nope", json={"status": "RUNNING"}, headers=post_json_admin_header
        )

        assert response.status_code == 404
        assert dagster == []

    @pytest.mark.parametrize("body", [{}, {"status": "PAUSED"}, {"status": None}, [], {"names": []}])
    @pytest.mark.parametrize("path", ["/dagster/sensors", "/dagster/sensors/task_launcher_sensor"])
    def test_bad_status_400(self, client, post_json_admin_header, dagster, path, body):
        response = client.patch(path, json=body, headers=post_json_admin_header)

        assert response.status_code == 400
        assert dagster == []

    def test_bad_names_400(self, client, post_json_admin_header, dagster):
        response = client.patch(
            "/dagster/sensors",
            json={"status": "RUNNING", "names": "task_launcher_sensor"},
            headers=post_json_admin_header,
        )

        assert response.status_code == 400
        assert dagster == []

    def test_non_admin_denied(self, client, post_json_user_header, mock_kc_client, dagster):
        mock_kc_client["wrappers_kc"].return_value.is_token_valid.side_effect = None
        mock_kc_client["wrappers_kc"].return_value.is_token_valid.return_value = False

        response = client.patch(
            "/dagster/sensors", json={"status": "RUNNING"}, headers=post_json_user_header
        )

        assert response.status_code == 403
        assert dagster == []


class TestDagsterErrors:
    def test_unreachable_502(self, client, simple_admin_header, mocker):
        mocker.patch(
            "app.helpers.dagster.requests.post",
            side_effect=requests.exceptions.ConnectionError("refused"),
        )

        response = client.get("/dagster/sensors", headers=simple_admin_header)

        assert response.status_code == 502
        assert "Dagster is unreachable" in response.json["error"]

    def test_graphql_error_502(self, client, simple_admin_header, mocker):
        response = mocker.Mock()
        response.json.return_value = {"errors": [{"message": "Cannot query field"}]}
        mocker.patch("app.helpers.dagster.requests.post", return_value=response)

        result = client.get("/dagster/sensors", headers=simple_admin_header)

        assert result.status_code == 502
        assert "Cannot query field" in result.json["error"]

    def test_mutation_error_502(self, client, post_json_admin_header, dagster, mocker):
        post = mocker.patch("app.helpers.dagster.requests.post")
        listing = {"repositoriesOrError": {
            "__typename": "RepositoryConnection",
            "nodes": [{
                "name": "__repository__",
                "location": {"name": "dagster-fn"},
                "sensors": [graphql_sensor("task_launcher_sensor", "STOPPED")],
            }],
        }}
        failure = {"startSensor": {"__typename": "PythonError", "message": "boom"}}
        post.side_effect = [
            mocker.Mock(json=lambda: {"data": listing}),
            mocker.Mock(json=lambda: {"data": failure}),
        ]

        response = client.patch(
            "/dagster/sensors/task_launcher_sensor",
            json={"status": "RUNNING"},
            headers=post_json_admin_header,
        )

        assert response.status_code == 502
        assert "boom" in response.json["error"]
