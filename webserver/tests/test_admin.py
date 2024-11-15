import json
from datetime import datetime
from sqlalchemy import select

from app.helpers.db import db
from app.models.audit import Audit


class TestAudits:
    def test_get_audit_events(
            self,
            simple_admin_header,
            client,
            user_uuid
        ):
        """
        Test that after a simple GET call we have an audit entry
        """
        r = client.get("/datasets/", headers=simple_admin_header)
        assert r.status_code == 200, r.text
        list_audit = db.session.execute(select(Audit)).all()
        assert len(list_audit) > 0
        response = client.get("/audit", headers=simple_admin_header)

        assert response.status_code == 200

        # Check if the expected result is a subset of the actual response
        # We do not check the entire dict due to the datetime and id
        assert response.json[0].items() >= {
            'api_function': 'get_datasets',
            'details': None,
            'endpoint': '/datasets/',
            'requested_by': user_uuid,
            'http_method': 'GET',
            'ip_address': '127.0.0.1',
            'status_code': 200
        }.items()

    def test_get_audit_events_not_by_standard_users(
            self,
            simple_user_header,
            client
        ):
        """
        Test that the endpoint returns 401 for non-admin users
        """
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
        log = Audit.query.filter(Audit.endpoint == '/datasets').one_or_none()
        assert log.details is None

    def test_get_filtered_audit_events(
            self,
            simple_admin_header,
            client
        ):
        """
        Test that after a simple GET call we have an audit entry
        """
        client.get("/datasets/", headers=simple_admin_header)
        date_filter = datetime.now().date()
        response = client.get(f"/audit?event_time__lte={date_filter}", headers=simple_admin_header)

        assert response.status_code == 200, response.json
        assert len(response.json) == 0

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
        data = dataset_post_body.copy()
        data["dictionaries"][0]["password"] = "2ecr3t!"
        resp = client.post(
            '/datasets/',
            data=json.dumps(data),
            headers=post_json_admin_header
        )

        # Request will fail as secret is not recognized as dictionaries field
        assert resp.status_code == 201, resp.json
        audit_list = Audit.get_all()[-1]
        details = json.loads(audit_list["details"].replace("'", "\""))

        assert details["password"] == '*****'
        assert details["username"] == '*****'
        assert details["dictionaries"][0]["password"] == '*****'
