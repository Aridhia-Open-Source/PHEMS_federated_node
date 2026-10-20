# GlobalResources and project links

A GlobalResource (a dataset, trigger repository, results repository or GitProvider; a Secret is only used by them) is created once by the administrator. A project reaches it only through its own link (a ProjectResource). These cases check the create, link, unlink and delete rules. The rules for switching things on and off are in the two enabled and revoked sections.

Needs: an administrator token. On the dev cluster `fncli setup-project` creates the whole set; the cases below use the HTTP routes so they also work on a node that fncli cannot reach. Use a scratch name (for example `qa-scratch`) for anything you create, and delete it at the end. Never put a real token in a request you keep in the notes.

## Create a GitProvider, and reject a bad one

1. `POST /global/providers` with `name`, `type` (`gitea` or `github`), `uri` and `api_uri`.
2. Repeat it with the same name, then with the same `uri`.
3. `POST` one whose `api_uri` is on a different host from its `uri`.
4. `GET /global/providers/<id>/healthcheck`.

- **Expected:** 201 the first time. Step 2 is 409 each time. Step 3 is refused (400, check). The healthcheck asks the provider's API without a token and reports the result in the body.
- **Rule:** a GitProvider has a unique name and `uri`, and its `api_uri` must be on the provider's own host ([Global resources, linked to projects]).
- **Automated by:** Automated: `webserver/tests/test_git_providers.py`; it misses real reachability of the provider.
- [ ] Pass
- [ ] Fail — notes:

## Create a Secret, and never get its value back

1. `POST /global/secrets` with a `label`, `provider` `K8S` and `values` (use throwaway values).
2. `GET /global/secrets/<label>` and the list.
3. Repeat the `POST` with the same label.
4. `kubectl get secret -A | grep <label>` (names only; do not print the data).

- **Expected:** 201, then the Secret is returned as a reference (label, generated key `fn-secret-<label>`, namespace, enabled) with no values field. The same label again is 409. The value is in the store under the generated key.
- **Rule:** a Secret is a reference; the value lives only in the store ([Generic Secret model and SecretProvider; per-repository tokens]).
- **Automated by:** Partly automated: `webserver/tests/test_global_resources.py` (values hidden, duplicate 409) with an in-memory Kubernetes client; it misses the real store.
- [ ] Pass
- [ ] Fail — notes:

## Create a trigger repository and a results repository

1. `POST /global/repositories/triggers` with `provider_id`, `repo_path` (`owner/name`) and `secret_label`. Do the same on `/global/repositories/results`.
2. Repeat with the same provider and path written differently (for example with an `https://` prefix).
3. Add `watch_dir` (trigger) or `target_dir` (results) to the body. Add `project_id`. Name a `secret_label` that does not exist, then one that is disabled.

- **Expected:** 201 with the `uri` derived from the provider and path. Step 2 is 409 (the path is normalised first). Step 3 is 400 each time, and nothing is created.
- **Rule:** a repository is global, unique on `(provider, repo_path)`; the per-project settings belong to the link ([Global resources, linked to projects]).
- **Automated by:** Automated: `webserver/tests/test_global_resources.py`, `webserver/tests/test_trigger_repositories_and_links.py`. It misses the live node (mocked Keycloak and Kubernetes).
- [ ] Pass
- [ ] Fail — notes:

## Create a dataset, and the duplicate-name behaviour

1. `POST /global/datasets` with `name`, `host`, `port` and `secret_label`.
2. Repeat with the same name in a different case.
3. Add `username` or `password` to the body.

- **Expected:** 201 and the name is stored in lower case. Step 2 is 409 (case-insensitive). Step 3 is 400: credentials go through a Secret.
- **Rule:** a dataset is global and refers to its credentials by Secret ([Global resources, linked to projects]).
- **Automated by:** Automated: `webserver/tests/test_global_resources.py` (`test_dataset_duplicate_name_is_409_case_insensitive`, `test_dataset_create_invalid`). It misses the live node (mocked Keycloak and Kubernetes).
- [ ] Pass
- [ ] Fail — notes:

## Link a trigger repository to a project

1. `PUT /projects/<pid>/repositories/triggers/<id>` with `{"watch_dir": "<dir>"}`; optionally `base_branch`.
2. `PUT` again with a changed `watch_dir`.
3. `PUT` with `{}`, then with an unknown field, then for an unknown repository id and an unknown project id.
4. `GET /projects/<pid>/repositories/triggers/<id>`.

- **Expected:** 201 the first time, 200 the second with the new settings (a `PUT` replaces the project's settings; fields left out take their defaults). Step 3 is 400, 400, 404, 404. The link shows `enabled`, `revoked`, a computed `active`, and its cursor.
- **Rule:** `PUT` links (201 then 200), the path uses the GlobalResource's id ([Global resources, linked to projects]).
- **Automated by:** Automated: `webserver/tests/test_trigger_repositories_and_links.py`, `webserver/tests/test_smoke.py`; the end-to-end setup creates the link on a live cluster. It misses real logins (mocked Keycloak).
- [ ] Pass
- [ ] Fail — notes:

## Linking a results repository needs the project disabled, and a project has one

1. On an enabled project, `PUT /projects/<pid>/repositories/results/<id>` with `{"target_dir": "<dir>"}`.
2. `fncli project-set --enabled false`, then repeat the `PUT`, then `fncli project-set --enabled true`.
3. Try to link a second, different ResultsRepository without unlinking the first.
4. Change `target_dir` with `PATCH` on the link while the project is enabled.

- **Expected:** step 1 is 409. Step 2 gives 201, and enabling afterwards works. Step 3 is refused (check the status; a project has one results link, so unlink first). Step 4 is 200: `target_dir` can be edited at any time.
- **Rule:** one results repository per project, linked only while the project is disabled ([Global resources, linked to projects]); edits are free ([A task is pinned to its configuration]).
- **Automated by:** Automated: `webserver/tests/test_results_and_delivery.py`; the end-to-end setup links it on a live cluster. The unit tests miss the live node.
- [ ] Pass
- [ ] Fail — notes:

## The first dataset linked becomes the project's default

1. Link dataset A to a project that has none, then dataset B.
2. Merge a watched pull request whose spec names no dataset.
3. Unlink dataset A and look at the project's default.

- **Expected:** after step 1 the project's default dataset is A. In step 2 the task runs on A. What the default becomes after step 3 is not stated in the sources: check and record.
- **Rule:** the first dataset linked becomes the default; a spec that names none uses it ([Global resources, linked to projects]).
- **Automated by:** Partly automated: `webserver/tests/test_projects_api.py` (`test_dataset_link_disable_unlink_and_default_dataset`) and `webserver/tests/test_pull_requests_and_tasks.py` (`test_dataset_default_and_case_insensitive_override`); they miss a live run on the default.
- [ ] Pass
- [ ] Fail — notes:

## A results link cannot write into a directory that a trigger link watches

1. Link a trigger repository with `watch_dir` `triggers`.
2. Link a results repository on the same repository (same provider and path) with `target_dir` `triggers/out`.
3. Reverse it: results `target_dir` `out`, then a trigger link on the same repository that watches the whole repository.

- **Expected:** both attempts are refused. The same check applies across projects.
- **Rule:** cross-project loops are forbidden ([Global resources, linked to projects]). The check keys on provider and path, so the same server under two host names is not seen (an open question in the decision).
- **Automated by:** Automated: `webserver/tests/test_results_and_delivery.py` (the tests for a results directory inside a watched directory, and for a whole-repository trigger link and a results link on the same repository); it does not cover two host names for one server.
- [ ] Pass
- [ ] Fail — notes:

## One project cannot see or change another project's link

1. As the administrator, `GET /projects/<other pid>/repositories/triggers/<id>` for a link that only the first project has.
2. `PATCH` the same path.

- **Expected:** 404 for both.
- **Rule:** the link is the permission boundary ([Global resources, linked to projects]).
- **Automated by:** Automated: `webserver/tests/test_trigger_repositories_and_links.py` (`test_link_is_invisible_to_other_projects`). It misses real roles and logins (mocked Keycloak).
- [ ] Pass
- [ ] Fail — notes:

## Unlinking revokes the link and can be undone by linking again

1. `DELETE /projects/<pid>/datasets/<id>`.
2. `GET` the link, then `PUT` it again.

- **Expected:** 204; the link is gone from the API (404); linking again works.
- **Rule:** deleting a link revokes and soft-deletes it; a deleted name or pair is free again ([Enabled, revoked and soft delete]).
- **Automated by:** Automated: `webserver/tests/test_trigger_repositories_and_links.py` (`test_unlinking_revokes_the_link_and_it_can_be_linked_again`). It misses the live node. Deleting a trigger link that has pull requests is a [known issue](known-issues.md).
- [ ] Pass
- [ ] Fail — notes:

## Deleting a GlobalResource that is linked needs `force`

1. Link a scratch dataset to two projects.
2. `DELETE /global/datasets/<id>`.
3. `DELETE /global/datasets/<id>?force=true`, then `GET` it, then create a dataset with the same name.
4. Try to `DELETE` a GitProvider that still has a repository.

- **Expected:** step 2 is 409 and lists the projects. Step 3 is 204; the dataset and both links are gone (404) and the name is free again. Step 4 is 409.
- **Rule:** deletes are soft; a GlobalResource with live links is a 409 unless forced, and a GitProvider with repositories cannot be deleted ([Enabled, revoked and soft delete]).
- **Automated by:** Automated: `webserver/tests/test_global_resources.py`, `webserver/tests/test_git_providers.py`, `webserver/tests/test_trigger_repositories_and_links.py`. They miss tasks in flight on a live node: what happens to a task in flight when its link is force-deleted is in [enabled and revoked: launch and delivery](enabled-and-revoked-launch-and-delivery.md).
- [ ] Pass
- [ ] Fail — notes:

## Editing a shared GlobalResource is seen by every project that links it

1. Link one dataset to two projects.
2. `PATCH /global/datasets/<id>` to change `host` (use a harmless host, restore it afterwards).
3. `GET` the dataset link of each project.

- **Expected:** both projects see the new host. Tasks already created from either project are affected by pinning, which is tested in [task pinning](task-pinning.md).
- **Rule:** editing a GlobalResource affects every project linked to it ([Global resources, linked to projects]).
- **Automated by:** Partly automated: `webserver/tests/test_task_config.py` covers the effect on one project's tasks; two projects on a live node are not covered. See also [two projects on the same GlobalResources](two-projects-on-the-same-globalresources.md).
- [ ] Pass
- [ ] Fail — notes:

## The list filters the sensors rely on return the right rows

1. `GET /global/repositories/triggers?pollable=true`.
2. `GET /projects/<pid>/repositories/triggers?active=true` and `?active_link=true` on the global list.
3. `GET /tasks?status=PENDING&project_enabled=true`.

- **Expected:** `pollable` lists only repositories that are enabled, on an enabled and not revoked GitProvider, with an enabled Secret; project links are ignored. The other filters list only what is active or enabled.
- **Rule:** filters are webserver query options; Dagster does not filter lists ([The Dagster pipeline: ingest as an op, twelve sensors, one interval, retries]).
- **Automated by:** Automated: `webserver/tests/test_pagination_and_filters.py`, `webserver/tests/test_trigger_repositories_and_links.py` (`test_pollable_filter_follows_the_repository_provider_and_secret_only`), `webserver/tests/test_all_tasks_list.py`. They miss the sensors that use the filters on a live node.
- [ ] Pass
- [ ] Fail — notes:

<!-- link definitions -->
[A task is pinned to its configuration]: ../decisions/0009-task-pinned-to-its-configuration.md
[Enabled, revoked and soft delete]: ../decisions/0008-enabled-revoked-and-soft-delete.md
[Generic Secret model and SecretProvider; per-repository tokens]: ../decisions/0007-secrets-and-secret-providers.md
[Global resources, linked to projects]: ../decisions/0006-global-resources-and-project-links.md
[The Dagster pipeline: ingest as an op, twelve sensors, one interval, retries]: ../decisions/0014-dagster-pipeline-ops-sensors-and-retries.md
