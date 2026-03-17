import json
from datetime import datetime
from pytest import mark
from sqlalchemy import select, text

from app.models.audit import Audit
from tests.base_test_class import BaseTest


class TestAudits(BaseTest):
    @mark.asyncio
    async def test_get_audit_events(
            self,
            simple_admin_header,
            client,
            admin_user_uuid,
            mock_kc_client
        ):
        """
        Test that after a simple GET call we have an audit entry
        """
        mock_kc_client["wrappers_kc"].return_value.get_user_by_email.return_value["id"] = admin_user_uuid

        r = await client.get("/datasets", headers=simple_admin_header)
        assert r.status_code == 200, r.text
        list_audit = await self.run_query(select(Audit))
        assert len(list_audit) > 0
        response = await client.get(
            "/audit",
            params={
                "endpoint": "/datasets"
            },
            headers=simple_admin_header
        )

        assert response.status_code == 200

        # Check if the expected result is a subset of the actual response
        # We do not check the entire dict due to the datetime and id
        assert response.json()["items"][0].items() >= {
            'api_function': 'get_datasets',
            'details': 'No body',
            'endpoint': '/datasets',
            'requested_by': admin_user_uuid,
            'http_method': 'GET',
            'ip_address': '127.0.0.1',
            'status_code': 200
        }.items()

    @mark.asyncio
    async def test_get_audit_events_not_by_standard_users(
            self,
            simple_user_header,
            client,
            mock_kc_client
        ):
        """
        Test that the endpoint returns 403 for non-admin users
        """
        mock_kc_client["wrappers_kc"].return_value.is_token_valid.return_value = False
        response = await client.get("/audit", headers=simple_user_header)
        assert response.status_code == 403

    @mark.asyncio
    async def test_audit_ignore_empty_json(
            self,
            post_json_admin_header,
            client
        ):
        """
        Test that a GET request with the content type set to json
        won't fail with an empty body
        """
        response = await client.get("/datasets", headers=post_json_admin_header)
        assert response.status_code == 200
        log = await self.run_query(select(Audit).where(Audit.endpoint == '/datasets'),"one_or_none")
        assert log.details == "No body"

    @mark.asyncio
    async def test_get_filtered_audit_events(
            self,
            simple_admin_header,
            client
        ):
        """
        Test that after a simple GET call we have an audit entry
        """
        await client.get("/datasets", headers=simple_admin_header)
        date_filter = datetime.now().date()
        response = await client.get(
            "/audit",
            params={
                "event_time__lte": date_filter,
                "endpoint": "/datasets"
            },
            headers=simple_admin_header
        )

        assert response.status_code == 200
        assert response.json()["total"] == 1

    @mark.asyncio
    async def test_sensitive_data_is_purged(
        self,
        client,
        post_json_admin_header,
        dataset_post_body,
        v1_ds_mock
    ):
        """
        Tests that sensitive information are not included in the audit logs details
        """
        dataset_post_body["name"] = "audittest"
        resp = await client.post(
            '/datasets',
            json=dataset_post_body,
            headers=post_json_admin_header
        )

        # RequestModel will fail as secret is not recognized as dictionaries field
        assert resp.status_code == 201
        audit_list = await self.run_query(select(Audit).filter_by(endpoint="/datasets").order_by(text("event_time DESC")), "one")
        details = json.loads(audit_list.details.replace("'", "\"").replace("None", "null"))

        assert details["password"] == '*****'
        assert details["username"] == '*****'
