"""
Shared Keycloak admin-API helpers for the integration test steps.

Each step was previously a `python3 - <<'PY'` heredoc inside one large shell script, and each
re-implemented its own token fetch and request wrapper. They are here once instead.

A step reports by calling check() as it goes and report() at the end; report() exits non-zero if any
check failed, which is how the orchestrator counts a step as failed.
"""
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

BASE = f"http://{os.environ['KC_IP']}:8080"
REALM = os.environ["KEYCLOAK_REALM"]

_results = []


def check(ok, msg):
    _results.append((bool(ok), msg))


def report():
    """Print every check and exit non-zero if any failed. Never returns."""
    for ok, msg in _results:
        print(f"  {'PASS' if ok else 'FAIL'}  {msg}")
    sys.exit(0 if all(ok for ok, _ in _results) else 1)


def password_token(username, password, realm=None):
    """A direct-grant token, or None if the credentials are rejected."""
    data = urllib.parse.urlencode({
        "client_id": "admin-cli", "grant_type": "password",
        "username": username, "password": password,
    }).encode()
    url = f"{BASE}/realms/{realm or REALM}/protocol/openid-connect/token"
    try:
        return json.load(urllib.request.urlopen(url, data))["access_token"]
    except urllib.error.HTTPError:
        return None


def service_token():
    """A token for the platform's own service account, which is how kc-init authenticates."""
    return password_token(os.environ["KEYCLOAK_SERVICE_USER"],
                          os.environ["KEYCLOAK_SERVICE_PASSWORD"])


def api(path, tok, method="GET", body=None):
    """
    Call the admin API for the FederatedNode realm.

    Returns the decoded body, or None when the response has none -- PUT and DELETE here reply 204.
    """
    req = urllib.request.Request(
        f"{BASE}/admin/realms/{REALM}{path}", method=method,
        headers={"Authorization": f"Bearer {tok}", "Content-Type": "application/json"},
        data=json.dumps(body).encode() if body is not None else None,
    )
    resp = urllib.request.urlopen(req)
    raw = resp.read()
    return json.loads(raw) if raw else None


def client_credentials_works(secret, client_id="global"):
    """A client_credentials grant is the cleanest probe of whether a client secret is accepted."""
    data = urllib.parse.urlencode({
        "client_id": client_id, "client_secret": secret, "grant_type": "client_credentials",
    }).encode()
    try:
        urllib.request.urlopen(f"{BASE}/realms/{REALM}/protocol/openid-connect/token", data)
        return True
    except urllib.error.HTTPError:
        return False
