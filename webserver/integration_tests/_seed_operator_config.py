"""Seed configuration an operator might add by hand, none of it present in realms.json."""
from kc_api import api, service_token

tok = service_token()

api("/identity-provider/instances", tok, "POST", {
    "alias": "operator-oidc", "providerId": "oidc", "enabled": True,
    "config": {"clientId": "x", "clientSecret": "y",
               "authorizationUrl": "https://example.invalid/auth",
               "tokenUrl": "https://example.invalid/token"},
})
# A realm setting the platform does not own.
rep = api("", tok)
rep["resetPasswordAllowed"] = True
api("", tok, "PUT", rep)
# A role outside realms.json.
api("/roles", tok, "POST", {"name": "operator-defined-role"})
print("  seeded operator configuration")
