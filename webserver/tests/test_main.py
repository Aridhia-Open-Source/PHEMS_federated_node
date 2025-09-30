import os
from unittest import mock
from requests.exceptions import ConnectionError

def test_login_successful(client):
    """
    Simple test to make sure /login returns a token
    """
    login_request = client.post(
        "/login",
        data={
            "username": os.getenv("KEYCLOAK_ADMIN"),
            "password": os.getenv("KEYCLOAK_ADMIN_PASSWORD")
        },
        headers={
            'Content-Type': 'application/x-www-form-urlencoded'
        }
    )
    assert login_request.status_code == 200
    assert list(login_request.json.keys()) == ["token"]

def test_login_unsuccessful(client):
    """
    Simple test to make sure /login returns 401 with incorrect credentials
    """
    login_request = client.post(
        "/login",
        data={
            "username": "not_a_user",
            "password": "pass123"
        },
        headers={
            'Content-Type': 'application/x-www-form-urlencoded'
        }
    )
    assert login_request.status_code == 401

def test_health_check(client):
    """
    Check that the HC returns 200 in optimal conditions
    """
    hc_resp = client.get("/health_check")
    assert hc_resp.status_code == 200

@mock.patch('app.main.requests.get', side_effect=ConnectionError("Some failure"))
def test_health_check_fails(mock_req, client):
    """
    Check that the HC returns 500 with keycloak connection issues
    """
    hc_resp = client.get("/health_check")
    assert hc_resp.status_code == 502
    assert hc_resp.json == {'keycloak': False, 'status': 'non operational'}
