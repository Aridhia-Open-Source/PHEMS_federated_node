"""Realm state after the runs above: credentials, migration version, and the authz model."""
from kc_api import api, check, password_token, report, service_token

print("=== Realm state assertions ===")

svc = service_token()
check(svc is not None, "fn-service can authenticate against the FederatedNode realm")
if not svc:
    report()

# fn-service must be able to drive the admin API, i.e. Super Administrator really is sufficient and
# no realm-management composites migration is needed.
try:
    api("/clients?clientId=global", svc)
    api("/users?max=1", svc)
    api("/roles", svc)
    check(True, "fn-service can drive the admin API (clients, users, roles)")
except Exception as exc:
    check(False, f"fn-service cannot drive the admin API: {exc}")

# The operator's console account must exist in master, be temporary, and NOT exist in the
# FederatedNode realm any more.
boot = password_token("tmpadmin-1", "password1", "master")
check(boot is None, "bootstrap user was deleted (no longer a standing master-realm admin)")

fn_admins = api("/users?username=admin&exact=true", svc)
check(len(fn_admins) == 0, "no `admin` user in the FederatedNode realm (fn-service replaces it)")

# The realm migration version must be recorded, so the next run is a no-op.
realm_rep = api("", svc)
version = (realm_rep.get("attributes") or {}).get("fn_realm_version")
check(version == "2", f"realm records fn_realm_version=2 (got {version!r})")

# The secret rotation policy must actually be present -- without it, rotation is an immediate
# cutover rather than a grace-period handover.
policies = api("/client-policies/policies", svc)
names = [p.get("name") for p in (policies.get("policies") or [])]
check("fn-client-secret-rotation-policy" in names,
      f"client secret rotation policy is configured (policies: {names})")
profiles = api("/client-policies/profiles", svc)
pnames = [p.get("name") for p in (profiles.get("profiles") or [])]
check("fn-client-secret-rotation" in pnames,
      f"client secret rotation profile is configured (profiles: {pnames})")

# The FN authz model lives inside the `global` client, which partialImport SKIPs. Confirm it is
# intact -- if a future change switched SKIP to OVERWRITE, this is what would break.
gid = api("/clients?clientId=global", svc)[0]["id"]
scopes = api(f"/clients/{gid}/authz/resource-server/scope", svc)
scope_names = {s["name"] for s in scopes}
expected = {"can_admin_dataset", "can_exec_task", "can_access_dataset", "can_do_admin"}
check(expected.issubset(scope_names),
      f"global client authz scopes intact (missing: {sorted(expected - scope_names)})")

report()
