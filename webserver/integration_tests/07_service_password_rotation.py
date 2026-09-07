"""
Service password rotation is a hard cutover, unlike the client secret above.

Keycloak has no dual-password concept, which is why consumers must retry on auth failure after
re-reading the credential, and why the rotation job patches Kubernetes immediately after changing
Keycloak.
"""
import os

from kc_api import api, check, password_token, report

print("=== Service password rotation takes effect immediately (no grace period) ===")

user = os.environ["KEYCLOAK_SERVICE_USER"]
old_pw = os.environ["KEYCLOAK_SERVICE_PASSWORD"]
new_pw = "rotated-service-password-1"


def set_password(tok, uid, password):
    api(f"/users/{uid}/reset-password", tok, "PUT",
        {"type": "password", "temporary": False, "value": password})


tok = password_token(user, old_pw)
check(tok is not None, "service account authenticates before rotation")

uid = api(f"/users?username={user}&exact=true", tok)[0]["id"]
set_password(tok, uid, new_pw)

check(password_token(user, new_pw) is not None, "new password authenticates immediately")
check(password_token(user, old_pw) is None,
      "old password stops working at once (no grace -- consumers must retry)")

# Put it back, so a later run of this suite still works.
set_password(password_token(user, new_pw), uid, old_pw)

report()
