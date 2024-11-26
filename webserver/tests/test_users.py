import re
import pytest

import responses
from app.helpers.keycloak import URLS

@pytest.fixture
def new_user_email():
    return "test@test.com"


class TestCreateUser:
    def test_create_successfully(
        self,
        client,
        post_json_admin_header,
        new_user_email
    ):
        """
        Basic test to ensure we get a 201 and a temp password
        as response.
        """
        resp = client.post(
            "/users",
            headers=post_json_admin_header,
            json={
                "email": new_user_email
            }
        )

        assert resp.status_code == 201
        assert "tempPassword" in resp.json

    def test_create_missing_fields(
        self,
        client,
        post_json_admin_header
    ):
        """
        Basic test to ensure we get 400 in case
        an email or username are not provided
        """
        resp = client.post(
            "/users",
            headers=post_json_admin_header,
            json={
                "username": "Administrator",
                "role": "Administrator"
            }
        )

        assert resp.status_code == 400
        assert resp.json == {"error": "An email should be provided"}

    def test_create_keycloak_error(
        self,
        client,
        post_json_admin_header,
        new_user_email
    ):
        """
        Basic test to ensure we get 500 in case
        the keycloak API returns an error
        """
        with responses.RequestsMock(assert_all_requests_are_fired=False) as req:
            # Ignore all of the other calls to KC, like admin login etc
            req.add_passthru(re.compile(".*/realms/FederatedNode/(?!users).*"))
            # Also ignore queries to get users details, creating users is plain /user
            req.add_passthru(re.compile(".*/realms/FederatedNode/users.+"))
            req.add(
               responses.POST,
                URLS["user"],
                status=400
            )
            resp = client.post(
                "/users",
                headers=post_json_admin_header,
                json={"email": new_user_email}
            )

        assert resp.status_code == 500
        assert resp.json == {"error": "Failed to create the user"}

    def test_create_admin_successfully(
        self,
        client,
        post_json_admin_header,
        new_user_email
    ):
        """
        Basic test to ensure we get a 201 and a temp password
        as response for an admin user
        """
        resp = client.post(
            "/users",
            headers=post_json_admin_header,
            json={
                "email": new_user_email,
                "role": "Administrator"
            }
        )

        assert resp.status_code == 201
        assert "tempPassword" in resp.json


class TestPassChange:
    def test_new_user_can_change_pass(
        self,
        client,
        post_json_admin_header,
        mocker,
        new_user_email
    ):
        """
        After a user has been created, make sure the temp
        password can be changed
        """
        resp = client.post(
            "/users",
            headers=post_json_admin_header,
            json={
                "email": new_user_email
            }
        )

        assert resp.status_code == 201

        # Change temp pass
        psw_resp = client.put(
            '/users/reset-password',
            json={
                "email": new_user_email,
                "tempPassword": resp.json["tempPassword"],
                "newPassword": "asjfpoasj124124"
            }
        )
        assert psw_resp.status_code == 204

        # Try to login
        login_resp = client.post(
            '/login',
            data={
                "username": new_user_email,
                "password": "asjfpoasj124124"
            },
            headers={
                'Content-Type': 'application/x-www-form-urlencoded'
            }
        )
        assert login_resp.status_code == 200

    def test_new_user_cant_change_wrong_pass(
        self,
        client,
        post_json_admin_header,
        mocker,
        new_user_email
    ):
        """
        After a user has been created, make sure that using
        another temp password won't allow a change.
        Double check by logging in with the supposed new pass
        """
        resp = client.post(
            "/users",
            headers=post_json_admin_header,
            json={
                "email": new_user_email
            }
        )

        assert resp.status_code == 201

        # Change temp pass
        psw_resp = client.put(
            '/users/reset-password',
            json={
                "email": new_user_email,
                "tempPassword": "notgood",
                "newPassword": "asjfpoasj124124"
            }
        )
        assert psw_resp.status_code == 400

        # Try to login
        login_resp = client.post(
            '/login',
            data={
                "username": new_user_email,
                "password": "asjfpoasj124124"
            },
            headers={
                'Content-Type': 'application/x-www-form-urlencoded'
            }
        )
        assert login_resp.status_code == 401

    def test_new_user_cant_change_for_another_user(
        self,
        client,
        post_json_admin_header,
        mocker,
        new_user_email
    ):
        """
        After a user has been created, make sure the temp
        password can't be used for another user, as we try to auth the
        user on kc on their behalf, we expect a certain error message,
        before proceeding with the reset
        """
        client.post(
            "/users",
            headers=post_json_admin_header,
            json={
                "email": new_user_email
            }
        )

        resp = client.post(
            "/users",
            headers=post_json_admin_header,
            json={
                "email": "second@user.com"
            }
        )

        assert resp.status_code == 201

        # Change temp pass
        psw_resp = client.put(
            '/users/reset-password',
            json={
                "email": new_user_email,
                "tempPassword": resp.json["tempPassword"],
                "newPassword": "asjfpoasj124124"
            }
        )
        assert psw_resp.status_code == 400

        # Try to login
        login_resp = client.post(
            '/login',
            data={
                "username": new_user_email,
                "password": "asjfpoasj124124"
            },
            headers={
                'Content-Type': 'application/x-www-form-urlencoded'
            }
        )
        assert login_resp.status_code == 401

    def test_new_user_login_with_temp_pass(
        self,
        client,
        post_json_admin_header,
        mocker,
        new_user_email
    ):
        """
        After a user has been created, make sure it can't
        login with a temporary password
        """
        resp = client.post(
            "/users",
            headers=post_json_admin_header,
            json={
                "email": new_user_email
            }
        )

        assert resp.status_code == 201

        # Try to login
        login_resp = client.post(
            '/login',
            data={
                "username": new_user_email,
                "password": resp.json["tempPassword"]
            },
            headers={
                'Content-Type': 'application/x-www-form-urlencoded'
            }
        )
        assert login_resp.status_code == 401
