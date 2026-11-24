"""/dagster/sensors: a Dagster that does not answer, or answers with an error, is a 504 or a 502."""
import pytest
from fednode.http import ClientError, ClientTimeout

SENSOR = {
    "name": "git_pull_request_ingest_sensor",
    "status": "RUNNING",
    "last_tick": None,
    "error": False,
    "state_id": "state-1",
    "selector": {"repositoryLocationName": "dagster-fn", "repositoryName": "__repository__", "sensorName": "x"},
}


@pytest.fixture
def dagster(mocker):
    return mocker.patch("app.dagster_api.dagster").return_value


def test_the_sensors_are_listed(client, admin_headers, dagster):
    dagster.list_sensors.return_value = [SENSOR]

    response = client.get("/dagster/sensors", headers=admin_headers)

    assert response.status_code == 200
    assert response.json() == [{"name": SENSOR["name"], "status": "RUNNING", "last_tick": None, "error": False}]


def test_a_sensor_is_started_through_the_client(client, admin_headers, dagster):
    dagster.list_sensors.return_value = [{**SENSOR, "status": "STOPPED"}]

    response = client.patch(f"/dagster/sensors/{SENSOR['name']}", headers=admin_headers, json={"status": "RUNNING"})

    assert response.status_code == 200
    dagster.set_sensor_status.assert_called_once_with({**SENSOR, "status": "STOPPED"}, "RUNNING")


@pytest.mark.parametrize(
    "error,status",
    [
        (ClientTimeout("The service did not answer in time"), 504),
        (ClientError("The service is unreachable: ConnectionError"), 502),
        (ClientError("Dagster GraphQL error: boom"), 502),
    ],
)
def test_a_client_error_is_a_gateway_error(client, admin_headers, dagster, error, status):
    dagster.list_sensors.side_effect = error

    response = client.get("/dagster/sensors", headers=admin_headers)

    assert response.status_code == status
    assert response.json() == {"error": str(error)}
