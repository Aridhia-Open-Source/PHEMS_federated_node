import json
from datetime import datetime
from sqlalchemy import select, text

from app.helpers.base_model import get_db
from app.models.audit import Audit


class TestAudits:
    def test_get_audit_events(
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

        r = client.get("/datasets", headers=simple_admin_header)
        assert r.status_code == 200, r.text
        with get_db() as session:
            list_audit = session.execute(select(Audit)).all()
        assert len(list_audit) > 0
        response = client.get("/audit", headers=simple_admin_header)

        assert response.status_code == 200

        # Check if the expected result is a subset of the actual response
        # We do not check the entire dict due to the datetime and id
        assert response.json()["items"][0].items() >= {
            'api_function': 'get_datasets',
            'details': 'No body',
            'endpoint': '/datasets',
            'requested_by': admin_user_uuid,
            'http_method': 'GET',
            'ip_address': 'testclient',
            'status_code': 200
        }.items()

    def test_get_audit_events_not_by_standard_users(
            self,
            simple_user_header,
            client,
            mock_kc_client
        ):
        """
        Test that the endpoint returns 403 for non-admin users
        """
        mock_kc_client["wrappers_kc"].return_value.is_token_valid.return_value = False
        response = client.get("/audit", headers=simple_user_header)
        assert response.status_code == 403

    def test_audit_ignore_empty_json(
            self,
            post_json_admin_header,
            client
        ):
        """
        Test that a GET request with the content type set to json
        won't fail with an empty body
        """
        response = client.get("/datasets", headers=post_json_admin_header)
        assert response.status_code == 200
        with get_db() as session:
            log = session.execute(select(Audit).where(Audit.endpoint == '/datasets')).scalars().one_or_none()
        assert log.details == "No body"

    def test_get_filtered_audit_events(
            self,
            simple_admin_header,
            client
        ):
        """
        Test that after a simple GET call we have an audit entry
        """
        client.get("/datasets", headers=simple_admin_header)
        date_filter = datetime.now().date()
        response = client.get(f"/audit?event_time__lte={date_filter}", headers=simple_admin_header)

        assert response.status_code == 200
        assert response.json()["total"] == 1

    def test_sensitive_data_is_purged(
        self,
        client,
        post_json_admin_header,
        dataset_post_body,
        k8s_client
    ):
        """
        Tests that sensitive information are not included in the audit logs details
        """
        resp = client.post(
            '/datasets',
            json=dataset_post_body,
            headers=post_json_admin_header
        )

        # RequestModel will fail as secret is not recognized as dictionaries field
        assert resp.status_code == 201, resp.json()
        with get_db() as session:
            audit_list = session.execute(select(Audit).filter_by(endpoint="/datasets").order_by(text("event_time DESC"))).scalars().all()[0]
        details = json.loads(audit_list.details.replace("'", "\"").replace("None", "null"))

        assert details["password"] == '*****'
        assert details["username"] == '*****'
