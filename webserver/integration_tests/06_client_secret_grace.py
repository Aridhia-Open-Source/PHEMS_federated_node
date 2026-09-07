"""
Client secret rotation must keep the PREVIOUS secret alive for a grace period.

Depends on migration 2's secret-rotation policy, which needs the `client-secret-rotation` Keycloak
feature (off by default, enabled in build/keycloak/kc-features.txt).
"""
from kc_api import api, check, client_credentials_works, report, service_token

print("=== Client secret rotation keeps the previous secret alive (the grace period) ===")

tok = service_token()
gid = api("/clients?clientId=global", tok)[0]["id"]

old_secret = api(f"/clients/{gid}/client-secret", tok)["value"]
check(client_credentials_works(old_secret), "current client secret authenticates")

new_secret = api(f"/clients/{gid}/client-secret", tok, method="POST")["value"]
check(new_secret != old_secret, "rotation produced a different secret")
check(client_credentials_works(new_secret), "NEW client secret authenticates")

# The heart of it.
check(client_credentials_works(old_secret),
      "PREVIOUS client secret still authenticates (grace period active)")

rotated = api(f"/clients/{gid}/client-secret/rotated", tok)
check(rotated.get("value") == old_secret,
      "Keycloak reports the previous secret via /client-secret/rotated")

# Invalidating early is how the rotation job closes the window once every pod has moved on.
api(f"/clients/{gid}/client-secret/rotated", tok, method="DELETE")
check(not client_credentials_works(old_secret),
      "previous secret stops working once explicitly invalidated")
check(client_credentials_works(new_secret),
      "new secret still authenticates after invalidating the old one")

report()
