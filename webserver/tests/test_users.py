import re
from unittest import mock

import responses
from app.helpers.keycloak import URLS


class UserMixin:
    def create_user(self, client, email, headers):
        """
        Common helper to send the create user request
        """
        resp = client.post(
            "/users",
            headers=headers,
            json={
                "email": email
            }
        )

        assert resp.status_code == 201
        return resp.json

class TestGetUsers(UserMixin):
    def test_get_all_users(
        self,
        client,
        simple_admin_header,
        new_user,
        new_user_email
    ):
        """
        Tests that admins can get a list of all users, but
        the one used by the backend
        """
        resp = client.get(
            "/users",
            headers=simple_admin_header
        )
        assert resp.status_code == 200
        assert len(resp.json) == 1
        assert resp.json[0]['email'] == new_user_email

    def test_get_all_users_fails(
        self,
        client,
        simple_admin_header,
        new_user,
        new_user_email
    ):
        """
        Tests that if something goes wrong during the keycloak
        request, we do return a 500
        """
        with responses.RequestsMock(assert_all_requests_are_fired=False) as req:
            # Ignore all of the other calls to KC, like admin login etc
            req.add_passthru(re.compile(".*/realms/FederatedNode/(?!users).*"))
            req.add(
                responses.GET,
                URLS["user"],
                status=400
            )
            resp = client.get(
                "/users",
                headers=simple_admin_header
            )
        assert resp.status_code == 500

    def test_get_all_users_non_admin(
        self,
        client,
        simple_user_header
    ):
        """
        Tests that non-admins cannot get the list of users
        """
        resp = client.get(
            "/users",
            headers=simple_user_header
        )
        assert resp.status_code == 403


class TestCreateUser(UserMixin):
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
            json={"email": new_user_email}
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

    @mock.patch('app.models.dataset.Keycloak.create_user', return_value=mock.Mock())
    def test_create_user_with_same_email(
        self,
        mock_kc_create,
        client,
        new_user,
        new_user_email,
        post_json_admin_header
    ):
        """
        Create a user with the email of an existing user.
        It is expected that no actions are taken, and 4xx is returned
        """
        resp = client.post(
            "/users",
            headers=post_json_admin_header,
            json={"email": new_user_email}
        )

        mock_kc_create.assert_not_called()
        assert resp.status_code == 400
        assert resp.json["error"] == "User already exists"

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

    def test_create_user_non_existing_role(
        self,
        client,
        post_json_admin_header,
        simple_admin_header,
        new_user_email
    ):
        """
        Basic test to ensure we get a 4xx for creating
        a user with a non-existing role
        """
        resp = client.post(
            "/users",
            headers=post_json_admin_header,
            json={
                "email": new_user_email,
                "role": "President"
            }
        )

        assert resp.status_code == 400
        assert resp.json["error"] == "Role President does not exist"

        # check the user doesn't exist in keycloak
        resp = client.get(
            "/users",
            headers=simple_admin_header
        )
        assert new_user_email not in [user["email"] for user in resp.json]

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
        assert login_resp.json == {"error": "Temporary password must be changed before logging in"}


class TestPassChange(UserMixin):
    def test_new_user_can_change_pass(
        self,
        client,
        post_json_admin_header,
        mocker,
        new_user_email,
        new_user
    ):
        """
        After a user has been created, make sure the temp
        password can be changed
        """
        # Change temp pass
        psw_resp = client.put(
            '/users/reset-password',
            json={
                "email": new_user_email,
                "tempPassword": new_user["password"],
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
        mocker,
        new_user
    ):
        """
        After a user has been created, make sure that using
        another temp password won't allow a change.
        Double check by logging in with the supposed new pass
        """
        # Change temp pass
        psw_resp = client.put(
            '/users/reset-password',
            json={
                "email": new_user["email"],
                "tempPassword": "notgood",
                "newPassword": "asjfpoasj124124"
            }
        )
        assert psw_resp.status_code == 401
        assert psw_resp.json["error"] == "Incorrect credentials"

        # Try to login
        login_resp = client.post(
            '/login',
            data={
                "username": new_user["email"],
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
        new_user
    ):
        """
        After a user has been created, make sure the temp
        password can't be used for another user, as we try to auth the
        user on kc on their behalf, we expect a certain error message,
        before proceeding with the reset
        """
        resp = self.create_user(client, "second@user.com", post_json_admin_header)

        # Change temp pass
        psw_resp = client.put(
            '/users/reset-password',
            json={
                "email": new_user["email"],
                "tempPassword": resp["tempPassword"],
                "newPassword": "asjfpoasj124124"
            }
        )
        assert psw_resp.status_code == 401
        assert psw_resp.json["error"] == "Incorrect credentials"

        # Try to login
        login_resp = client.post(
            '/login',
            data={
                "username": new_user["email"],
                "password": "asjfpoasj124124"
            },
            headers={
                'Content-Type': 'application/x-www-form-urlencoded'
            }
        )
        assert login_resp.status_code == 401
