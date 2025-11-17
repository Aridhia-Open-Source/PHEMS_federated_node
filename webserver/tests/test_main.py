import os
import responses
from unittest import mock
from requests.exceptions import ConnectionError
from app.helpers.keycloak import URLS


class TestLogin:
    def test_login_successful(self, client):
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

    def test_login_unsuccessful(self, client):
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


class TestHealthCheck:
    def test_health_check(self, client):
        """
        Check that the HC returns 200 in optimal conditions
        """
        hc_resp = client.get("/health_check")
        assert hc_resp.status_code == 200

    @mock.patch('app.main.requests.get', side_effect=ConnectionError("Some failure"))
    def test_health_check_fails(self, mock_req, client):
        """
        Check that the HC returns 500 with keycloak connection issues
        """
        hc_resp = client.get("/health_check")
        assert hc_resp.status_code == 502
        assert hc_resp.json == {'keycloak': False, 'status': 'non operational'}


class TestTokenRefresh:
    @mock.patch('app.main.Keycloak.get_client_id', return_value="id")
    @mock.patch('app.main.Keycloak._get_client_secret', return_value="sec")
    def test_refresh_token_200(self, mock_client_id, mock_sec_id, client):
        """
        Simmple test to make sure a refresh token is returned
        when a valid token is used in the request header
        """
        # Mocking the requests for the specific token
        valid_token = "eydjn2onoin"
        with responses.RequestsMock() as rsps:
            # Successful response for both admin and user
            rsps.add(
                responses.POST,
                URLS["get_token"],
                json={"access_token": "token", "refresh_token": "token"},
                status=201
            )

            resp = client.post(
                "/refresh_token",
                headers={"Authorization": f"Bearer {valid_token}"}
            )
        assert resp.status_code == 200
        assert "token" in resp.json

    @mock.patch('app.main.Keycloak.get_client_id', return_value="id")
    @mock.patch('app.main.Keycloak._get_client_secret', return_value="sec")
    def test_refresh_token_401(self, mock_client_id, mock_sec_id, client):
        """
        Simmple test to make sure an error is returned
        when an invalid/expired token is used in the request header
        """
        invalid_token = "not a token"
        with responses.RequestsMock() as rsps:
            # Admin token
            rsps.add(
                responses.POST,
                URLS["get_token"],
                json={"access_token": "token", "refresh_token": "token"},
                status=201
            )
            rsps.add(
                responses.POST,
                URLS["get_token"],
                json={"error": "Unauthorized"},
                status=401
            )
            resp = client.post(
                "/refresh_token",
                headers={"Authorization": f"Bearer {invalid_token}"}
            )
        assert resp.status_code == 401
