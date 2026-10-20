# Permissions and what is out of scope for the beta

For the beta only two identities matter: the administrator (the first Keycloak user, role Administrator) and the Dagster System user. Authentication hardening, audit and normal-user permissions wait for the authorization rework. This section lists what is out of scope so that it is not recorded as a defect, and keeps a few observation cases for things that are in the code but not designed yet.

## Out of scope for the beta

Do not test these as pass or fail. If you notice behaviour, write it down for the follow-up work.

- **Authentication, audit and normal-user permissions.** DAR and whitelisted images are disconnected until the authorization rework; every caller takes the plain path (admin scope or the endpoint's scope) ([Authorization detached from DAR, Keycloak and whitelisted images]). The mocked Keycloak in the unit tests cannot tell you what a normal user may do.
- **Isolation.** NetworkPolicy, RBAC and per-task Secrets are tracked on GitHub ([Task isolation: storage, secrets, namespace and network]).
- **The Gitea mirror.** It is developed on a separate branch as a stateless service that the node would see as a Gitea GitProvider; no end-to-end test covers it ([dagster/fncli/tests/e2e/README.md]).
- **Retrying a task.** Task retry is on hold until after the beta. A task failed by a rule, by a changed configuration or by its run stays failed, and there is no stale-task retry; the pull request has to be re-run another way ([A task is pinned to its configuration]).
- **Tasks requested through the API.** They are created, and run, but their results are not delivered: delivery needs a task that came from a pull request ([Results delivered as a pushed branch plus a results pull request]).
- **Backfill for anything but a project being enabled.** There is none for a link, a repository or a GitProvider switched back on ([Pull requests stored once per repository, fanned out to project links, with cursors]).
- **ProjectSecret.** The flags exist and nothing reads them ([docs/architecture/revoke-and-enabled.md#known-limits]).
- **Cancelling a task through the webserver.** The route is not implemented; cancelling a run in Dagster is mirrored onto the task ([task and result state machines](task-and-result-state-machines.md)).
- **After the beta:** a delivery decision endpoint like the launch one (an open question in [Responsibility: the webserver owns the record and the rules; Dagster carries out decisions]), generating the Dagster models from `openapi.json`, replacing the five run-status sensors with the reconcile sensor.

## What a normal (non-admin) user can do: observe only

Needs a Keycloak user without the Administrator role. Skip if there is none.

1. Log in as that user. Try `GET /global/secrets`, `GET /projects`, `GET /tasks`, `POST /global/datasets`, `PATCH` of a project's `enabled`, and `PATCH` with `{"revoked": true}`.

- **Expected:** `revoked` and the global write routes are refused (403). For everything else the sources do not say: write down which calls succeed. This is input for the authorization work, not a failure.
- **Rule:** `revoked` needs the Administrator role; global writes need the admin scope; other scopes are not designed yet ([docs/architecture/revoke-and-enabled.md#who-may-do-what]; [Authorization detached from DAR, Keycloak and whitelisted images]).
- **Automated by:** Partly automated: `webserver/tests/test_global_resources.py` and `webserver/tests/test_trigger_repositories_and_links.py` for the refusals, with a mocked Keycloak that lets a non-admin token through every other scope.
- [ ] Pass
- [ ] Fail — notes:

## Credentials stay out of logs, responses and command lines

Do not print any value. Count matches only.

1. After a full run (happy path with a delivery), count lines that mention a header or a token in the backend log and in a delivery run's log: `kubectl logs <pod> | grep -c -i "bearer\|authorization"`. If the count is not zero, use `grep -n` to find the lines and read only those, looking for credential text. Never paste a value into the notes.
2. Look at the process arguments of a delivery run while it pushes (`kubectl exec <pod> -- ps`, if the image has it) and at the git remote URL in its logs.
3. Read the responses of `GET /global/secrets`, `GET /global/datasets` and `GET /global/repositories/triggers`.

- **Expected:** no token or password in the logs, in the arguments or in the remote URL. The push passes the token in an environment variable used as an extra HTTP header. No response carries a Secret value (only the reference).
- **Rule:** responses return secret references only, never values; the push uses the token in an `http.extraHeader` env, never in the URL or arguments ([Global resources, linked to projects]; [Results delivered as a pushed branch plus a results pull request]).
- **Automated by:** Partly automated: `dagster/app/tests/test_results_delivery.py` (`test_the_token_stays_out_of_the_command_line`) and `webserver/tests/test_global_resources.py` (values hidden). Real logs are not scanned. A leaked git token must also be revoked at the git host.
- [ ] Pass
- [ ] Fail — notes:

## A task pod runs without a Kubernetes service-account token

1. While a task is `RUNNING`, find its pod in the task namespace (`kubectl get pods -A`) and `kubectl describe pod <pod>`. Look at Mounts and Volumes.

- **Expected:** no service-account token is mounted in the task pod; the artifacts volume and the dataset connection details are. This is a spot check; the wider isolation work is out of scope.
- **Rule:** the task pod builder gives the pod no service-account token (`dagster/app/tests/test_pipes.py`; no decision record covers it, check).
- **Automated by:** Partly automated: `dagster/app/tests/test_pipes.py` (`test_task_pod_gets_no_service_account_token`); not checked on a real pod.
- [ ] Pass
- [ ] Fail — notes:

## Retrying a task that has not failed is refused (observation)

Retry is on hold; this only records the refusal.

1. `POST /projects/<pid>/tasks/<id>/retry` for a `SUCCESS` task.

- **Expected:** 400 (a retry only applies to `FAILED` or `CANCELED`), and the task is unchanged. Do not retry failed tasks as part of the beta.
- **Rule:** the only way out of a final status is a retry, and it needs `FAILED` or `CANCELED` ([State transition tables for triggers, tasks and result steps; 409 on a refused move]).
- **Automated by:** Automated: `webserver/tests/test_pull_requests_and_tasks.py` (`test_retry_resets_a_failed_task_only`). It misses only the live node (mocked Keycloak).
- [ ] Pass
- [ ] Fail — notes:

<!-- link definitions -->
[A task is pinned to its configuration]: ../decisions/0009-task-pinned-to-its-configuration.md
[Authorization detached from DAR, Keycloak and whitelisted images]: ../decisions/0017-authorization-detached-from-dar-and-keycloak.md
[Global resources, linked to projects]: ../decisions/0006-global-resources-and-project-links.md
[Pull requests stored once per repository, fanned out to project links, with cursors]: ../decisions/0011-pull-requests-stored-once-fan-out-and-cursors.md
[Responsibility: the webserver owns the record and the rules; Dagster carries out decisions]: ../decisions/0021-webserver-owns-the-record-and-the-rules.md
[Results delivered as a pushed branch plus a results pull request]: ../decisions/0013-results-delivered-as-branch-and-pull-request.md
[State transition tables for triggers, tasks and result steps; 409 on a refused move]: ../decisions/0005-state-transition-tables.md
[Task isolation: storage, secrets, namespace and network]: ../decisions/0022-task-isolation.md
[dagster/fncli/tests/e2e/README.md]: ../../dagster/fncli/tests/e2e/README.md
[docs/architecture/revoke-and-enabled.md#known-limits]: ../../docs/architecture/revoke-and-enabled.md#known-limits
[docs/architecture/revoke-and-enabled.md#who-may-do-what]: ../../docs/architecture/revoke-and-enabled.md#who-may-do-what
