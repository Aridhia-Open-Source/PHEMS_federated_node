# Secrets and quarantine

A Secret is a reference to a value in the store (Kubernetes). Switching a Secret off moves its value to a quarantine namespace and switches off every dataset, trigger repository and results repository that uses it; switching it on moves the value back but does not switch them on again. The unit tests run this against an in-memory store, so the real move is only checked here.

Needs: an administrator token and `kubectl`. To see where a value is, list names only: `kubectl get secret -A | grep <key>` (the key is `fn-secret-<label>`). Never print a Secret's data (`-o yaml`, `-o json`, `jsonpath`), and never write a value into the notes. Use a scratch Secret and scratch GlobalResources for the destructive cases. The quarantine namespace name is not in the sources: find it from the first case and write it down (check).

## Disabling a Secret moves its value out and switches off what uses it

1. On the dev project: `kubectl get secret -A | grep fn-secret-` and note the namespace of the trigger Secret.
2. `fncli secret-set --entity trigger --enabled false`.
3. `kubectl get secret -A | grep <key>` again. `GET /global/secrets/<label>` and `GET /global/repositories/triggers/<id>`. `fncli project-show` (the trigger resource `active`).

- **Expected:** the value is now in the quarantine namespace, not the original one. The Secret's row keeps the original namespace, so reads of it fail while it is moved. The Secret is `enabled: false`, and so is every GlobalResource that uses it (here the trigger repository; the project resource is inactive). The change is one commit: if the move fails the request fails and nothing changes.
- **Rule:** disabling a Secret also disables what uses it and quarantines its value ([docs/architecture/revoke-and-enabled.md#secrets]; [Generic Secret model and SecretProvider; per-repository tokens]).
- **Automated by:** Partly automated: `nexus/api/tests/test_secrets_quarantine.py` (in-memory store); the end-to-end failure suite, group "a PR merged while the trigger repository's Secret is switched off gets no task" (`dagster/fncli/tests/e2e/test_failure_paths.py`, written, never run on a cluster). Both miss the real Kubernetes move and the quarantine namespace.
- [ ] Pass
- [ ] Fail — notes:

## Enabling a Secret brings the value back and does not switch the users on

1. Continue from the previous case: `fncli secret-set --entity trigger --enabled true`.
2. Check the namespace of the value, then `fncli project-show` (the trigger resource `active`).
3. `fncli global-set trigger --enabled true`, then `fncli project-show` again.

- **Expected:** the value is back in its original namespace. The trigger repository is still off and the project resource still inactive after step 1; it is active only after step 3. Pull requests merged while it was off get no trigger (the gap is skipped; see [enabled and revoked: trigger side](enabled-and-revoked-ingest-side.md)).
- **Rule:** enabling a Secret does not re-enable them; it is two steps ([docs/architecture/revoke-and-enabled.md#secrets]).
- **Automated by:** Partly automated: the same unit file and end-to-end group as above; they miss a Secret shared by more than one GlobalResource (next case).
- [ ] Pass
- [ ] Fail — notes:

## A Secret shared by two GlobalResources switches both off

1. Create a scratch Secret and two scratch GlobalResources that name it (for example a dataset and a trigger repository).
2. Disable the Secret.
3. Enable the Secret, then enable one of the two GlobalResources.

- **Expected:** step 2 switches off both in the same commit. Step 3 leaves the second one off.
- **Rule:** the same as the previous case, for every user of the Secret ([docs/architecture/revoke-and-enabled.md#secrets]).
- **Automated by:** Partly automated: `nexus/api/tests/test_global_resources.py` (`test_disabling_a_secret_disables_what_uses_it_and_enabling_it_does_not_enable_it_again`); it misses the real store and a live pipeline using both.
- [ ] Pass
- [ ] Fail — notes:

## A GlobalResource cannot be enabled, created or repointed onto a disabled Secret

1. Disable a scratch Secret that a scratch dataset uses.
2. `PATCH` the dataset with `{"enabled": true}`.
3. `PATCH` it with `secret_label` naming the disabled Secret, then with a different, enabled Secret.
4. Create a repository that names the disabled Secret.
5. Delete the Secret (with force), then try to enable a dataset that used it.

- **Expected:** step 2 is 409. Step 3: naming the disabled Secret is 400; naming an enabled one works, after which step 2 works. Step 4 is 400. Step 5: enabling is 409 until the dataset is repointed.
- **Rule:** enabling a GlobalResource whose Secret is disabled or deleted is a 409; naming a disabled Secret is a 400 ([docs/architecture/revoke-and-enabled.md#secrets]).
- **Automated by:** Automated: `nexus/api/tests/test_secrets_quarantine.py`, `nexus/api/tests/test_global_resources.py`; a live node adds only the real store.
- [ ] Pass
- [ ] Fail — notes:

## A disabled Secret cannot be rotated unless the same request enables it

1. With the scratch Secret disabled, `PATCH /global/secrets/<label>` with new `values`.
2. `PATCH` with `{"enabled": true, "values": {...}}`.
3. `PATCH` with `{"enabled": false, "values": {...}}` on an enabled Secret, then check where the new value is.

- **Expected:** step 1 is 409. Step 2 succeeds and the new value is in the original namespace. In step 3 the new value ends up in quarantine, not in the original namespace.
- **Rule:** rotating a disabled Secret is a 409 unless the same request enables it ([docs/architecture/revoke-and-enabled.md#secrets]).
- **Automated by:** Partly automated: `nexus/api/tests/test_secrets_quarantine.py`; it misses the real store.
- [ ] Pass
- [ ] Fail — notes:

## A Secret created disabled is stored in quarantine

1. `POST /global/secrets` for a scratch label with `enabled` false (check the field name in the create route).
2. List names with `kubectl get secret -A | grep <key>`.

- **Expected:** the value is in the quarantine namespace from the start; the Secret is disabled.
- **Rule:** a Secret created disabled is stored in quarantine ([docs/architecture/revoke-and-enabled.md#secrets]).
- **Automated by:** Partly automated: `nexus/api/tests/test_secrets_quarantine.py` (`test_a_secret_created_disabled_is_stored_in_quarantine`); it misses the real store.
- [ ] Pass
- [ ] Fail — notes:

## Deleting a Secret is refused while an enabled GlobalResource uses it

1. `DELETE /global/secrets/<label>` for a scratch Secret used by an enabled dataset.
2. Disable the dataset and delete again.
3. Repeat with a new scratch Secret and `DELETE ...?force=true`.
4. `kubectl get secret -A | grep <key>` after each delete.

- **Expected:** step 1 is 409 naming the users. Step 2 works; the value is deleted from its namespace, or from quarantine if the Secret was disabled. Step 3 disables the users first and then deletes.
- **Rule:** a Secret in use cannot be deleted; `force` disables its users first ([docs/architecture/revoke-and-enabled.md#secrets]).
- **Automated by:** Partly automated: `nexus/api/tests/test_secrets_quarantine.py`, `nexus/api/tests/test_global_resources.py`; they miss the real store.
- [ ] Pass
- [ ] Fail — notes:

## The healthcheck of a disabled Secret does not read the store

1. Disable a scratch Secret.
2. `GET /global/secrets/<label>/healthcheck`.

- **Expected:** the check reports `secret_missing` (disabled), and does not read the store. No value is returned.
- **Rule:** the healthcheck of a disabled Secret reports `secret_missing` without reading the store ([docs/architecture/revoke-and-enabled.md#secrets]).
- **Automated by:** Automated: `nexus/api/tests/test_secrets_quarantine.py`, `nexus/api/tests/test_healthchecks_all.py`. They miss the real store.
- [ ] Pass
- [ ] Fail — notes:

## A disabled results Secret holds a delivery, which resumes once both are on

Run it after [run a task and deliver the result](run-a-task-and-deliver-the-result.md) passes.

1. Merge a watched pull request. While the task is `RUNNING` run `fncli secret-set --entity results --enabled false`.
2. Let the task finish. Watch `fncli project-show` results.
3. `fncli secret-set --entity results --enabled true`, then `fncli global-set results --enabled true`.

- **Expected:** the results repository is switched off with the Secret, so the result is recorded `FAILED` with "results resource switched off" and held, and nothing is pushed. After step 3 the delivery retry sensor delivers it (result `OPENED`). If a delivery attempt instead fails while reading the token, record the error text: the sources say a delivery fails when it reads a disabled Secret and is retried until the attempts run out (check which path happens).
- **Rule:** a disabled Secret switches off the ResultsRepository using it; a switched-off results resource holds the result ([Enabled, revoked and soft delete]).
- **Automated by:** Partly automated: `dagster/app/tests/test_results_delivery.py` (a disabled Secret fails the delivery before its token is read) and the unit tests for the held result. Neither combines the Secret with a live delivery; the end-to-end held-result group switches off the results resource only.
- [ ] Pass
- [ ] Fail — notes:

## A task whose dataset's Secret is disabled fails at launch

Needs the launcher stopped so the task is still `PENDING` (see "Make a change while a task is still PENDING" in [the index](README.md)).

1. Stop the launcher, merge a watched pull request, wait for the task to be `PENDING`.
2. `fncli secret-set --entity dataset --enabled false`.
3. Start the launcher.

- **Expected:** the task goes `FAILED` at launch with a cause naming the dataset. The dataset was switched off with its Secret, so the cause may say the dataset is not active rather than that the Secret is disabled (check and record the text). No run, no result.
- **Rule:** the launcher fails a task whose dataset resource is not active or whose dataset's Secret is disabled ([Responsibility: nexus-api owns the record and the rules; Dagster carries out decisions]).
- **Automated by:** Partly automated: `nexus/api/tests/test_task_config.py` (the order of the two causes); it misses the live launcher.
- [ ] Pass
- [ ] Fail — notes:

<!-- link definitions -->
[Enabled, revoked and soft delete]: ../decisions/0008-enabled-revoked-and-soft-delete.md
[Generic Secret model and SecretProvider; per-repository tokens]: ../decisions/0007-secrets-and-secret-providers.md
[Responsibility: nexus-api owns the record and the rules; Dagster carries out decisions]: ../decisions/0021-nexus-api-owns-the-record-and-the-rules.md
[docs/architecture/revoke-and-enabled.md#secrets]: ../../docs/architecture/revoke-and-enabled.md#secrets
