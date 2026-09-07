"""Everything seeded before the kc-init run must still be there afterwards."""
from kc_api import api, check, report, service_token

tok = service_token()

idps = [i["alias"] for i in api("/identity-provider/instances", tok)]
check("operator-oidc" in idps, f"operator-added identity provider survives ({idps})")

rep = api("", tok)
check(rep.get("resetPasswordAllowed") is True,
      "operator realm setting survives (resetPasswordAllowed)")

roles = [r["name"] for r in api("/roles", tok)]
check("operator-defined-role" in roles, "operator-added realm role survives")

report()
