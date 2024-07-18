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
            'details': f'Requested by {user_uuid} - ',
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
