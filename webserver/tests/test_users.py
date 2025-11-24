from unittest import mock

from app.helpers.exceptions import AuthenticationError, KeycloakError


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
        new_user_email,
        mock_kc_client
    ):
        """
        Tests that admins can get a list of all users, but
        the one used by the backend
        """
        mock_kc_client["users_api_kc"].return_value.list_users.return_value[0]["email"] = new_user_email
        resp = client.get(
            "/users",
            headers=simple_admin_header
        )
        assert resp.status_code == 200
        assert len(resp.json) == 1
        assert resp.json[0]['email'] == new_user_email

    def test_user_needs_pass_reset_flag_true(
        self,
        client,
        simple_admin_header,
        basic_user,
        new_user_email,
    ):
        """
        Test that the needs_to_reset_password is set properly
        for a new user and for existing ones
        """
        resp = client.get(
            "/users",
            headers=simple_admin_header
        )
        assert resp.status_code == 200
        for us in resp.json:
            if us["email"] == new_user_email:
                assert us["needs_to_reset_password"] == True
            if basic_user["email"] == new_user_email:
                assert us["needs_to_reset_password"] == False

    def test_get_all_users_fails(
        self,
        client,
        simple_admin_header,
        mock_kc_client
    ):
        """
        Tests that if something goes wrong during the keycloak
        request, we do return a 500
        """
        mock_kc_client["users_api_kc"].return_value.list_users.side_effect = KeycloakError()

        resp = client.get(
            "/users",
            headers=simple_admin_header
        )
        assert resp.status_code == 500

    def test_get_all_users_non_admin(
        self,
        client,
        simple_user_header,
        mock_kc_client
    ):
        """
        Tests that non-admins cannot get the list of users
        """
        mock_kc_client["wrappers_kc"].return_value.is_token_valid.return_value = False
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
        new_user_email,
        mock_kc_client
    ):
        """
        Basic test to ensure we get a 201 and a temp password
        as response.
        """
        mock_kc_client["users_api_kc"].return_value.get_user_by_email.return_value = []
        resp = client.post(
            "/users",
            headers=post_json_admin_header,
            json={"email": new_user_email}
        )

        assert resp.status_code == 201
        assert "tempPassword" in resp.json

    def test_create_successfully_with_special_char(
        self,
        client,
        post_json_admin_header,
        mock_kc_client
    ):
        """
        Basic test to ensure we get a 201 and a temp password
        as response. This tests that email with + are processed fine
        """
        mock_kc_client["users_api_kc"].return_value.get_user_by_email.return_value = []
        resp = client.post(
            "/users",
            headers=post_json_admin_header,
            json={"email": "someemail+test@email.com"}
        )

        assert resp.status_code == 201
        assert "tempPassword" in resp.json

    def test_create_missing_fields(
        self,
        client,
        post_json_admin_header,
        mock_kc_client
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
        new_user_email,
        mock_kc_client
    ):
        """
        Basic test to ensure we get 500 in case
        the keycloak API returns an error
        """
        mock_kc_client["users_api_kc"].return_value.get_user_by_email.return_value = []
        mock_kc_client["users_api_kc"].return_value.create_user.side_effect = KeycloakError('Failed to create the user')

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
        new_user_email,
        mock_kc_client
    ):
        """
        Basic test to ensure we get a 201 and a temp password
        as response for an admin user
        """
        mock_kc_client["users_api_kc"].return_value.get_user_by_email.return_value = []

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
        new_user_email,
        mock_kc_client
    ):
        """
        Basic test to ensure we get a 4xx for creating
        a user with a non-existing role
        """
        mock_kc_client["users_api_kc"].return_value.get_user_by_email.return_value = []
        mock_kc_client["users_api_kc"].return_value.create_user.side_effect = KeycloakError('Role President does not exist', 400)

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
        mock_kc_client,
        new_user_email
    ):
        """
        After a user has been created, make sure it can't
        login with a temporary password
        """
        mock_kc_client["users_api_kc"].return_value.get_user_by_email.return_value = []

        resp = client.post(
            "/users",
            headers=post_json_admin_header,
            json={
                "email": new_user_email
            }
        )

        assert resp.status_code == 201

        mock_kc_client["main_kc"].return_value.get_token.side_effect=AuthenticationError("Temporary password must be changed before logging in")

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
        new_user_email,
        mock_kc_client
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
                "tempPassword": "password",
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
        new_user,
        mock_kc_client,
    ):
        """
        After a user has been created, make sure that using
        another temp password won't allow a change.
        Double check by logging in with the supposed new pass
        """
        mock_kc_client["users_api_kc"].return_value.reset_user_pass.side_effect=AuthenticationError("Incorrect credentials")

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

        mock_kc_client["main_kc"].return_value.get_token.side_effect = AuthenticationError("Failed to login")

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
        new_user,
        mock_kc_client
    ):
        """
        After a user has been created, make sure the temp
        password can't be used for another user, as we try to auth the
        user on kc on their behalf, we expect a certain error message,
        before proceeding with the reset
        """
        new_user["email"] = "second@user.com"
        new_user["username"] = "second@user.com"

        mock_kc_client["users_api_kc"].return_value.get_user_by_email.return_value = []
        resp = self.create_user(client, "second@user.com", post_json_admin_header)

        mock_kc_client["users_api_kc"].return_value.get_user_by_email.return_value = new_user
        mock_kc_client["users_api_kc"].return_value.reset_user_pass.side_effect = AuthenticationError("Incorrect credentials")
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

        mock_kc_client["main_kc"].return_value.get_token.side_effect=AuthenticationError("Failed to login")

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
