class TestUpdateDeliverySecret:
    def test_delivery_secret_not_implemented(
        self,
        client,
        post_json_admin_header,
        k8s_client
    ):
        """
        Test that updating the delivery secret returns 501
        while the endpoint has no implementation
        """
        resp = client.patch(
            "/delivery-secret",
            json={"auth": "test"},
            headers=post_json_admin_header
        )

        assert resp.status_code == 501
        assert resp.json["error"] == "Not implemented"
        k8s_client["patch_namespaced_secret_mock"].assert_not_called()
