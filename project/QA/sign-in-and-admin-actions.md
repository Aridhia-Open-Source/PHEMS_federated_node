# Sign-in and admin-only actions

Who can sign in, and which actions only an administrator may do. For the beta only two identities matter: the administrator (the first Keycloak user) and the Dagster System user. Normal-user permissions are out of scope ([permissions and out of scope](permissions-and-out-of-scope.md)).

Needs: the administrator's login. Never write a password or token into the notes.

## The administrator can sign in and call an admin route

1. Log in as the first Keycloak user (the Administrator the chart creates from `firstUserSecret`).
2. With the token, `GET /global/secrets` and `GET /projects`.

- **Expected:** both return 200 and a list. No Secret value is in the response.
- **Rule:** creating GlobalResources and writing their flags needs the admin role ([Global resources and project resources]).
- **Automated by:** Partly automated: the failure suite logs in as the first Keycloak user before it starts (`dagster/fncli/tests/e2e/test_failure_paths.py`, the admin login check). The webserver tests mock Keycloak, so real logins are not covered elsewhere.
- [ ] Pass
- [ ] Fail — notes:

## The Dagster System user works for the pipeline

1. Run `fncli project-show` and `fncli project-set --enabled true` (both log in as the System user).
2. Open `fncli sensor-status` after a few intervals.

- **Expected:** both fncli calls succeed. No sensor tick fails with an authentication error.
- **Rule:** the Dagster side authenticates to the backend with a Keycloak System user ([Authorization detached from DAR, Keycloak and whitelisted images]).
- **Automated by:** Partly automated: `webserver/tests/test_system_user_routes.py` (mocked Keycloak) and every end-to-end run; it misses expiry and refresh (see [failures mid-flow and limits](failures-mid-flow-and-limits.md)).
- [ ] Pass
- [ ] Fail — notes:

## The System user can never revoke or un-revoke

1. Send `PATCH /projects/<pid>/repositories/triggers/<id>` with `{"revoked": true}` using the System user's token. Skip this case if you cannot get that token without reading the Secret that holds it (do not decode it).
2. For comparison, `fncli resource-set trigger --revoked true` (it logs in as the first Keycloak user) and then `--revoked false`.

- **Expected:** step 1 is refused with 403 and nothing changes. Step 2 returns 200 both ways.
- **Rule:** `revoked` is set only by administrators; the pipeline's System user can never revoke ([Enabled, revoked and soft delete]).
- **Automated by:** Partly automated: `webserver/tests/test_system_user_routes.py`, `dagster/fncli/tests/test_state.py` (which login each command uses) and the end-to-end revoke groups. The tests mock the role check.
- [ ] Pass
- [ ] Fail — notes:

## A non-admin user cannot revoke or write GlobalResources

Needs a Keycloak user without the Administrator role. If there is none, mark Not run: normal-user permissions are out of scope, so this is an observation.

1. With that user's token send `PATCH` with `{"revoked": true}` on a project resource, and `POST /global/datasets`.

- **Expected:** both are refused (403). Record what a normal user can read, for the follow-up work.
- **Rule:** `revoked` needs the Administrator role on every route that has it; global writes need the admin scope ([docs/architecture/revoke-and-enabled.md#who-may-do-what]).
- **Automated by:** Partly automated: `webserver/tests/test_trigger_repositories_and_resources.py` (`test_revoke_admin_only`) and `webserver/tests/test_global_resources.py` (non-admin refused on the write routes). The mocked Keycloak lets a non-admin token through every scope except `revoked`, so scopes are not tested for real.
- [ ] Pass
- [ ] Fail — notes:

## `revoked` cannot be set when creating or assigning

1. `POST /global/datasets` (and one repository) with `"revoked": true` in an otherwise valid body.
2. `PUT /projects/<pid>/repositories/triggers/<id>` with `"revoked": true` in the body.

- **Expected:** 400 each time, and nothing is created or changed.
- **Rule:** `revoked` is the controller's flag, set only by an admin `PATCH` ([Global resources and project resources]).
- **Automated by:** Automated: `webserver/tests/test_create_refuses_revoked.py` for the create routes (it misses real roles, since Keycloak is mocked). The PUT case is a rule in the decision; check it by hand.
- [ ] Pass
- [ ] Fail — notes:

## A request without a token is refused

1. `GET /tasks` with no `Authorization` header.

- **Expected:** 401 or 403, and no data.
- **Rule:** every caller goes through the plain authorization check, a valid token and the endpoint's scope ([Authorization detached from DAR, Keycloak and whitelisted images]). The password reset route is the one known exception (check).
- **Automated by:** Partly automated: `webserver/tests/test_all_tasks_list.py` (`test_unauthenticated_is_refused`) and `webserver/tests/test_task_launch.py`; they use the mocked Keycloak.
- [ ] Pass
- [ ] Fail — notes:

<!-- link definitions -->
[Authorization detached from DAR, Keycloak and whitelisted images]: ../decisions/0017-authorization-detached-from-dar-and-keycloak.md
[Enabled, revoked and soft delete]: ../decisions/0008-enabled-revoked-and-soft-delete.md
[Global resources and project resources]: ../decisions/0006-global-resources-and-project-resources.md
[docs/architecture/revoke-and-enabled.md#who-may-do-what]: ../../docs/architecture/revoke-and-enabled.md#who-may-do-what
