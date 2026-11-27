"""app/errors.py: the status and body of the errors the clients and the request validation raise."""
import json

import pytest
from fednode.clients.keycloak import KeycloakError
from fednode.clients.kubernetes.client import KubernetesError
from fednode.clients.kubernetes.names import InvalidName


@pytest.fixture
def dagster(mocker):
    return mocker.patch("app.dagster_api.dagster").return_value


def test_a_keycloak_error_keeps_its_code_and_message(client, admin_headers, dagster):
    dagster.list_sensors.side_effect = KeycloakError("Failed to fetch the user")
    response = client.get("/dagster/sensors", headers=admin_headers)
    assert (response.status_code, response.json()) == (500, {"error": "Failed to fetch the user"})

    dagster.list_sensors.side_effect = KeycloakError("Could not find project", 400)
    response = client.get("/dagster/sensors", headers=admin_headers)
    assert (response.status_code, response.json()) == (400, {"error": "Could not find project"})


def test_a_kubernetes_error_keeps_the_status_and_causes_of_the_cluster(client, admin_headers, dagster):
    body = json.dumps({"code": 422, "details": {"causes": [{"field": "data", "message": "bad"}]}})
    dagster.list_sensors.side_effect = KubernetesError(body)
    response = client.get("/dagster/sensors", headers=admin_headers)
    assert response.status_code == 422
    assert response.json() == {
        "error": "An unexpected kubernetes error occurred. Check the details field",
        "details": [{"field": "data", "message": "bad"}],
    }


def test_a_kubernetes_error_with_a_plain_body_is_a_500_with_that_message(client, admin_headers, dagster):
    dagster.list_sensors.side_effect = KubernetesError("Forbidden")
    response = client.get("/dagster/sensors", headers=admin_headers)
    assert (response.status_code, response.json()) == (500, {"error": "Forbidden"})


def test_a_name_kubernetes_would_refuse_is_unprocessable(client, admin_headers, dagster):
    dagster.list_sensors.side_effect = InvalidName("run_id must be 1 to 63 lowercase alphanumerics")
    response = client.get("/dagster/sensors", headers=admin_headers)
    assert (response.status_code, response.json()) == (422, {"error": "run_id must be 1 to 63 lowercase alphanumerics"})


def test_a_body_that_is_not_an_object_is_unprocessable(client, admin_headers, dagster):
    response = client.patch("/dagster/sensors", headers=admin_headers, json=["names"])
    assert response.status_code == 422
    assert "Input should be a valid dictionary" in response.json()["error"]


def test_a_body_that_is_not_json_is_a_bad_request(client, admin_headers, dagster):
    response = client.patch(
        "/dagster/sensors", headers={**admin_headers, "Content-Type": "application/json"}, content="{not json"
    )
    assert response.status_code == 400


def test_a_parameter_that_does_not_fit_is_unprocessable(client, admin_headers):
    response = client.get("/global/datasets?page=0", headers=admin_headers)
    assert response.status_code == 422


def test_an_id_that_is_not_a_number_is_a_missing_route(client, admin_headers):
    response = client.get("/global/datasets/abc", headers=admin_headers)
    assert (response.status_code, response.json()) == (404, {"error": "Not Found"})
