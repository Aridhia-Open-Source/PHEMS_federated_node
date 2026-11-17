# Operator and node config

The node's config is five kinds of custom resource in the API group `fn.aridhia.com/v1alpha1`: `GitProvider`, `NodeSecret`, `Repository`, `Dataset` and `Project`. The nexus operator (the `nexus-operator` Deployment) syncs each one to its nexus-api record: it creates or adopts the record, sends only what differs, and soft-deletes it when the resource is deleted. A record it manages is changed only through its custom resource: nexus-api refuses anyone else's change to a field the resource declares, and the record's removal, with a 409. These cases check that it does, and that it never does more.

Needs: the dev project applied and synced (see [the index](README.md)), the second project file `config/e2e/qa-two.yaml`, an administrator token for the HTTP checks, and the nexus-api and operator logs (`kubectl logs deploy/nexus-operator -n fn --tail=200`). For anything you make, copy a file from `config/e2e/` to a scratch file outside the repository and give it a scratch name (for example `qa-scratch`); delete it at the end. Never put a Secret value in a scratch file: a NodeSecret only names a Kubernetes Secret.

## Applying the config creates every record, and status says so

1. `kubectl get fn -A` after the setup in [the index](README.md).
2. `kubectl get project fn-dev -n fn -o yaml` and `kubectl get repository fn-trigger-repo -n fn -o yaml`.
3. `kubectl get events -n fn --field-selector reason=Synced`.
4. `GET /projects`, `GET /global/repositories/triggers`, `GET /global/datasets`, `GET /global/providers` and `GET /global/secrets`.

- **Expected:** every resource shows `Synced` `true` and an empty `Message`. Each status has `nexusId` (the record's id; none for a NodeSecret) and `observedGeneration` equal to `metadata.generation`. There is one `Synced` Event per resource that changed something. nexus-api has one record per resource, under the resource's name (a repository under its uri), and the project `fn-dev` is enabled with the dataset, trigger repository and results repository assigned with the settings in the file. Every one of these records has `managed_by` `fn-operator`.
- **Rule:** the custom resources are the node config; one sync per kind writes `synced`, `nexusId`, `message` and `observedGeneration` ([Declarative node config through an operator]).
- **Automated by:** Partly automated: the setup step `apply` of every end-to-end suite applies the files and waits for `status.synced`; `nexus/operator/tests/test_sync.py` (`test_provider_created_when_missing`, `test_dataset_created`, `test_new_project_created_disabled_then_enabled_last`) against a fake API; `nexus/api/tests/test_managed.py` (`test_operator_create_marks_the_record_and_others_get_a_409`) for `managed_by`. None looks at the Events or the record's settings on a live node.
- [ ] Pass
- [ ] Fail — notes:

## A resource waits for what it needs, in any order

1. Copy `config/e2e/qa-two.yaml` to a scratch file, rename the project `qa-scratch`, and add a dataset name that does not exist yet (`qa-scratch-dataset`) to `datasets`. `kubectl apply -f` it.
2. `kubectl get project qa-scratch -n fn`.
3. Write a scratch Dataset `qa-scratch-dataset` in namespace `experiments` with `secret: qa-scratch-creds`, and a NodeSecret `qa-scratch-creds` with `fromSecret: {name: qa-scratch-source}`. Apply the Dataset only, then the NodeSecret, then make the source: `kubectl create secret generic qa-scratch-source -n experiments --from-literal=USERNAME=x --from-literal=PASSWORD=x` (throwaway values). Look at each resource's status after each step.
4. `kubectl delete -f` the scratch files and `kubectl delete secret qa-scratch-source -n experiments`.

- **Expected:** in step 2 the project is `Synced` `false` with `Message` `waiting for dataset qa-scratch-dataset`, and no project `qa-scratch` exists in nexus-api yet. In step 3 the Dataset waits with `waiting for secret qa-scratch-creds`, the NodeSecret with `waiting for Secret qa-scratch-source`. Within one retry (60 seconds by default) of the source Secret existing, all three are synced and the project is enabled with both datasets. Step 4 removes all three records.
- **Rule:** order comes from retries; a resource whose dependency is missing is retried, with what it waits for in its status ([Declarative node config through an operator]).
- **Automated by:** Partly automated: `nexus/operator/tests/test_sync.py` (`test_project_waits_for_what_it_names`, `test_repository_waits_for_its_provider_and_secret`) against a fake API; nothing checks the NodeSecret's wait for its source Secret, or the retry delay on a cluster.
- [ ] Pass
- [ ] Fail — notes:

## `kubectl diff` previews a change to the config, not to nexus-api

1. In a copy of `config/e2e/fn-dev.yaml`, change the trigger's `watchDir` to `specs-qa/`. `kubectl diff -f` the copy.
2. `kubectl diff -f config/e2e/fn-dev.yaml` (no change).
3. `PATCH /projects/<pid>/repositories/triggers/<id>` with `{"watch_dir": "specs-qa/"}`, and at once `kubectl diff -f config/e2e/fn-dev.yaml` again.

- **Expected:** step 1 shows only the `watchDir` line, and changes nothing. Step 2 shows nothing. In step 3 the `PATCH` is refused (409, see the case on refused changes below), so the record is unchanged, and `kubectl diff` shows nothing either way: it compares the file with the custom resource, not with nexus-api.
- **Rule:** dev applies the config with `kubectl apply`, `kubectl diff` and `kubectl delete` ([Declarative node config through an operator]).
- **Automated by:** Manual only.
- [ ] Pass
- [ ] Fail — notes:

## Updating a resource changes only what differs

1. Copy `config/e2e/fn-dev.yaml` and change the results `targetDir` to `results-qa/`. `kubectl apply -f` the copy.
2. Wait until `observedGeneration` equals `metadata.generation` on `fn-dev`. `GET /projects/<pid>/repositories/results/<id>` and the state command.
3. Look at the nexus-api log for the calls the operator made.
4. `kubectl apply -f config/e2e/fn-dev.yaml` to put it back.

- **Expected:** the results resource has `target_dir` `results-qa/`; nothing else changed: the project stays enabled, the trigger resource and its cursor are untouched, no assignment is made again. The log shows one `PATCH` of the results resource. A task created before step 1 follows the rules in [task pinning](task-pinning.md). Step 4 puts it back the same way.
- **Rule:** each sync compares first and sends only what differs, because a `PUT` resets what its body leaves out ([Declarative node config through an operator]).
- **Automated by:** Partly automated: `nexus/operator/tests/test_sync.py` (`test_live_project_only_patched_where_it_differs`, `test_provider_patched_with_only_what_differs`) against a fake API; it misses the live cursor.
- [ ] Pass
- [ ] Fail — notes:

## A Project that drops a dataset or a trigger repository unassigns it

1. Apply the second project and run one watched pull request through it, so `qa-two` has a trigger and a task.
2. Copy `config/e2e/qa-two.yaml`, empty its `datasets` (`[]`) and its `triggers` (`[]`), and `kubectl apply -f` the copy.
3. `fncli project-show --project qa-two`. `GET /global/datasets/<id>` and `GET /global/repositories/triggers/<id>`.
4. `kubectl apply -f config/e2e/qa-two.yaml`, then `kubectl delete -f config/e2e/qa-two.yaml`.

- **Expected:** after step 2 `qa-two` has no dataset resource and no trigger resource; the GlobalResources are still there and still assigned to `fn-dev`. Step 4 assigns them again with fresh cursors (pull requests from before are not replayed), then removes the project. Unassigning a trigger resource that has pull requests is a [known issue](known-issues.md): record what you see.
- **Rule:** the Project lists what the project has; one it no longer names is unassigned ([Declarative node config through an operator]); unassigning revokes and soft-deletes the project resource ([Enabled, revoked and soft delete]).
- **Automated by:** Partly automated: `nexus/operator/tests/test_sync.py` (`test_live_project_unassigns_what_the_spec_dropped`) against a fake API; it misses pull requests and tasks in flight.
- [ ] Pass
- [ ] Fail — notes:

## Changing a live project's results repository disables it, swaps, and enables it again

1. Write a scratch Repository `qa-scratch-results` (`type: results`, uri `http://gitea.fn.svc:4000/gitea_admin/qa-scratch-results`, `secret: fn-results-repo-creds`) and run `fncli gitea setup -f config/gitea.yaml -f config/e2e/fn-dev.yaml -f <scratch file>` so the Gitea repository exists (it needs the NodeSecret's file too, and keeps the Secrets that exist). Apply it.
2. Copy `config/e2e/fn-dev.yaml` and point its results `repository` at the scratch uri. Apply the copy and watch the state command and the operator log.
3. Merge a watched pull request and wait for its result.
4. `kubectl apply -f config/e2e/fn-dev.yaml`, then delete the scratch Repository.

- **Expected:** in step 2 the operator disables the project, unassigns the old results repository, assigns the new one and enables the project, in that order; the project ends enabled with the new results resource. The result in step 3 is a pull request in `qa-scratch-results`. Step 4 swaps back the same way, and the scratch Repository's delete then goes through.
- **Rule:** a results repository is assigned only while the project is disabled and has none ([Global resources and project resources]); the operator disables, swaps and enables last ([Declarative node config through an operator]).
- **Automated by:** Partly automated: `nexus/operator/tests/test_sync.py` (`test_live_project_disabled_to_change_its_results_repository`) against a fake API; it misses tasks in flight while the project is briefly disabled.
- [ ] Pass
- [ ] Fail — notes:

## Deleting a resource soft-deletes its record

1. Apply the second project. Note its `nexusId`.
2. `kubectl delete -f config/e2e/qa-two.yaml`.
3. `GET /projects/<id>` and the project list. `kubectl get project qa-two -n fn`.
4. `kubectl apply -f config/e2e/qa-two.yaml` again, then delete it again.

- **Expected:** the delete returns once the operator has soft-deleted the record: `qa-two` is gone from the API (404) and from `kubectl get`. The GlobalResources it used stay, and `fn-dev` is untouched. Step 4 creates a new project under the same name (a new `nexusId`).
- **Rule:** a finalizer, `fn.aridhia.com/nexus-sync`, holds a removed resource until nexus-api has soft-deleted the record ([Declarative node config through an operator]); deletes are soft and a deleted name is free again ([Enabled, revoked and soft delete]).
- **Automated by:** Partly automated: the teardown step `delete-second-projects` of the long end-to-end failure suite; `nexus/operator/tests/test_sync.py` (`test_delete_never_forces`). Neither checks that the record is soft-deleted rather than removed.
- [ ] Pass
- [ ] Fail — notes:

## Deleting a GlobalResource another project still uses is refused, and the record is kept

Do this last in a session: it tears the test project down.

1. Apply the second project, and let a task finish in each project.
2. `kubectl delete -f config/e2e/fn-dev.yaml -f config/e2e/dev-dataset.yaml --wait=false`.
3. `kubectl get fn -A`. `kubectl get repository fn-trigger-repo -n fn -o yaml` and `kubectl get dataset dev-dataset -n experiments -o yaml`.
4. `GET /global/repositories/triggers/<id>` and `GET /global/datasets/<id>`. `fncli project-show --project qa-two`. Merge a watched pull request and look at `qa-two`.
5. `kubectl delete -f config/e2e/qa-two.yaml`. Wait one retry delay (60 seconds by default), then `kubectl get fn -A`.
6. Set the dev project up again (see [the index](README.md)).

- **Expected:** in step 3 the Project `fn-dev` is gone, and the Repository, Dataset and NodeSecret resources that `qa-two` still uses stay `Terminating` with `Synced` `false` and a `Message` holding nexus-api's 409 and its reason (the projects or records that still use it). In step 4 the records are still there and `qa-two` still has its resources and gets its trigger and task. The operator never deletes with `force`. After step 5 the refused deletes go through within a few retry delays (a NodeSecret's waits until the Repositories that use it are gone) and every resource is gone; `config/gitea.yaml` stays. Record the messages.
- **Rule:** removal is safe on a shared node: a GlobalResource another project uses is refused with a 409, the operator reports it in status, keeps the record and retries, and the resource stays `Terminating` until the delete goes through ([Declarative node config through an operator]).
- **Automated by:** Partly automated: the end-to-end teardown deletes the second projects first for this reason, and `nexus/operator/tests/test_sync.py` (`test_delete_never_forces`) checks no forced delete. Nothing checks the 409 in status or that the record is kept.
- [ ] Pass
- [ ] Fail — notes:

## A change to a managed field, or removal of a managed record, is refused with a 409

Use an administrator token. Every call below is expected to fail, so nothing needs undoing; if one succeeds, put it back through the Project or the matching custom resource.

1. Each with `--expect 409`: `fncli project-set --enabled false`, `fncli project-set --enabled true --backfill`, `fncli resource-set trigger --enabled false`, `fncli resource-set trigger --base-branch qa-other`, `fncli resource-set results --target-dir qa-other`.
2. `PATCH /global/datasets/<id>` with `{"host": "elsewhere"}`. `PATCH /global/providers/<id>` with `{"name": "renamed"}`. `PATCH /global/repositories/triggers/<id>` with `{"secret_label": "<another label>"}`. `PATCH /global/secrets/<label>` with `{"values": {"QA_KEY": "<throwaway>"}}`.
3. `PUT /projects/<pid>/datasets/<dataset id>` with `{}`. `DELETE /projects/<pid>/repositories/triggers/<id>`. `DELETE /projects/<pid>`. `DELETE /global/providers/<id>`.
4. In the UI: look at the project's Enabled toggle (list and detail) and its delete button.
5. Read the state command and `GET` the records again. After a few minutes: `kubectl get events -n fn --field-selector reason=Synced` and the operator log.

- **Expected:** every call in steps 1 to 3 is a 409 whose error names the record as managed by `fn-operator`, lists the refused fields and says to change its custom resource instead (a removal has no fields). Nothing in the records changes, and the operator makes no call for any of it. In the UI the project's Enabled toggle is read-only and its delete button is not shown. Step 5 shows no new `Synced` Event and no change.
- **Rule:** nexus-api refuses (409) a change to a managed field, or the removal of a managed record, unless the caller is the operator; this replaces putting back drift, so nothing is silently undone ([Declarative node config through an operator]; a refused move is a 409 as in [State transition tables]).
- **Automated by:** Partly automated: `nexus/api/tests/test_managed.py` (every kind and the project's assignments, against the app with a faked Keycloak token). The end-to-end suites patch the Project for this reason (`patch_project`), but none sends a refused call. Nothing checks the UI or a live node.
- [ ] Pass
- [ ] Fail — notes:

## Runtime state stays editable, and the operator leaves it alone

1. `fncli project-set --revoked true`, then `--revoked false`. `fncli resource-set trigger --revoked true`, then `false`. `fncli resource-set dataset --enabled false`, then `true`.
2. `fncli global-set trigger --enabled false`. Leave it off for a few minutes. Read the state command and the operator log. Then `fncli global-set trigger --enabled true`.

- **Expected:** each call is accepted (200). After those minutes the trigger repository is still off and the operator has made no call about it: `revoked`, a GlobalResource's `enabled` and a dataset resource's `enabled` are not in the config, so nothing puts them back. `managed_by` of the records is unchanged.
- **Rule:** runtime state stays editable through the API: `revoked` everywhere, the `enabled` of a GitProvider, Secret, repository or Dataset, a dataset assignment's `enabled`, cursors, pull requests, tasks and results ([Declarative node config through an operator]; [Enabled, revoked and soft delete]).
- **Automated by:** Partly automated: `nexus/api/tests/test_managed.py` (`revoked` and `enabled` stay editable on a managed provider, dataset, repository and project). Nothing waits to see that the operator does not touch it.
- [ ] Pass
- [ ] Fail — notes:

## A disabled Secret is not rotated: the NodeSecret stays unsynced until it is enabled

1. `fncli secret-set --entity trigger --enabled false` (this also disables the trigger repository that uses it).
2. Rotate the trigger repository's token (see "Rotate a git token" in [the index](README.md)). Wait one resync interval. `kubectl get nodesecret fn-trigger-repo-creds -n fn -o yaml`.
3. `fncli secret-set --entity trigger --enabled true`, then `fncli global-set trigger --enabled true`. Wait one resync interval. `fncli verify-git-secret --entity trigger`.

- **Expected:** after step 2 the NodeSecret is `Synced` `false` and `Message` holds nexus-api's 409 reason; nexus-api still has the old values. After step 3 it syncs again within a resync interval and the verify passes.
- **Rule:** a disabled Secret cannot be rotated (409): the NodeSecret stays unsynced, with nexus-api's reason in its status, until the Secret is enabled ([Declarative node config through an operator]).
- **Automated by:** Manual only. The decision states it; check the status text.
- [ ] Pass
- [ ] Fail — notes:

## A record made in the UI with the same name is adopted

1. Before applying it, make a project `qa-scratch` in the UI (or `POST /projects`) with nothing assigned. Look at its `managed_by` (empty) and `PATCH /projects/<pid>` with `{"enabled": true}` (200: a hand-made record is editable).
2. Copy `config/e2e/qa-two.yaml`, rename the project `qa-scratch`, and apply it.
3. `GET /projects` and the project's resources. Compare `nexusId` with the id from step 1. Look at `managed_by`.
4. `PATCH /projects/<pid>` with `{"enabled": false}`.
5. Delete the scratch file.

- **Expected:** there is one project `qa-scratch`, with the id from step 1, now with the dataset and repositories of the file and `managed_by` `fn-operator`. No duplicate. The `PATCH` in step 4 is a 409: the operator took the record over by sending every declared field once. Step 5 soft-deletes it.
- **Rule:** the operator finds a record by its key (name or uri) and adopts it; the id in status is a cache ([Declarative node config through an operator]).
- **Automated by:** Partly automated: `nexus/operator/tests/test_sync.py` (`test_repository_adopted_and_patched`, `test_provider_made_by_hand_adopted_with_every_declared_field`, `test_project_made_by_hand_marked_by_sending_enabled`) against a fake API, and `nexus/api/tests/test_managed.py` (`test_a_record_made_by_hand_is_editable_until_the_operator_adopts_it`); nothing on a live node.
- [ ] Pass
- [ ] Fail — notes:

## A bad resource is refused by Kubernetes before the operator sees it

1. In a scratch copy of `config/e2e/qa-two.yaml`, set the trigger's `watchDir` to `/`. Apply it.
2. Leave out `results` from `repositories`. Apply it.
3. A Repository with `type: other`, a NodeSecret with both `fromSecret` and `values`, and a GitProvider without `uri`. Apply each.

- **Expected:** `kubectl apply` refuses each with a validation error naming the field. Nothing reaches nexus-api.
- **Rule:** the CRDs carry the schema of each kind ([Declarative node config through an operator]).
- **Automated by:** Manual only.
- [ ] Pass
- [ ] Fail — notes:

## The operator survives a restart and never runs twice

1. `kubectl get deployment nexus-operator -n fn -o jsonpath='{.spec.replicas} {.spec.strategy.type}'`.
2. Note the time. `kubectl delete pod -n fn -l app=nexus-operator`, and while the new pod starts apply a change (a scratch copy of `config/e2e/qa-two.yaml`).
3. `kubectl get pods -n fn -l app=nexus-operator -w` until it is running. `kubectl get fn -A`. The new pod's log.
4. `kubectl rollout restart deployment nexus-operator -n fn` and watch the pods.
5. Delete the scratch project.

- **Expected:** step 1 is `1 Recreate`. In step 2 the change waits, then is synced once the new pod is up; at start the new pod syncs every resource again and sends nothing for those that already match (no duplicate record, no project disabled and enabled, no Secret sent again). In step 4 the old pod is gone before the new one starts: two never run at once. Record how long the start takes.
- **Rule:** one replica with `Recreate`; a resume syncs every resource ([Declarative node config through an operator]). The chart runs Kopf standalone with peering off, and `Recreate` is what keeps two from running. Record it if you see two pods at once. No timer syncs the kinds other than NodeSecret, so a record lost from nexus-api's database comes back only when the operator starts.
- **Automated by:** Partly automated: `k8s/federated-node/tests/nexus_operator_test.yaml` ("runs one replica with Recreate, watching the release namespace and watchNamespaces"); nothing restarts it on a cluster.
- [ ] Pass
- [ ] Fail — notes:

## A changed source Secret is sent again; a NodeSecret never shows a value

1. `kubectl get nodesecret fn-trigger-repo-creds -n fn -o yaml`. `kubectl get nodesecret dev-dataset-dataset-creds -n experiments -o yaml`.
2. Rotate the trigger repository's token (see "Rotate a git token" in [the index](README.md)). Note the time from the rotation to `sourceVersions` changing.
3. Merge a watched pull request.
4. Search the operator log and the Events for the Secret's keys (`CLIENT_SECRET`, `REFRESH_TOKEN`, `PASSWORD`). Do not copy what you find into notes; record only whether a value appears.

- **Expected:** step 1 shows `fromSecret` or `values` with `secretKeyRef` names only, and a status with `sourceVersions` (Secret name to `resourceVersion`), never a value or a hash of one. Step 2 is done within one resync interval; nexus-api has the new values and `fncli verify-git-secret --entity trigger` passes. Step 3 gets its task. Step 4 finds no value: the log and Events name resources, not values.
- **Rule:** a NodeSecret is a reference only; the operator reads the source Secret, sends its values because nexus-api stores them, and sends them again when the source changes, keeping only the `resourceVersion` in status ([Declarative node config through an operator]); never a Secret value in values, examples or logs ([Generic Secret model and SecretProvider; per-repository tokens]).
- **Automated by:** Partly automated: `nexus/operator/tests/test_sync.py` (`test_secret_sent_only_when_a_source_changed`, `test_secret_sent_when_the_spec_changed_with_the_same_source`, `test_secret_sent_when_the_record_is_missing`); the long end-to-end failure suite group "a lost token fails clearly, then recovers" rotates through the operator. Neither searches the logs.
- [ ] Pass
- [ ] Fail — notes:

## The operator logs in as its own user, and survives a password rotation

1. In the Keycloak admin console, find the user `fn-operator` and its roles.
2. `kubectl create job qa-rotate -n <keycloak namespace> --from=cronjob/keycloak-credential-rotation` (check the CronJob's namespace with `kubectl get cronjob -A`). Wait for it to finish.
3. Apply a change (a scratch copy of `config/e2e/qa-two.yaml`), then delete it. `kubectl get pods -n fn -l app=nexus-operator` (restart count).

- **Expected:** `fn-operator` has the Administrator role, not System. After the rotation the change still syncs, with no pod restart: the next 401 logs in again with the new password, read from the mounted file.
- **Rule:** the operator has its own identity, `fn-operator`, an Administrator, with a generated password rotated like Dagster's ([Declarative node config through an operator]).
- **Automated by:** Partly automated: `k8s/federated-node/tests/nexus_operator_test.yaml` ("makes the fn-operator login", "mounts fn-operator's password into realm-init beside kc-secrets"); nothing rotates it on a cluster.
- [ ] Pass
- [ ] Fail — notes:

## Uninstalling the release does not delete the node's records

Dev cluster only, and last: it removes the release. Check `mise run deploy-owner` first.

1. Note the records in nexus-api's database (`GET /projects` and the global lists, before you start).
2. `helm uninstall <release> -n fn`. Watch `kubectl get jobs -n fn` and `kubectl get fn -A`.
3. `kubectl get crd | grep fn.aridhia.com`.
4. `mise run deploy`, then `kubectl get fn -A` and the lists from step 1.

- **Expected:** the pre-delete hook stops the operator and strips the finalizers, so the uninstall does not hang, and the custom resources stay. The nexus-api log shows no `DELETE` from the operator. The CRDs stay. After step 4, if the database was kept, the operator adopts the records again with the same ids; if it was not, it creates them. Record which.
- **Rule:** uninstall is not a delete: a pre-delete hook stops the operator and strips the finalizers; the CRDs are kept ([Declarative node config through an operator]).
- **Automated by:** Partly automated: `k8s/federated-node/tests/nexus_operator_test.yaml` ("strips the finalizers in a pre-delete hook", "creates the hook's RBAC before its Job") renders the hook; nothing runs it.
- [ ] Pass
- [ ] Fail — notes:

## On a Flux node, changes are attributed, and a kubectl edit lasts only until Flux applies the values

Only on a node delivered by Flux.

1. Merge a change to the node config in the site repository and wait for Flux to reconcile the HelmRelease.
2. `kubectl get events -n <release namespace> --field-selector reason=Synced` and the operator log.
3. `kubectl edit` one Project and change a field. Wait for Flux's interval. Note whether the site's HelmRelease sets `driftDetection`.

- **Expected:** the Event and the log line carry the Flux annotations of the resource (which commit applied it). Step 3 is a check: with drift detection on, Flux puts the custom resource back to the values and the operator syncs that to nexus-api; without it, the edit holds (and the operator syncs it to nexus-api) until the next upgrade. Either way nothing in nexus-api changes except through the custom resource. Record which.
- **Rule:** changes are attributed in git and in Kubernetes (Events and logs with the Flux annotations), not yet in nexus-api ([Declarative node config through an operator]); Flux delivers the release and its values ([GitOps delivery with Helm and Flux]).
- **Automated by:** Manual only.
- [ ] Pass
- [ ] Fail — notes:

<!-- link definitions -->
[Declarative node config through an operator]: ../decisions/0032-declarative-node-config-through-an-operator.md
[GitOps delivery with Helm and Flux]: ../decisions/0031-gitops-delivery-with-helm-and-flux.md
[Global resources and project resources]: ../decisions/0006-global-resources-and-project-resources.md
[Enabled, revoked and soft delete]: ../decisions/0008-enabled-revoked-and-soft-delete.md
[Generic Secret model and SecretProvider; per-repository tokens]: ../decisions/0007-secrets-and-secret-providers.md
[State transition tables]: ../decisions/0005-state-transition-tables.md
