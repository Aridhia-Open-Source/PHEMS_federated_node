# Known issues

Open items and the known limits in [docs/architecture/revoke-and-enabled.md#known-limits]. They are known: a case here does not fail the beta by itself. Run the case, write down what the node does today, and say whether it still matches the description. Where the description and a unit test disagree, that is a finding.

Needs: the dev project, an administrator login, and the second project (`fncli second-project-setup QaTwo`) for the destructive cases.

## Deleting a trigger link that has pull requests

1. Run a watched pull request through so the second project has a trigger (`fncli second-project-setup QaTwo` before the merge).
2. `DELETE /projects/<QaTwo pid>/repositories/triggers/<id>`.
3. `fncli second-project-teardown QaTwo` when finished.

- **Expected today:** this returns a raw foreign-key 400 rather than a 409. Record the status and the body. A link cannot be removed for real while triggers exist, so the link should stay.
- **Rule:** a link cannot be removed for real while triggers exist (`RESTRICT`) ([Pull requests stored once per repository, fanned out to project links, with cursors]).
- **Automated by:** Manual only. No test asserts the status for this case.
- [ ] Pass (matches the expected result above)
- [ ] Fail (differs; note what you saw)

## `PATCH /global/secrets/<label>` has no admin-only check and uses local time

1. With a non-admin token (skip if there is none): `PATCH /global/secrets/<scratch label>` with a changed `description`.
2. Compare the Secret's `updated_at` with `date -u`.

- **Expected today:** the route has no admin-only check and sets `updated_at` from local time. Record whether the PATCH is accepted and the time offset.
- **Rule:** global writes need the admin scope ([Global resources, linked to projects]).
- **Automated by:** Partly automated: `webserver/tests/test_global_resources.py` (`test_a_non_admin_is_refused_on_the_write_routes_of_the_global_resources`); check whether it covers the Secret `PATCH`. It may not cover the Secret `PATCH` or the time zone.
- [ ] Pass (matches the expected result above)
- [ ] Fail (differs; note what you saw)

## A revoked Secret link is not checked when a token is read

This is a probe from the end-to-end README, not a pass or fail there.

1. `fncli link-set secret --revoked true`. `fncli open-pr --kind watched --merge`. Watch the pull request and the task.
2. `fncli link-set secret --revoked false`.

- **Expected today:** the pull request is processed as usual: the link is not read when the token is read.
- **Rule:** `ProjectSecret` has the flags but nothing reads them ([Enabled, revoked and soft delete], open questions).
- **Automated by:** Manual only (an end-to-end probe).
- [ ] Pass (matches the README)
- [ ] Fail (differs; note what you saw)

## `GET /tasks` clamps `page` and `per_page`, and dataset `PATCH` returns 200

1. `GET /tasks?page=0&per_page=0`, then `?page=-1`.
2. `PATCH /global/datasets/<id>` with a harmless change.

- **Expected today:** step 1 returns 200 with values clamped to 1 rather than a 400; step 2 returns 200. Both are listed as open questions.
- **Rule:** open questions in [Global resources, linked to projects].
- **Automated by:** Partly automated: `webserver/tests/test_pagination_and_filters.py`. It misses a live node.
- [ ] Pass (matches the open question)
- [ ] Fail (differs; note what you saw)

## The Keycloak realm init pod may crash-loop after deploy

1. `kubectl get pods -A | grep -i realm-init` and `kubectl logs` of that pod.
2. Run the happy path ([run a task and deliver the result](run-a-task-and-deliver-the-result.md)).

- **Expected today:** the `keycloak-realm-init` pod can crash-loop on realm migration 2 (a 400, "client profile contains the executor which does not have valid provider"); the end-to-end suites still run. Record whether it crash-loops on your release and whether sign-in and the pipeline work.
- **Rule:** none; a known issue listed on this page.
- **Automated by:** Manual only. `webserver/integration_tests/` exercise the Keycloak initialiser against a real Keycloak, not this deploy.
- [ ] Pass (matches the expected result above)
- [ ] Fail (differs; note what you saw)

## A very fast task has a `started_at`

1. `fncli open-pr --kind failing --merge` (the task ends in seconds). When it is `FAILED`, `GET /projects/<pid>/tasks/<id>`.

- **Expected today:** a task that goes `STARTED` to final between two sensor ticks gets `started_at` from the run record's `start_time`; whether Dagster fills it for such a run is unconfirmed. Record whether `started_at` is set.
- **Rule:** the status mapping in [Task status is written by the run-status sensors and the reconcile sensor].
- **Automated by:** Partly automated: `dagster/app/tests/test_task_run_status_sensor.py` (`test_a_run_with_no_start_time_records_only_when_it_ended`). The real run record is not tested.
- [ ] Pass (set)
- [ ] Fail (empty; note what you saw)

## Known limits to keep in mind (no case; covered in the sections named)

- A result recorded before a revoke keeps its step and state until the results route is called for it again; a non-final `FAILED` result is set `REVOKED` on its next attempt ([enabled and revoked: launch and delivery](enabled-and-revoked-launch-and-delivery.md)).
- A running task is not stopped by a revoke, and a delivery already past the results check is not stopped either; a push in progress may still complete. A leaked git token must also be revoked at the git host.
- A project that is both revoked and disabled keeps its waiting tasks waiting; they fail once it is enabled.
- A delivery that stays `FAILED` after the maximum attempts raises no alert ([task and result state machines](task-and-result-state-machines.md)).
- A `CLOSED` result is terminal: a results pull request reopened on the provider is not followed; one deleted on the provider stays at its last step.
- The failure suite's check that a failed ingest tick's error text contains "Ingest failed" reads the tick error's `stack` and `causes`; that Dagster puts the text there is unconfirmed ([failure paths](failure-paths.md)).
- The ingest-versus-link-create race, and `get_or_assign_*` in fncli returning an existing link with different settings (setup tooling): no case; they need fault injection.
- The cross-project loop check keys on provider and repository path, so the same server under two host names is not seen.
- `openapi.json` is not regenerated for the `revoked` fields.
- A leaked or lost token on the git side is a separate action at the git host.

## Items that look out of date

Check this against the checked-out code and update this page.

- The end-to-end README names the admin login variables `FNCLI_ADMIN_USER` and `FNCLI_ADMIN_PASSWORD`; the code logs in with the first Keycloak user stored in the `keycloak-first-user` secret by `deploy.sh`, from `KEYCLOAK_FIRST_USER_EMAIL` and `KEYCLOAK_FIRST_USER_PASSWORD` in `.dev.env`.

<!-- link definitions -->
[Enabled, revoked and soft delete]: ../decisions/0008-enabled-revoked-and-soft-delete.md
[Global resources, linked to projects]: ../decisions/0006-global-resources-and-project-links.md
[Pull requests stored once per repository, fanned out to project links, with cursors]: ../decisions/0011-pull-requests-stored-once-fan-out-and-cursors.md
[Task status is written by the run-status sensors and the reconcile sensor]: ../decisions/0003-task-status-written-by-run-status-sensors.md
[docs/architecture/revoke-and-enabled.md#known-limits]: ../../docs/architecture/revoke-and-enabled.md#known-limits
