class TestCreateUser:
    def test_create_successfully(
        self,
        client,
        post_json_admin_header
    ):
        """
        Basic test to ensure we get a 201 and a temp password
        as response.
        """
        resp = client.post(
            "/users",
            headers=post_json_admin_header,
            json={
                "email": "test@test.com"
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

    def test_new_user_can_change_pass(
        self,
        client
    ):
        """
        After a user has been created, make sure the temp
        password can be changed
        """
        psw_resp = client.put(
            '/users/reset-password',
            json={
                "email": "test@test.com",
                "tempPassword": "test",
                "newPassword": "asjfpoasj124124"
            }
        )
        assert psw_resp.status_code == 200

    def test_create_admin_successfully(
        self,
        client,
        post_json_admin_header
    ):
        """
        Basic test to ensure we get a 201 and a temp password
        as response for an admin user
        """
        resp = client.post(
            "/users",
            headers=post_json_admin_header,
            json={
                "email": "test@test.com",
                "role": "Administrator"
            }
        )

        assert resp.status_code == 201
        assert "tempPassword" in resp.json
