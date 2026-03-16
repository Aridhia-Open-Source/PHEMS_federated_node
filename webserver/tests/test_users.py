from pytest import mark
from unittest import mock

from app.helpers.exceptions import AuthenticationError, KeycloakError


class UserMixin:
    async def create_user(self, client, email, headers):
        """
        Common helper to send the create user request
        """
        resp = await client.post(
            "/users",
            headers=headers,
            json={
                "email": email
            }
        )

        assert resp.status_code == 201
        return resp.json()

class TestGetUsers(UserMixin):
    @mark.asyncio
    async def test_get_all_users(
        self,
        client,
        simple_admin_header,
        new_user_email,
        mock_kc_client_users_route,
        base_kc_mock_args
    ):
        """
        Tests that admins can get a list of all users, but
        the one used by the backend
        """
        base_kc_mock_args.list_users.return_value[0]["email"] = new_user_email
        resp = await client.get(
            "/users",
            headers=simple_admin_header
        )
        assert resp.status_code == 200
        assert len(resp.json()) == 1
        assert resp.json()[0]['email'] == new_user_email

    @mark.asyncio
    async def test_user_needs_pass_reset_flag_true(
        self,
        client,
        simple_admin_header,
        basic_user,
        new_user_email,
        mock_kc_client_wrapper
    ):
        """
        Test that the needs_to_reset_password is set properly
        for a new user and for existing ones
        """
        resp = await client.get(
            "/users",
            headers=simple_admin_header
        )
        assert resp.status_code == 200
        for us in resp.json():
            if us["email"] == new_user_email:
                assert us["needs_to_reset_password"] == True
            if basic_user["email"] == new_user_email:
                assert us["needs_to_reset_password"] == False

    @mark.asyncio
    async def test_get_all_users_fails(
        self,
        client,
        simple_admin_header,
        mock_kc_client_users_route,
        base_kc_mock_args
    ):
        """
        Tests that if something goes wrong during the keycloak
        request, we do return a 500
        """
        base_kc_mock_args.list_users.side_effect = KeycloakError()

        resp = await client.get(
            "/users",
            headers=simple_admin_header
        )
        assert resp.status_code == 500

    @mark.asyncio
    async def test_get_all_users_non_admin(
        self,
        client,
        simple_user_header,
        mock_kc_client_users_route,
        base_kc_mock_args
    ):
        """
        Tests that non-admins cannot get the list of users
        """
        base_kc_mock_args.is_token_valid.return_value = False
        resp = await client.get(
            "/users",
            headers=simple_user_header
        )
        assert resp.status_code == 403


class TestCreateUser(UserMixin):
    @mark.asyncio
    async def test_create_successfully(
        self,
        client,
        post_json_admin_header,
        new_user_email,
        mock_kc_client_users_route,
        base_kc_mock_args
    ):
        """
        Basic test to ensure we get a 201 and a temp password
        as response.
        """
        base_kc_mock_args.get_user_by_email.side_effect = [
            [],
            base_kc_mock_args.get_user_by_email.return_value
        ]
        resp = await client.post(
            "/users",
            headers=post_json_admin_header,
            json={"email": new_user_email}
        )

        assert resp.status_code == 201
        assert "tempPassword" in resp.json()

    @mark.asyncio
    async def test_create_successfully_with_special_char(
        self,
        client,
        post_json_admin_header,
        mock_kc_client_users_route,
        base_kc_mock_args
    ):
        """
        Basic test to ensure we get a 201 and a temp password
        as response. This tests that email with + are processed fine
        """
        base_kc_mock_args.get_user_by_email.side_effect = [
            [],
            base_kc_mock_args.get_user_by_email.return_value
        ]
        resp = await client.post(
            "/users",
            headers=post_json_admin_header,
            json={"email": "someemail+test@email.com"}
        )

        assert resp.status_code == 201
        assert "tempPassword" in resp.json()

    @mark.asyncio
    async def test_create_missing_fields(
        self,
        client,
        post_json_admin_header,
        mock_kc_client_users_route
    ):
        """
        Basic test to ensure we get 400 in case
        an email or username are not provided
        """
        resp = await client.post(
            "/users",
            headers=post_json_admin_header,
            json={
                "username": "Administrator",
                "role": "Administrator"
            }
        )

        assert resp.status_code == 400
        assert resp.json()["error"][0]["message"] == "Field required"
        assert "email" in resp.json()["error"][0]["field"]

    @mark.asyncio
    @mock.patch('app.routes.users.Keycloak.create.create_user', return_value=mock.Mock())
    async def test_create_user_with_same_email(
        self,
        mock_kc_create,
        client,
        new_user,
        new_user_email,
        post_json_admin_header,
        mock_kc_client_wrapper
    ):
        """
        Create a user with the email of an existing user.
        It is expected that no actions are taken, and 4xx is returned
        """
        resp = await client.post(
            "/users",
            headers=post_json_admin_header,
            json={"email": new_user_email}
        )

        mock_kc_create.assert_not_called()
        assert resp.status_code == 400
        assert resp.json()["error"] == "User already exists"

    @mark.asyncio
    async def test_create_keycloak_error(
        self,
        client,
        post_json_admin_header,
        new_user_email,
        mock_kc_client_users_route,
        base_kc_mock_args
    ):
        """
        Basic test to ensure we get 500 in case
        the keycloak API returns an error
        """
        base_kc_mock_args.create_user.side_effect = KeycloakError('Failed to create the user')
        base_kc_mock_args.get_user_by_email.side_effect = [
            [],
            base_kc_mock_args.get_user_by_email.return_value
        ]

        resp = await client.post(
            "/users",
            headers=post_json_admin_header,
            json={"email": new_user_email}
        )

        assert resp.status_code == 500
        assert resp.json() == {"error": "Failed to create the user"}

    @mark.asyncio
    async def test_create_admin_successfully(
        self,
        client,
        post_json_admin_header,
        new_user_email,
        mock_kc_client_users_route,
        base_kc_mock_args
    ):
        """
        Basic test to ensure we get a 201 and a temp password
        as response for an admin user
        """
        base_kc_mock_args.get_user_by_email.side_effect = [
            [],
            base_kc_mock_args.get_user_by_email.return_value
        ]
        resp = await client.post(
            "/users",
            headers=post_json_admin_header,
            json={
                "email": new_user_email,
                "role": "Administrator"
            }
        )

        assert resp.status_code == 201
        assert "tempPassword" in resp.json()

    @mark.asyncio
    async def test_create_user_non_existing_role(
        self,
        client,
        post_json_admin_header,
        simple_admin_header,
        new_user_email,
        mock_kc_client_users_route,
        base_kc_mock_args
    ):
        """
        Basic test to ensure we get a 4xx for creating
        a user with a non-existing role
        """
        base_kc_mock_args.get_user_by_email.side_effect = [
            [],
            base_kc_mock_args.get_user_by_email.return_value, # For audit wrappers
            base_kc_mock_args.get_user_by_email.return_value # For audit wrappers
        ]
        base_kc_mock_args.create_user.side_effect = KeycloakError('Role President does not exist', 400)

        resp = await client.post(
            "/users",
            headers=post_json_admin_header,
            json={
                "email": new_user_email,
                "role": "President"
            }
        )

        assert resp.status_code == 400
        assert resp.json()["error"] == "Role President does not exist"

        # check the user doesn't exist in keycloak
        resp = await client.get(
            "/users",
            headers=simple_admin_header
        )
        assert new_user_email not in [user["email"] for user in resp.json()]

    @mark.asyncio
    async def test_new_user_login_with_temp_pass(
        self,
        client,
        post_json_admin_header,
        mock_kc_client_users_route,
        new_user_email,
        base_kc_mock_args
    ):
        """
        After a user has been created, make sure it can't
        login with a temporary password
        """
        base_kc_mock_args.get_user_by_email.side_effect = [
            [],
            base_kc_mock_args.get_user_by_email.return_value
        ]

        resp = await client.post(
            "/users",
            headers=post_json_admin_header,
            json={
                "email": new_user_email
            }
        )

        assert resp.status_code == 201

        base_kc_mock_args.get_token.side_effect = AuthenticationError("Temporary password must be changed before logging in")

        # Try to login
        login_resp = await client.post(
            '/login',
            data={
                "username": new_user_email,
                "password": resp.json()["tempPassword"]
            },
            headers={
                'Content-Type': 'application/x-www-form-urlencoded'
            }
        )
        assert login_resp.status_code == 401
        assert login_resp.json() == {"error": "Temporary password must be changed before logging in"}


class TestPassChange(UserMixin):
    @mark.asyncio
    async def test_new_user_can_change_pass(
        self,
        client,
        new_user_email,
        mock_kc_client_users_route
    ):
        """
        After a user has been created, make sure the temp
        password can be changed
        """
        # Change temp pass
        psw_resp = await client.put(
            '/users/reset-password',
            json={
                "email": new_user_email,
                "tempPassword": "password",
                "newPassword": "asjfpoasj124124"
            }
        )
        assert psw_resp.status_code == 204

        # Try to login
        login_resp = await client.post(
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

    @mark.asyncio
    async def test_new_user_cant_change_wrong_pass(
        self,
        client,
        new_user,
        mock_kc_client_users_route,
        base_kc_mock_args
    ):
        """
        After a user has been created, make sure that using
        another temp password won't allow a change.
        Double check by logging in with the supposed new pass
        """
        base_kc_mock_args.reset_user_pass.side_effect=AuthenticationError("Incorrect credentials")

        # Change temp pass
        psw_resp = await client.put(
            '/users/reset-password',
            json={
                "email": new_user["email"],
                "tempPassword": "notgood",
                "newPassword": "asjfpoasj124124"
            }
        )
        assert psw_resp.status_code == 401
        assert psw_resp.json()["error"] == "Incorrect credentials"

        base_kc_mock_args.get_token.side_effect = AuthenticationError("Failed to login")

        # Try to login
        login_resp = await client.post(
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

    @mark.asyncio
    async def test_new_user_cant_change_for_another_user(
        self,
        client,
        post_json_admin_header,
        new_user,
        mock_kc_client_users_route,
        base_kc_mock_args
    ):
        """
        After a user has been created, make sure the temp
        password can't be used for another user, as we try to auth the
        user on kc on their behalf, we expect a certain error message,
        before proceeding with the reset
        """
        new_user["email"] = "second@user.com"
        new_user["username"] = "second@user.com"

        base_kc_mock_args.get_user_by_email.side_effect = [
            [],
            new_user,
            base_kc_mock_args.get_user_by_email.return_value
        ]
        resp = await self.create_user(client, "second@user.com", post_json_admin_header)

        base_kc_mock_args.reset_user_pass.side_effect = AuthenticationError("Incorrect credentials")
        # Change temp pass
        psw_resp = await client.put(
            '/users/reset-password',
            json={
                "email": new_user["email"],
                "tempPassword": resp["tempPassword"],
                "newPassword": "asjfpoasj124124"
            }
        )
        assert psw_resp.status_code == 401
        assert psw_resp.json()["error"] == "Incorrect credentials"

        base_kc_mock_args.get_token.side_effect = AuthenticationError("Failed to login")

        # Try to login
        login_resp = await client.post(
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
