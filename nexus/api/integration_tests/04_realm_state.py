"""Realm state after the runs above: credentials, migration version, and the authz model."""
import os
from urllib.parse import quote

from kc_api import api, check, claims, password_token, report, service_token

NODE_ROLES = {"SuperUser", "Administrator", "Service", "Users", "Dagster"}
ROLE_GROUPS = {"superuser": "SuperUser", "admins": "Administrator", "service": "Service",
               "users": "Users", "dagster": "Dagster"}

print("=== Realm state assertions ===")

svc = service_token()
check(svc is not None, "fn-service can authenticate against the FederatedNode realm")
if not svc:
    report()

# fn-service must be able to drive the admin API: realm-management's realm-admin, held directly, is
# sufficient.
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
check(version == "3", f"realm records fn_realm_version=3 (got {version!r})")

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

# ADR 0037: five node roles, none including another, each carried by one /roles group.
role_names = {r["name"] for r in api("/roles?max=200", svc)}
check(NODE_ROLES <= role_names, f"the five node roles exist (missing: {sorted(NODE_ROLES - role_names)})")
check(not {"Super Administrator", "System"} & role_names, "the old Super Administrator and System roles are gone")
for role in sorted(NODE_ROLES):
    inner = api(f"/roles/{quote(role)}/composites/realm", svc)
    check(not inner, f"{role} includes no other realm role (got {[r['name'] for r in inner]})")
for group, role in ROLE_GROUPS.items():
    group_id = api(f"/group-by-path/roles/{group}", svc)["id"]
    mapped = [r["name"] for r in api(f"/groups/{group_id}/role-mappings/realm", svc)]
    check(mapped == [role], f"/roles/{group} carries {role} only (got {mapped})")
top_groups = {g["name"] for g in api("/groups", svc)}
check(not {"Administrator", "Super Administrator", "Users"} & top_groups, "the old role-named groups are gone")

# fn-service: realm-admin directly, no node role.
svc_user = api(f"/users?username={os.environ['KEYCLOAK_SERVICE_USER']}&exact=true", svc)[0]
svc_realm = {r["name"] for r in api(f"/users/{svc_user['id']}/role-mappings/realm/composite", svc)}
check(not NODE_ROLES & svc_realm, f"fn-service holds no node role (got {sorted(NODE_ROLES & svc_realm)})")

# The first user signs in through the global client with exactly one node role and the groups claim.
user_tok = password_token("test@admin.com", "test123!", client_id="global",
                          client_secret=os.environ["KEYCLOAK_SECRET"])
check(user_tok is not None, "the first user can sign in through the global client")
if user_tok:
    payload = claims(user_tok)
    held = NODE_ROLES & set(payload.get("realm_access", {}).get("roles", []))
    check(held == {"Administrator"}, f"the first user's token carries Administrator only (got {sorted(held)})")
    check("/roles/admins" in payload.get("groups", []), f"the token's groups claim has /roles/admins "
          f"(got {payload.get('groups')})")

# The superuser is in /roles/superuser.
supers = api("/users?username=superuser&exact=true", svc)
check(len(supers) == 1, "the superuser exists")
if supers:
    groups = [g["path"] for g in api(f"/users/{supers[0]['id']}/groups", svc)]
    check(groups == ["/roles/superuser"], f"the superuser is in /roles/superuser only (got {groups})")

# The global client's role policies name the new roles, so nexus-api's can_* scopes keep working.
policies = {p["name"]: p for p in api(f"/clients/{gid}/authz/resource-server/policy?type=role", svc)}
expected_policies = {
    "admin-policy": {"Administrator", "SuperUser", "Service"},
    "system-policy": {"Dagster"},
}
for name, roles in expected_policies.items():
    detail = api(f"/clients/{gid}/authz/resource-server/policy/role/{policies[name]['id']}", svc)
    got = {api(f"/roles-by-id/{r['id']}", svc)["name"] for r in detail.get("roles", [])}
    check(got == roles, f"{name} names {sorted(roles)} (got {sorted(got)})")

report()
