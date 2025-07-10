from app.models.dataset import Dataset


class TestPagination:
    def test_pagination(
            self,
            client,
            mocker,
            k8s_client,
            user_uuid,
            dataset,
            dataset_oracle,
            simple_admin_header
        ):
        """
        Test that an endpoint that supports pagination
        effectively returns reliable results
        """
        mocker.patch('app.helpers.wrappers.Keycloak.is_token_valid', return_value=True)
        Dataset(
            name="testnew",
            host="host.url",
            username="user",
            password="pass"
        ).add(user_id=user_uuid)
        resp = client.get('/datasets', query_string={"page": "2", "per_page": '2'}, headers=simple_admin_header)

        assert resp.status_code == 200
        assert len(resp.json["items"]) == 1
        assert resp.json["total"] == 3

    def test_pagination_page_does_not_exist(
            self,
            client,
            simple_admin_header
        ):
        """
        Test that an endpoint that supports pagination
        returns a 404 when the page of results exceeds the ones available
        """
        resp = client.get('/datasets', query_string={"page": "5", "per_page": '2'}, headers=simple_admin_header)

        assert resp.status_code == 404

    def test_pagination_invalid_value_page(
            self,
            client,
            simple_admin_header
        ):
        """
        Test that an endpoint that supports pagination
        returns a 400 when the page is not in a supported format
        """
        resp = client.get('/datasets', query_string={"page": "asdf", "per_page": '2'}, headers=simple_admin_header)

        assert resp.status_code == 400
        assert resp.json["error"] == "page and per_page parameters should be integers"
