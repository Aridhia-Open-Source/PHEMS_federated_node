from app.models.dataset import Dataset


class TestPagination:
    def test_pagination(
            self,
            client,
            mocker,
            k8s_client,
            dataset,
            dataset_oracle,
            simple_admin_header,
            db_session
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
        ).add(db_session)
        resp = client.get('/datasets', params={"page": "2", "per_page": '2'}, headers=simple_admin_header)

        assert resp.status_code == 200
        assert len(resp.json()["items"]) == 1
        assert resp.json()["total"] == 3

    def test_pagination_page_does_not_exist(
            self,
            client,
            simple_admin_header
        ):
        """
        Test that an endpoint that supports pagination
        returns an empty list
        """
        resp = client.get('/datasets', params={"page": "5", "per_page": '2'}, headers=simple_admin_header)

        assert resp.status_code == 200
        assert resp.json() == {"items": [], "page": 5, "per_page": 2, "pages": 0, "total": 0}

    def test_pagination_invalid_value_page(
            self,
            client,
            simple_admin_header
        ):
        """
        Test that an endpoint that supports pagination
        returns a 400 when the page is not in a supported format
        """
        resp = client.get('/datasets', params={"page": "asdf", "per_page": '2'}, headers=simple_admin_header)

        assert resp.status_code == 400
        assert "Input should be a valid integer, unable to parse string as an integer" in resp.json()["error"][0]["message"]
        assert "page" in resp.json()["error"][0]["field"]
