from unittest import mock
from datetime import datetime as dt, timedelta as td
from app.models.audit import Audit


def test_filter_by_date(
        client,
        simple_admin_header,
):
    """
    Testing the efficacy of filtering by date fields
        - __lte => less than or equal
        - __gte => greater than or equal
        - =     => equal
        - __eq  => equal
        - __gt  => greater than
        - __lt  => less than
        - __ne  => not equal
    """
    base_audit = {
        "ip_address": "127.0.0.1",
        "http_method": "GET",
        "endpoint": "/dataset",
        "api_function": "get_datasets",
        "requested_by": "admin",
        "status_code": "200",
        "details": "",
    }
    for idx in range(3):
        base_audit["event_time"] = dt.now() - td(days=idx)
        Audit(**base_audit).add()

    filters = {
        '': 1,
        '__lte': 2,
        '__gte': 2,
        '__eq': 1,
        '__gt': 1,
        '__lt': 1,
        '__ne': 2
    }
    target_date = (dt.now() - td(days=1)).date().strftime("%Y-%m-%d")
    for fil, expected_results in filters.items():
        resp = client.get("/audit", query_string={f"event_time{fil}": target_date}, headers=simple_admin_header)
        assert resp.status_code == 200
        assert resp.json["total"] == expected_results
