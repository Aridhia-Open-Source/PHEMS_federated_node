# Moonshot: architecture and requirements

> **Status at end of day 2026-10-17. Read this first: the sections below predate some of it.**
> - **Proven live:** the happy path passed end to end on kind-fn (Gitea PR → `YIELDED` → task `SUCCESS` → results PR `OPENED` → `MERGED`), by hand and as the automated test.
> - **GitProvider:** global `GitProvider` (`/global/providers`: `name`, `type` github|gitea, `uri` unique, `api_uri`, `enabled`).
>   - Trigger and results repos are `provider_id` + `repo_path` + `secret_id` (token per repo, for least privilege) + `enabled`, unique `(provider_id, repo_path)`; the `uri` is derived.
>   - A disabled provider makes its repos inactive.
>   - Migration 002. No `upstream_id` yet.
> - **Routes:**
>   - tasks under `/projects/:pid/tasks/...`, plus `GET .../tasks/:id/trigger`
>   - `service-info` deleted
>   - `/global/users`, `/global/registries`, `/global/whitelisted_images`
>   - results under `/projects/:pid/results`
> - **Integrity and project state:**
>   - PRs unique by `(repo, merge_commit_sha)` as well as number (migration 003)
>   - new projects start **disabled** (baseline migration); fncli `setup-project` enables them at the end. There is no project lock (dropped 2026-10-19): a project is enabled or disabled, a results repository is linked while it is disabled, and enabling may ask for a backfill
> - **Sensors:** one interval for all sensors, `fnDagster.sensors.minIntervalSeconds` (30s default, 2s in dev; PR #554, merged).
> - **Tooling:**
>   - fncli moved into `dagster/fncli` and shares `app.*`; install with `pipx install --force --editable './dagster[cli]'`
>   - Dagster and fncli unit tests run in Docker (`dagster/run_tests.sh`)
>   - e2e: `pytest dagster --e2e [success|failure] -v` from the repo root. The suites are granular (each fncli command and state change is its own test). The failure suite has never been run.
> - **Not built yet:** auth (planned in `project/auth-mvp-plan.md`).
> - **gitea-mirror is parked for the beta.** Post-beta it becomes a stateless mirror service with number-matched PR replay, which the node sees as a `gitea` GitProvider.
> - **To do:** a full refresh of this document, and a narrow bug review (migrations 002-004, drain rules, sensors). See `.claude/handover.md`.


- Written: 2026-10-17. Owner: codepint.
- Purpose: the owner's source of truth. Use it to validate the work, confirm assumptions and brief the manager. A review agent will check both branches against it.
- Built from the ADRs first, not from the code. The code was read only to see whether a decision was implemented.
- Branches:
  - **shared-resources** (ADR 0019): `origin/moonshot/shared-resources`.
  - **gitea-mirror** (ADR 0020): `origin/moonshot/gitea-mirror`.
- Tags in validation cases: **[business]** is about what the owner wants. **[technical]** is about how it is built.
- Notes: `Uncertain (Qn)` means sources conflict or I inferred it. `Assumption (Qn)` means no source at all. Every note is collected in section 5.

Precedence when sources disagree:

1. Decisions the owner made on 2026-10-17 ("decision 2026-10-17").
2. ADR 0019 (and ADR 0020 with its "Decisions changed by the 2026-10-17 review" section).
3. Handovers, commit messages, READMEs.
4. The code (only proves what was built).

---

## 1. Summary (for a manager)

**What the moonshot is.** Today every secret, dataset and git repository belongs to one project. If two projects need the same repository, someone registers it twice, the node polls GitHub twice, and it stores every pull request twice. The moonshot makes these things shared:

- A data controller creates a secret, dataset or repository **once**, at node level.
- A project then **links** to it. The link holds that project's own settings.
- A controller can **revoke** a link. Only that connection stops. The project keeps running.
- GitHub is polled **once per repository**. Each merged pull request (PR) is stored once and then offered to every project that watches it.

**Why.** One credential to rotate. One poll per repository. Less duplicated data. A clear place for the controller to grant or withdraw access.

**What is built (shared-resources).**

- Shared secrets, datasets, trigger repositories and results repositories, with per-project links.
- `enabled` (a person's switch) and `revoked` (the controller's withdrawal) on every link.
- Shared PRs: stored once, one trigger per matching project.
- A new API layout: `/global/...` for shared things, `/projects/:pid/...` for a project's links, tasks and results.
- Dagster sensors that poll once per repository, evaluate PRs, launch tasks and deliver results as a PR.
- Healthchecks for each resource, project and the whole node.
- Webserver tests, Dagster tests in Docker, and an end-to-end script.

**What is built (gitea-mirror).** A separate service. It copies merged GitHub PRs into the node's own Gitea, so the node reads locally and never needs GitHub tokens in the evaluation path. It can also send signed webhooks when a PR is mirrored. It is built and unit-tested, but **not verified on a real cluster or against the real GitHub API**. The node-side receiver for its webhooks is **not built**.

**What is parked.** Narrowing Dagster's secret permissions. Restarting Dagster after credential rotation (dropped). Legacy models. The sensor redesign. Flask to FastAPI. Authorization rework. Guards on editing shared resources (replaced by pinning a task to its configuration, ADR 0019). Full list in section 4.

**Known open risks (section 5 has the list).** Four trigger-loss and ingest bugs found in review are still unfixed in code. The owner needs to say which of them block the MVP.

**State of verification.** Webserver tests were green (606 passed) at handover. Dagster plus fncli tests are green: `cd dagster && ./run_tests.sh ci` gave 470 passed (346 Dagster + 124 fncli), per the owner. The end-to-end script has never been run. The mirror was verified in a sandbox (365 tests with a real Gitea) but not on a cluster.

---

## 2. Architecture

### 2.1 Components

| Component | Role |
|---|---|
| Webserver (Flask) | The only API. Owns the data model and all rules. Sits behind Keycloak. |
| Keycloak | Node-level users and tokens. Project access uses data access requests (legacy). |
| Postgres | Webserver data. The mirror has its own database `gitea_mirror` on the same server. |
| Dagster sensors and jobs | Poll GitHub or Gitea, evaluate PRs, launch task runs, deliver results. They only call the webserver API. |
| Gitea | The node's own git server. Hosts mirrored repositories and, in dev, results repositories. |
| gitea-mirror | Separate service. GitHub merged PRs into Gitea, plus webhooks. Knows nothing about the node. |
| fncli | Dev and ops CLI. Lives in `dagster/fncli` (second package, `cli` extra) and imports `app.*`. No copies. Done and committed. |

### 2.2 Data model

```
GLOBAL (no project_id)                PER PROJECT (the "link")
secrets                       <----   project_secrets
trigger_repositories          <----   project_trigger_repositories  (watch_dir, base_branch, cursor)
results_repositories          <----   project_results_repositories  (target_dir)  one per project
datasets                      <----   project_datasets

pull_requests (one per repo+number) --> pull_request_triggers (one per link + PR) --> task
pull_request_files (paths, status)                     (state: UNKNOWN / YIELDED / REJECTED)
                                                       task --> result (one per task + results link)
```

- Every global resource has its own `enabled`.
- Every link has `enabled` and `revoked`.
- A link is **active** when: the global resource is enabled, AND the link is enabled, AND the link is not revoked.

| Flag | Who sets it | Meaning |
|---|---|---|
| global `enabled` | admin, on the global resource | Resource on or off for the whole node |
| link `enabled` | a person, for the project | Project switched it on or off |
| link `revoked` | controller (admin only, via PATCH) | Access withdrawn. Never changes `enabled`, so a re-grant restores the old state |
| `active` (computed) | nobody | All three conditions above |

Inactive links are still returned by the API with their flags. Delivery and results sync need them.

### 2.3 Flow from a merged PR

```
GitHub/Gitea --poll once per repo--> [ingest sensor]
   --POST <=100 PRs--> webserver: store PR + files once, fan out
   --> one trigger (UNKNOWN) per active matching link
[evaluate sensor] reads each project's UNKNOWN triggers, reads the spec file from git
   --POST .../task--> webserver: validate, YIELDED + task PENDING   (or REJECTED)
[launcher sensor] PENDING task of an enabled project --> Dagster run
[run-status sensors] copy run status to the task (only writer of task status)
[delivery sensor] task SUCCESS --> GET .../tasks/:id/trigger (finds the PR)
   --> push results branch + open results PR  --> result steps PUSHED, OPENED
[results sync sensor] results PR merged or closed --> result MERGED or CLOSED
```

Optional front of the flow (gitea-mirror, not yet connected to the node):

```
GitHub --poll--> gitea-mirror --push + open/merge PR--> Gitea
                     --signed webhook--> (node receiver: NOT built)
```

### 2.4 API layout

| Scope | Path | Notes |
|---|---|---|
| Global resources | `/global/datasets/:id`, `/global/secrets/:label`, `/global/repositories/triggers/:id`, `/global/repositories/results/:id` | `POST` on collection creates. `GET`, `PATCH`, `DELETE` manage. Admin only to create. |
| Global PR facts | `/global/repositories/triggers/:id/pull_requests` | `GET` list, `POST` batch ingest |
| Global other | `/global/users`, `/global/registries`, `/global/whitelisted_images`, `/global/healthcheck` | `PUT /global/users/reset-password` is deliberately unauthenticated |
| Project links | `/projects/:pid/datasets/:id`, `/projects/:pid/secrets/:label`, `/projects/:pid/repositories/triggers/:id`, `/projects/:pid/repositories/results/:id` | `PUT` links (201 then 200). `PATCH` settings. `DELETE` unlinks. Keyed by the global id. |
| Project PR state | `/projects/:pid/repositories/triggers/:id/pull_requests[/:number[/task]]` | Evaluation state per project |
| Tasks | `/projects/:pid/tasks`, `/tasks/:id`, `/tasks/validate`, `/retry`, `/cancel`, `/logs`, `/results`, `/results/approve`, `/results/block`, `/trigger` | All task routes live here. `GET /tasks/service-info` is deleted. |
| Results | `/projects/:pid/results[/:id]` | `POST` creates a delivery. `PATCH` records progress. |
| Project | `/projects`, `/projects/:pid`, `/projects/:pid/healthcheck` | `/projects/:pid/users` comes later |
| Healthchecks | `/global/.../healthcheck` and `/projects/:pid/.../healthcheck` | One per resource and per link |

Rules: `POST` only under `/global`. Project paths use the global id, never the link id. Filtering is a query option on the list route (for example `?active_link=true`, `?active=true`, `?state=`, `?status=`, `?step=`).

---

## 3. Requirements

### 3.1 Global resources (SR-GLOB)

### SR-GLOB-01 Resources are global and created only under /global

**Happy path:** An admin creates a secret, dataset, trigger repository or results repository with `POST /global/...`. It has no `project_id`.

**Validation cases:**
1. Admin `POST /global/repositories/triggers` with `{uri, provider, secret_label}` → 201, body has `enabled: true` and the nested secret, no `project_id`. **[business]**
2. `POST /global/repositories/triggers` with `project_id`, `watch_dir` or `base_branch` in the body → 400. **[business]**
3. `POST /global/datasets` with `project_id` or credential fields (`username`) → 400. **[technical]**
4. `POST` of a global resource with a non-admin token → 403. **[business]**
5. No `POST` route exists under `/projects/:pid/datasets`, `/secrets` or `/repositories/...` (only `PUT` to link) → `POST` returns 404 or 405. **[technical]**

**Source:** ADR 0019 §1, §9, §11 ("Projects never create resources"). Status codes also confirmed in code.

> **Uncertain (Q1):** ADR §9 says creating global resources "requires the admin role for now". Code has `@auth(scope='can_do_admin')` on POST and DELETE, but `PATCH /global/secrets/<label>` has no admin check (known gap in the tests handover, not fixed). Is that acceptable for the MVP?

### SR-GLOB-02 Secrets are addressed by label; values are never returned

**Happy path:** A secret has a unique `label`. Its stored key is `fn-secret-<label>`. The API returns references, never values.

**Validation cases:**
1. `POST /global/secrets {label, provider: "K8S", values}` → 201, `key == "fn-secret-<label>"`, no `values` in the response. **[business]**
2. `POST` the same label twice → second is 409. **[technical]**
3. `POST` without `values`, or with an unknown provider → 400. **[technical]**
4. `PATCH /global/secrets/<label>` with new `values` (rotation) on a secret linked to a project → 200 (rotation is free). **[business]**
5. `DELETE /global/secrets/<label>` while a repository or dataset uses it → 409. **[technical]**

**Source:** ADR 0019 §7.

### SR-GLOB-03 Each global resource has its own `enabled`; a disabled secret is refused

**Happy path:** A global resource can be switched off for the whole node. A repository or dataset cannot reference a disabled secret.

**Validation cases:**
1. `PATCH /global/repositories/triggers/:id {"enabled": false}` → 200, `enabled: false`. Its links report `active: false`. **[business]**
2. Create or patch a repository or dataset with `secret_label` of a disabled secret → 400. **[business]**
3. `PATCH` a repository keeping its current (disabled) secret → not refused. **[technical]**
4. `POST` batch ingest to a disabled trigger repository → 400, nothing stored. **[business]**

**Source:** ADR 0019 §2 ("Global `enabled`"), §12 item 14.

### SR-GLOB-04 Datasets are global and addressed by id

**Happy path:** Datasets have no `project_id`, unique lowercase names, and are addressed by id only.

**Validation cases:**
1. `POST /global/datasets {name, host, port, secret_label}` → 201, `name` stored lowercase, `url` ends in `/global/datasets/<id>`. **[business]**
2. `GET /global/datasets/<id>` → 200. `GET /global/datasets/999` → 404. **[technical]**
3. `PATCH /global/datasets/<id>` → 200. **[technical]**
4. A duplicate dataset name → 409 (not 500). **[technical]**

**Source:** ADR 0019 §6, §12 items 5 and 15.

> **Uncertain (Q2):** ADR §12 item 15 marks "Dataset PATCH returns 200" and "`/tasks` clamps `page`/`per_page` below 1 to 1" with "(?)". Both are built as written. Owner to confirm. The duplicate-name 409 comes only from the handover's flagged-then-fixed list (round 1 of app fixes, "unique violations are 409").

### SR-GLOB-05 Trigger and results repositories are global and unique by URI

**Happy path:** A repository is registered once by URI, with a secret, a provider and an API URI.

**Validation cases:**
1. `POST /global/repositories/triggers` twice with the same `uri` (the second written `https://github.com/...`) → second is 409. **[business]**
2. `POST` with an unknown `secret_label` → 400. **[technical]**
3. `POST` with a bad `provider` → 400. **[technical]**
4. `GET /global/repositories/triggers?active_link=true` → only repositories that have an active link of an enabled project. **[business]**

**Source:** ADR 0019 §1, §11.

---

### 3.2 Project links (SR-LINK)

### SR-LINK-01 A project links to a resource with PUT, keyed by the global id

**Happy path:** `PUT /projects/:pid/<kind>/<global id>` links. It returns 201 the first time and 200 after. `PATCH` changes the project's settings. `DELETE` unlinks.

**Validation cases:**
1. `PUT /projects/:pid/repositories/triggers/:T {"watch_dir": "triggers"}` → 201, nested `trigger_repository.id == T`, `active: true`. **[business]**
2. `PUT /projects/:pid/repositories/triggers/:T {}` or with an unknown field → 400. **[technical]**
3. `PUT` to an unknown repository or project → 404. **[technical]**
4. A second `PUT` on the same link replaces settings; fields left out take defaults → 200 (needs the project drained, see Out of scope). **[technical]**
5. `GET /projects/:other/repositories/triggers/:T` where only the first project has the link → 404. **[business]**

**Source:** ADR 0019 §11.

### SR-LINK-02 `enabled`, `revoked` and `active` behave as defined

**Happy path:** Revoking sets only `revoked`. Re-granting clears it and restores the previous `enabled`. Lists return inactive links with `enabled`, `revoked`, `active`.

**Validation cases:**
1. Admin `PATCH /projects/:pid/repositories/triggers/:T {"revoked": true}` → 200, `revoked: true`, `active: false`, `enabled` unchanged. **[business]**
2. Same `PATCH` with a non-admin token → 403. **[business]**
3. `PATCH {"revoked": false}` → 200, `active: true`, `enabled` as before. **[business]**
4. `GET /projects/:pid/repositories/triggers` → includes the revoked link with its flags. `?active=true` leaves it out. **[technical]**
5. `PUT` never sets `revoked`; a `PUT` leaves the stored `revoked` alone. **[technical]**

**Source:** ADR 0019 §2, §11, §12 item 11.

### SR-LINK-03 Revoke takes effect immediately and only on that resource

**Happy path:** Revoking is not blocked by in-flight work. The project keeps running. Only that connection stops.

**Validation cases:**
1. Revoke a project's dataset link while a task is in flight → 200 (not 409). **[business]**
2. After revoking a trigger link, ingest a matching PR → no trigger for that project; the PR is still stored. **[business]**
3. After revoking a trigger link, `POST .../pull_requests/:n/task` on an existing UNKNOWN trigger → 409. **[business]**
4. After revoking one link, the project still shows `enabled: true` and its other links stay active. **[business]**

**Source:** ADR 0019 §2, §12 items 1 and 10.

### SR-LINK-04 Link uniqueness

**Happy path:** A project watches one directory per trigger repository, and has at most one results repository.

**Validation cases:**
1. `PUT` a second, different results repository for a project that already has one → 409. **[business]**
2. A second `PUT` to the same trigger repository replaces the settings (it does not add a second link) → 200, link count stays 1. **[technical]**

**Source:** ADR 0019 §8, §11.

### SR-LINK-05 Loops across projects are forbidden

**Happy path:** A results repository directory may not overlap a trigger repository directory, even across projects.

**Validation cases:**
1. Project A links results repository R at `target_dir: "triggers/out"`, where R's URI equals a trigger repository linked with `watch_dir: "triggers"` → 400, message mentions overlap. **[business]**
2. Same setup, but the trigger repository is linked by a different project → 400. **[business]**

**Source:** ADR 0019 §9, §12 item 3.

### SR-LINK-06 Dataset links and the default dataset

**Happy path:** A task can only use a dataset the project has an active link to. The first dataset linked becomes the project's default.

**Validation cases:**
1. `PUT /projects/:pid/datasets/:D {}` on a project with no dataset → 201, and `GET /projects/:pid` shows `default_dataset_id == D`. **[business]**
2. `POST /projects/:pid/tasks` naming a dataset the project has no link to → rejected (400) and recorded as REJECTED. **[business]**
3. Task from a PR with no dataset named → runs on the project's default dataset (`spec.dataset_id == D`). **[business]**
4. Delete a global dataset that a task ran on → refused (the task spec row blocks it). **[technical]**

**Source:** ADR 0019 §6.

### SR-LINK-07 Deleting a project removes links only

**Happy path:** `DELETE /projects/:pid` deletes the project's tasks, triggers and links. It leaves secrets, datasets, repositories and stored secret values alone.

**Validation cases:**
1. Delete a drained project → 204. `GET /global/secrets/:label` and the global datasets and repositories still return 200. **[business]**
2. After the delete, no call to the secret store's delete was made. **[technical]**

**Source:** ADR 0019 §7.

---

### 3.3 Pull requests and triggers (SR-PR)

### SR-PR-01 Batch ingest stores PRs once and is idempotent

**Happy path:** `POST /global/repositories/triggers/:id/pull_requests` takes up to 100 PRs, upserts them and fans out. Sending the same PRs again changes nothing.

**Validation cases:**
1. Post PRs 1 and 2 → 201, `{"created": [1, 2], "existing": []}`. **[business]**
2. Post PRs 1, 2 and 3 afterwards → 201, `created == [3]`, `existing == [1, 2]`. **[business]**
3. Post 101 PRs → 400. **[technical]**
4. Post a body where `pull_requests` is not a list, or a PR lacks `title` or has an unknown field → 400. **[technical]**
5. Post to an unknown repository → 404. **[technical]**

**Source:** ADR 0019 §3, §4, §11. Cap of 100 from the ingest sensors decision 2026-10-17.

### SR-PR-02 Provider facts are stored once per repository

**Happy path:** `pull_requests` holds number, title, author, merge time, merge commit, base branch and `files_truncated`. `pull_request_files` holds the changed paths. A PR with more than 3000 changed files sets `files_truncated` and matches every watcher.

**Validation cases:**
1. Ingest the same PR twice → one `pull_requests` row; `GET /global/repositories/triggers/:id/pull_requests` shows `total == 1`. **[business]**
2. Ingest a PR with `files_truncated: true` and an empty file list → every active link gets a trigger. **[technical]**
3. Ingest a PR into a repository with no links → 201, stored, no triggers. **[business]**

**Source:** ADR 0019 §3.

> **Uncertain (Q3):** ADR §3 says `pull_request_files(pull_request_id, path)`. The code also stores a file `status`. Needed because the match rule uses it (see SR-PR-03).

### SR-PR-03 Fan-out creates one trigger per active, matching link

**Happy path:** When a PR is stored, each active link on that repository whose `base_branch` and watched directory match gets a trigger in state UNKNOWN. A non-matching link gets no trigger. The decision uses stored data only, with no provider call.

**Validation cases:**
1. PR merged into `main`, links watch `main` and `dev` → only the `main` link gets a trigger. **[business]**
2. PR changes a file only outside `watch_dir` → no trigger for that link. **[business]**
3. Two projects link the same repository, both match → each gets its own trigger and its own task later (different task ids). **[business]**
4. A revoked or disabled link on the repository → no trigger created. **[business]**

**Source:** ADR 0019 §3, §12 item 10.

> **Uncertain (Q4):** The code's match rule is stricter than the ADR. It needs a file ending `.json` with status `added` under `watch_dir`. The ADR only says "its `watch_dir` against `pull_request_files.path`". The tests handover states the stricter rule. Confirm it is intended.

> **Uncertain (Q5):** Fan-out creates triggers for active links of **disabled projects**, while `?active_link=true` leaves disabled projects out (so ingest does not poll for them). Is a disabled project meant to collect triggers? (Handover lists this as "flagged, not changed".)

### SR-PR-04 Trigger states: UNKNOWN, YIELDED, REJECTED. No IGNORED.

**Happy path:** `REJECTED` is final. A PR that does not match a link creates no trigger. A PR whose spec is invalid, or with no new spec file when Dagster reads it, ends REJECTED with a `state_cause`.

**Validation cases:**
1. `GET /projects/:pid/repositories/triggers/:T/pull_requests?state=IGNORED` → 400 (unknown state). **[business]**
2. `PATCH .../pull_requests/:n {"state": "REJECTED"}` without `state_cause` → 400. **[technical]**
3. A PR with a spec that fails validation: `POST .../task {"spec_raw": "{}"}` → 400, and the trigger is REJECTED with a cause. **[business]**
4. The Dagster parser given a PR with no watched `.json` file → outcome REJECTED. It also rejects a PR with several new spec files. **[technical]**
5. `openapi.json` does not list `IGNORED`. **[technical]**

**Source:** decision 2026-10-17 ("`IGNORED` removed: a PR with no watched file is REJECTED"), ADR 0019 §3 and §12 item 10.

> **Uncertain (Q6):** Two layers apply the idea. The webserver fan-out skips a non-matching link (no trigger). The Dagster parser marks a PR REJECTED when it finds no watched file at evaluation. The decision text says "REJECTED" only. I read both as consistent, because fan-out normally stops such PRs first. Please confirm.

### SR-PR-05 Cursors, backfill and no replay of history

**Happy path:** A new link starts at the latest stored PR (or its creation time if none), so history is not replayed. When a link is created, re-enabled or un-revoked, the backend backfills triggers for PRs it missed, from stored data only. The global poll cursor is the latest `merged_at` stored for the repository.

**Validation cases:**
1. Link created after PRs 1 and 2 were stored → no triggers for 1 and 2. **[business]**
2. Revoke a link, ingest PR 3, un-revoke → trigger for PR 3 exists after un-revoke; `pr_count` is 1. **[business]**
3. Link response contains `pr_cursor`; the global repository response contains the global cursor. **[technical]**
4. Changing `watch_dir` or `base_branch` does not replay older PRs. **[business]**

**Source:** ADR 0019 §3.

### SR-PR-06 Project PR lists filter in the webserver

**Happy path:** The project PR list takes `state`, `page`, `per_page`. There is no `?task_id=` filter. A task's PR is found through `/tasks/:id/trigger`.

**Validation cases:**
1. `GET .../pull_requests?state=UNKNOWN` → only UNKNOWN triggers. **[technical]**
2. `GET .../pull_requests?state=NOPE` → 400. **[technical]**
3. `GET .../pull_requests?task_id=1` → the parameter does nothing (no such filter in the API). **[technical]**

**Source:** decision 2026-10-17.

### SR-PR-07 Create a task from a PR

**Happy path:** `POST /projects/:pid/repositories/triggers/:T/pull_requests/:n/task {"spec_raw": ...}` validates, marks the trigger YIELDED and creates the task in one transaction. It is idempotent.

**Validation cases:**
1. First call with a valid spec → 201, task `PENDING`, trigger `YIELDED`, `task_id` set. **[business]**
2. Same call again → 200, same task id. **[technical]**
3. Call on a REJECTED trigger, or through an inactive link → 409. **[business]**
4. Call with `spec_raw` missing → 400. **[technical]**

**Source:** ADR 0019 §12 item 10.

---

### 3.4 Tasks (SR-TASK)

### SR-TASK-01 All task routes live under /projects/:pid/tasks

**Happy path:** Every task route is nested under the owning project. A task of another project is a 404.

**Validation cases:**
1. `GET /projects/:pid/tasks`, `POST` (create), `POST /validate`, `GET /:id`, `PATCH /:id`, `POST /:id/retry`, `/cancel`, `GET /:id/logs`, `GET /:id/results`, `POST /:id/results/approve`, `/results/block` all exist under `/projects/:pid/tasks` (a request to each answers with something other than "route not found"; the unbuilt ones answer 501). **[business]**
2. `GET /tasks`, `GET /tasks/:id` at the old root paths → 404. **[technical]**
3. `GET /projects/:other/tasks/:id` for a task of the first project → 404. **[business]**
4. `GET /projects/:pid/tasks?status=NOPE` → 400. **[technical]**

**Source:** decision 2026-10-17.

> **Uncertain (Q7):** In code, `cancel`, `logs`, `results/approve` and `results/block` raise `NotImplementedException` (501). The decision says the routes "live" here. I wrote the requirement as "routes exist under the project", not "they work". Confirm that is the MVP intent.

### SR-TASK-02 GET /tasks/service-info is deleted

**Happy path:** The route no longer exists.

**Validation cases:**
1. `GET /tasks/service-info` → 404. **[technical]**
2. `GET /projects/:pid/tasks/service-info` → 404. **[technical]**
3. No mention of `service-info` in `openapi.json` or docs. **[technical]**

**Source:** decision 2026-10-17.

### SR-TASK-03 GET /projects/:pid/tasks/:id/trigger returns the task's PR and trigger repository

**Happy path:** The response has the PR's `number` and `merge_commit_sha`, and a nested trigger repository with `id`, `repo_path` and `uri`. Results delivery uses it to find the PR.

**Validation cases:**
1. Task made from a PR → 200 with `number`, `merge_commit_sha`, `trigger_repository.id`, `trigger_repository.repo_path`, `trigger_repository.uri`. **[business]**
2. Task created by hand (API request, no PR) → 404. **[business]**
3. Task of another project → 404. **[technical]**
4. The Dagster delivery code calls this route and does not scan PR lists. **[technical]**

**Source:** decision 2026-10-17.

### SR-TASK-04 A finished task cannot change status

**Happy path:** `PATCH` of a task in SUCCESS, FAILED or CANCELED to a different status is refused. The same status again is fine.

**Validation cases:**
1. `PATCH` a SUCCESS task `{"status": "RUNNING"}` → 409. **[business]**
2. `PATCH` a SUCCESS task `{"status": "SUCCESS"}` → 200. **[technical]**
3. `PATCH` a RUNNING task `{"status": "SUCCESS"}` → 200. **[technical]**
4. `PATCH` with an invalid status or an unknown field → 400. **[technical]**

**Source:** ADR 0019 §12 item 12 (supersedes ADR 0017's "PATCH accepts any valid status").

### SR-TASK-05 Retry resets a failed or canceled task

**Happy path:** `POST .../retry` on a FAILED or CANCELED task sets it PENDING, adds one to `attempt` and clears run fields.

**Validation cases:**
1. Retry a FAILED task → 200, `status: PENDING`, `attempt` up by 1, `executor_run_id` null. **[business]**
2. Retry a RUNNING task → 400. **[technical]**
3. Retry a SUCCESS task → 400. **[technical]**

**Source:** ADR 0017.

> **Uncertain (Q8):** The handover asks whether "retry on a SUCCESS task returns 400" is intended. ADR 0017 says only FAILED or CANCELED can retry, so I wrote 400. Confirm.

### SR-TASK-06 Create and validate a task through the API

**Happy path:** `POST /projects/:pid/tasks` records the request, validates the spec and dataset, and creates a PENDING task. A rejected request is kept as REJECTED and creates no task. `POST /tasks/validate` checks without creating.

**Validation cases:**
1. Valid body on an enabled project → 201 with `id`, `api_request_id`, `status: PENDING`. **[business]**
2. Same body on a disabled project → 409. **[business]**
3. Invalid spec → 400 and no task row. **[business]**
4. `POST .../tasks/validate` with a valid body → 200, no task created. **[technical]**

**Source:** ADR 0001, ADR 0002 (background); behaviour confirmed in code. ADR 0019 §6 for the dataset rule.

> **Decided (Q9, 2026-10-19):** task creation on a disabled project is a 409. The project lock is gone; this is the only place a disabled project is refused.

---

### 3.5 Results delivery (SR-RES)

### SR-RES-01 Results are project-scoped

**Happy path:** `POST /projects/:pid/results {task_id, results_repository_id}` creates the delivery (201). The same call again returns the existing one (200). A task from another project is a 404.

**Validation cases:**
1. First `POST` for a SUCCESS task → 201, `step: UNKNOWN`, `state: IN_PROGRESS`, `results_repository_id` is the **global** id. **[business]**
2. Same `POST` again → 200, same id. **[technical]**
3. `POST` with a task of another project → 404. **[business]**
4. `POST` naming a results repository the project is not linked to → 400. **[technical]**
5. `GET /projects/:pid/results?step=OPENED` → only OPENED results. **[technical]**

**Source:** ADR 0019 §8, §11.

### SR-RES-02 Only a SUCCESS task can have results

**Happy path:** `POST /results` for a task that is not SUCCESS is refused.

**Validation cases:**
1. `POST /results` for a PENDING, RUNNING or FAILED task → 409. **[business]**
2. `POST /results` for a SUCCESS task whose link is inactive → 409. **[business]**
3. Re-posting a result that already exists → 200 even if the link is inactive now. **[technical]**

**Source:** ADR 0019 §12 item 13.

> **Uncertain (Q10):** ADR §12 item 13 marks the inactive-link 409 with "(?)" ("agreed for now"). Built as written. Owner to confirm.

### SR-RES-03 Result progress only moves forward

**Happy path:** `PATCH /projects/:pid/results/:id` records `step`, `state`, `number`, `url`, errors. Steps only go forward.

**Validation cases:**
1. `PATCH {"step": "OPENED", "number": 5, "url": "..."}` → 200. **[business]**
2. After OPENED, `PATCH {"step": "PUSHED"}` → 400. **[business]**
3. `PATCH` with an unknown field, a negative counter or a non-string `step` → 400. **[technical]**
4. `PATCH /projects/:other/results/:id` → 404. **[technical]**

**Source:** ADR 0008; confirmed in the tests handover (round 1 fixes).

### SR-RES-04 Delivery pushes a branch and opens a results PR

**Happy path:** When a task reaches SUCCESS, the delivery job finds the task's PR through `/tasks/:id/trigger`, pushes the zipped results, `spec.json` and `metadata.json` to a new branch, opens a PR into the results repository's default branch, and records PUSHED then OPENED with `state: DELIVERED`. Delivery never changes the task's status.

**Validation cases:**
1. End to end, a PR with a valid spec → task SUCCESS, result goes UNKNOWN, PUSHED, OPENED. **[business]**
2. Task status after delivery (success or failure) is still SUCCESS. **[business]**
3. The results PR title names the source repository, PR number and task id. **[technical]**
4. A delivery that fails records `state: FAILED`, an `error` and one more `attempts`, and the Dagster run fails. **[technical]**
5. A relaunched delivery resumes: a branch already on the remote is not pushed again; an existing PR is looked up before opening one. **[technical]**

**Source:** ADR 0007, ADR 0017, decision 2026-10-17 (`/trigger`). Resume behaviour from the code docstring.

### SR-RES-05 A results PR merged or closed is synced back

**Happy path:** The results sync sensor reads results at OPENED and later steps, asks the provider, and sets MERGED or CLOSED. It reads the results link by id, even when it is inactive.

**Validation cases:**
1. Merge the results PR → within a few ticks the result is MERGED with `merged_at` and `merge_commit_sha`. **[business]**
2. Close the results PR unmerged → result CLOSED. **[business]**
3. The sensor still works when the project's results link was revoked after the PR opened. **[technical]**

**Source:** ADR 0009, ADR 0019 §2 (visibility contract).

### SR-RES-06 Revoked or inactive results link in flight

**Happy path:** Revoke is immediate. A delivery that cannot proceed fails with a recorded error, not an exception from unpacking an empty list.

**Validation cases:**
1. Revoke the results link while a result exists and is not past PUSHED, then relaunch delivery → result `state: FAILED`, `error: "results repository access revoked"`. **[business]**
2. `GET /projects/:pid/repositories/results` for a project whose link is revoked → 200 with the link and its flags (not an empty list). **[technical]**

**Source:** ADR 0019 §2, §5, §8.

> **Uncertain (Q11):** For a task that is SUCCESS **with no result row yet**, a revoked link makes `POST /results` return 409. The delivery sensor treats a 409 as "skip" (decision 2026-10-17). So no result is recorded and no error is shown, which differs from ADR §2 ("fails with a recorded error"). Also: the delivery sensor launches once per task attempt, so re-activating the link may not re-trigger delivery. Which behaviour does the owner want for a SUCCESS task with no result?

### SR-RES-07 A project with no results link is not handled

**Happy path:** For the MVP nothing handles this case. The intended fix is to block unlinking while tasks are in flight, and it is only a code comment.

**Validation cases:**
1. `dagster/app/backend.py` `get_results_repository` carries a comment saying this case is not handled and what the intended fix is. **[technical]**
2. No new behaviour is required (no test expects a handled failure for this case). **[business]**

**Source:** decision 2026-10-17.

> **Uncertain (Q12):** Code now allows `DELETE /projects/:pid/repositories/results/:id` in any project state (a soft delete; a task in flight gets a `REVOKED` result). Revoke keeps the row, so the unpack does not fail. Is the comment now outdated, or does the owner want a stricter rule?

---

### 3.6 Sensors (SR-SENS)

### SR-SENS-01 Ingest polls each repository once

**Happy path:** The ingest sensor lists trigger repositories that have an active link of an enabled project, polls each once with the repository's own secret from its cursor, and posts the new merged PRs. The poll has no base-branch filter; the backend matches per link.

**Validation cases:**
1. Two projects link one repository → the sensor makes one provider poll, not two. **[business]**
2. The sensor lists repositories with `GET /global/repositories/triggers?active_link=true` (no Python filtering). **[technical]**
3. A repository with no active link, or only links of disabled projects, is not polled. **[business]**
4. With nothing to poll, the sensor yields a skip reason, not an error. **[technical]**

**Source:** ADR 0019 §4, §11; decision 2026-10-17 (filtering in webserver).

### SR-SENS-02 Ingest posts at most 100 PRs per batch, oldest first

**Happy path:** PRs since the cursor are sorted by `(merged_at, number)` and posted in chunks of at most 100.

**Validation cases:**
1. 250 new PRs for one repository → three POSTs of 100, 100 and 50, in order. **[business]**
2. `create_pull_requests_batch` called with more than 100 raises before any request. **[technical]**
3. The cursor only moves once a batch is stored, so an older unposted PR is never left behind a newer one. **[technical]**

**Source:** decision 2026-10-17.

### SR-SENS-03 A failing repository does not stop the others

**Happy path:** An error on one repository is logged and the loop carries on with the rest.

**Validation cases:**
1. Repository A raises (bad token) and repository B has new PRs → B's PRs are stored in the same tick. **[business]**
2. Every failed repository URI is named in the error raised after the loop. **[technical]**

**Source:** decision 2026-10-17.

> **Uncertain (Q13):** After the loop, the sensor **raises** if any repository failed, so the tick shows as failed in Dagster. The decision says a failing repository "doesn't stop the others". It does not say whether the tick should look failed. Is a failed tick acceptable?

### SR-SENS-04 Evaluate reads each project's active links; filtering is in the webserver

**Happy path:** Evaluate loops over enabled projects, reads each one's active links and UNKNOWN triggers, and starts one evaluation run per repository. A run in flight for a repository is skipped.

**Validation cases:**
1. The sensor calls `GET /projects?enabled=true`. **[technical]**
2. The sensor calls `GET /projects/:pid/repositories/triggers?active=true`. **[technical]**
3. The sensor calls `GET .../pull_requests?state=UNKNOWN` and does not filter in Python. **[technical]**
4. A disabled project is not evaluated. **[business]**

**Source:** ADR 0019 §11, §12 item 11; decision 2026-10-17.

### SR-SENS-05 Evaluate turns a PR into a task or REJECTED

**Happy path:** The evaluate job reads the spec file at the merge commit. A valid spec creates the task through `POST .../task`. An invalid one is REJECTED with a cause.

**Validation cases:**
1. A PR adding one valid `.json` spec under `watch_dir` → trigger YIELDED, task PENDING. **[business]**
2. A PR adding one invalid spec → trigger REJECTED with `state_cause`, no task. **[business]**
3. A PR adding two spec files under `watch_dir` → REJECTED. **[technical]**

**Source:** ADR 0006, ADR 0002, decision 2026-10-17 (IGNORED removed).

### SR-SENS-06 New 409s are skipped, not errors

**Happy path:** A 409 from the webserver in these places is logged as a warning and skipped:
- creating a task for an inactive link or a non-UNKNOWN trigger,
- patching the status of a finished task,
- creating a result for a task that is not SUCCESS, or through an inactive link.

**Validation cases:**
1. Evaluate gets 409 from `POST .../task` → no exception, the PR is skipped. **[business]**
2. A run-status sensor gets 409 patching a finished task → no exception, the task keeps its status. **[business]**
3. Delivery gets 409 from `POST /results` → no exception, no result created. **[business]**
4. A 400 or 500 in the same places still raises (only 409 is skipped). **[technical]**

**Source:** decision 2026-10-17; ADR 0019 §12 items 10, 12, 13.

### SR-SENS-07 A disabled secret is refused before its token is read

**Happy path:** The Dagster secret reader checks `enabled` first and raises `PermissionError` without touching Kubernetes.

**Validation cases:**
1. `read_secret_value` on a secret with `enabled: false` → `PermissionError`, and the Kubernetes read is never called. **[business]**
2. The launcher fails a task whose dataset's secret is disabled, with a `state_cause`. **[business]**
3. Every git client is built through the same checked reader. **[technical]**

**Source:** decision 2026-10-17.

> **Uncertain (Q14):** The handover review says a **revoked project secret link** (`ProjectSecret.active`) is also not checked at use. The decision names only a disabled secret. I did not write a requirement for the link case. Is it needed?

### SR-SENS-08 Launcher starts runs for PENDING tasks of enabled projects

**Happy path:** The launcher yields one run request per PENDING task, with run key `task/<id>/<attempt>`. It patches nothing on success. A task whose dataset link is inactive is failed with a cause.

**Validation cases:**
1. A PENDING task of an enabled project → one run request tagged `trigger=task`, `task_id`, `project_id`. **[business]**
2. A PENDING task of a disabled project → not launched. **[business]**
3. A PENDING task whose dataset link is inactive → task patched to FAILED with a cause, no run. **[business]**
4. The launcher reads enabled projects only: a disabled project's PENDING tasks wait. **[technical]**

**Source:** ADR 0017; ADR 0019 §11.

### SR-SENS-09 Only run-status sensors write task status

**Happy path:** Five run-status sensors copy the Dagster run status to the task. Delivery runs are tagged `trigger=delivery` and never change the task.

**Validation cases:**
1. A run moves to STARTED → task `RUNNING` with `started_at`. **[business]**
2. A run finishes → task SUCCESS or FAILED with `completed_at`. **[business]**
3. A delivery run finishing or failing does not change the task. **[business]**

**Source:** ADR 0017.

### SR-SENS-10 Dagster never fetches lists to filter them in Python

**Happy path:** Every filter a sensor needs is a query option on the webserver list route.

**Validation cases:**
1. The sensors use these webserver options: `?active_link=true`, `?active=true`, `?enabled=true`, `?state=`, `?status=` and `?step=`. **[technical]**
2. No sensor or delivery code loads a list and then filters it with a Python `if` on a field the webserver could filter (review each of `launcher.py`, `pr_evaluate.py`, `delivery/results.py`, `pull_request_sync.py`). **[technical]**
3. The webserver supports each option (`GET /projects?enabled=true` returns only those projects). **[technical]**

**Source:** decision 2026-10-17; ADR 0019 §11 ("Filter in the webserver").

> **Uncertain (Q15):** `pull_request_sync.py` loops over **all** projects (`get_projects()`, no filter) and then asks for results by step per project. The step filter is in the webserver. The project loop is not filtered. This looks intended (a disabled project's results PRs should still sync), but no source says so.

---

### 3.7 Healthchecks (SR-HC)

### SR-HC-01 Global and per-resource healthchecks

**Happy path:** `GET /global/healthcheck` checks every global dataset, secret, trigger repository and results repository. Each resource also has its own check. A failed check is reported in the body with HTTP 200.

**Validation cases:**
1. `GET /global/healthcheck` with all checks passing → 200, `status: "ok"`, each list has its items with `status: "ok"`. **[business]**
2. A repository check fails (unauthorized) → 200, overall `status: "error"`, that repository's `status: "unauthorized"`. **[business]**
3. A secret missing from its store → 200, `status: "secret_missing"` with the missing keys, no values. **[business]**
4. `GET /global/repositories/triggers/999/healthcheck` → 404. **[technical]**

**Source:** `webserver/app/healthcheck_api.py` docstring and the tests handover. No ADR covers healthchecks.

> **Assumption (Q16):** Healthchecks have no ADR. I wrote the requirement from the code docstring and the handover. Owner to confirm the expected status values and that failure is 200.

### SR-HC-02 Project and link healthchecks

**Happy path:** `GET /projects/:pid/healthcheck` rolls up the project's trigger and results links. Each link has its own check, which adds the link's state.

**Validation cases:**
1. `GET /projects/:pid/healthcheck` for a healthy project → 200, `status: "ok"`, lists its trigger links and its results link. **[business]**
2. `GET /projects/:pid/repositories/triggers/:T/healthcheck` → 200 with `active` and `project_id`. **[technical]**
3. The same call for a project that has no such link → 404. **[technical]**
4. No response contains a secret's value. **[business]**

**Source:** as SR-HC-01.

---

### 3.8 API conventions (SR-API)

### SR-API-01 Admin routes live under /global, unchanged

**Happy path:** `/users`, `/registries` and `/whitelisted_images` moved to `/global/...` with no other change. `PUT /global/users/reset-password` is deliberately unauthenticated: a new user swaps their temp password, which Keycloak checks.

**Validation cases:**
1. `GET /global/users` and `POST /global/users` exist (admin only). **[business]**
2. `PUT /global/users/reset-password` with no `Authorization` header is accepted (not 401). **[business]**
3. `GET /global/registries` exists. **[technical]**
4. `GET /users`, `GET /registries` at the old paths → 404. **[technical]**
5. `/projects/:pid/users` does not exist yet. **[business]**

**Source:** decision 2026-10-17.

> **Uncertain (Q17):** `whitelisted_images_api.py` has the `/global/whitelisted_images` prefix, but its blueprint is **not registered** in `app/__init__.py` (a `TODO(whitelisted_images)` comment). `openapi.json` still lists it, and also `/task_requests*`. The decision says it "lives under `/global` unchanged". Should the route answer, or is "disconnected" the MVP state (legacy models are parked)?

### SR-API-02 Consistent errors, pagination and filters

**Happy path:** Errors are JSON `{"error": "..."}`. Wrong types and bad bodies give 400. Unique violations give 409. Lists paginate consistently.

**Validation cases:**
1. A request with a wrong-typed field → 400 with `{"error": ...}`. **[technical]**
2. A duplicate global resource → 409. **[technical]**
3. A page past the end → 200 with empty items. On the task and PR lists, `page=0` or `per_page=0` is treated as 1 (200). **[technical]**
4. Non-numeric `page` → 400. **[technical]**

**Source:** tests handover (app fixes round 1); ADR 0019 §12 item 15 (clamping, "(?)", see Q2).

### SR-API-03 The API exposes the real model; no flat compatibility layer

**Happy path:** Link responses nest the global resource. Project paths use the global id.

**Validation cases:**
1. `GET /projects/:pid/repositories/triggers` items have `trigger_repository` (nested), `watch_dir`, `base_branch`, `pr_cursor`, `pr_count`, `enabled`, `revoked`, `active`. **[technical]**
2. `GET /projects/:pid/repositories/triggers/:id` uses the repository's id; the link row id does not appear in any URL. **[technical]**
3. `GET /project_trigger_repositories` (cross-project list) does not exist → 404. **[technical]**

**Source:** ADR 0019 §4, §11.

> **Uncertain (Q18):** ADR 0019 §11's table and §12 do not yet list the task routes, `/trigger`, or `/global/users|registries|whitelisted_images`. ADR 0017 still says `PATCH /tasks/<id>` accepts any status and `/cancel` is not implemented. `openapi.json` still lists stale routes. The ADRs are behind the 2026-10-17 decisions. Should the ADRs be updated before the review?

---

### 3.9 Dev tooling and tests (SR-DEV)

### SR-DEV-01 Dagster tests run in Docker

**Happy path:** `dagster/run_tests.sh` builds the image from `dagster/Dockerfile` and runs pytest in Docker Compose, like the webserver.

**Validation cases:**
1. `cd dagster && ./run_tests.sh` builds and runs the unit tests with no local `dagster` install. **[technical]**
2. The test image is built `FROM` the locally built Dagster image. **[technical]**
3. CI mode (`run_tests.sh ci`) uses `docker-compose-tests-ci.yaml` only, and runs the Dagster and fncli tests (`make tests_dagster` calls it). **[technical]**

**Source:** decision 2026-10-17; commit `ce017d7b`.

> **Resolved (Q19):** `cd dagster && ./run_tests.sh ci` runs `app/tests` and `fncli/tests`: 470 passed (346 + 124), per the owner. The reviewer may re-run it.

### SR-DEV-02 Webserver tests

**Happy path:** `webserver/run_tests.sh` runs the suite in Docker Compose against Postgres.

**Validation cases:**
1. `cd webserver && ./run_tests.sh` → all pass (606 passed at the last recorded run). **[technical]**
2. Tests are black-box HTTP (status and body only), so they carry over to a later FastAPI move. **[technical]**
3. Each test uses a fresh database. **[technical]**

**Source:** tests handover.

### SR-DEV-03 fncli lives in dagster/fncli and shares app.* code

**Happy path:** The move is DONE. fncli lives in `dagster/fncli`, imports `app.*` models and the backend client, and has no copies. Install from the repo root with `pipx install --force --editable './dagster[cli]'`. `cd dagster && ./run_tests.sh ci` runs the Dagster and fncli tests together (470 passed: 346 + 124).

**Validation cases:**
1. `dagster/pyproject.toml` has the `fncli` entry point and includes `fncli*`. **[technical]**
2. No `scripts/fncli` directory remains. **[technical]**
3. fncli imports models and backend client from `app.*` (no `dagster/fncli/dagster/` copy directory). **[technical]**
4. `fncli` tests are collected by `dagster/pyproject.toml` `testpaths` (`app/tests`, `fncli/tests`) and run in the Dagster test image. **[technical]**

**Source:** decision 2026-10-17; commits `ed10916f`, `5c0c0cbe`, `95d61117`.

> **Resolved (Q20):** The move is done and committed (`ed10916f` move, `5c0c0cbe` copies deleted, `95d61117` tests fixed). No `scripts/fncli` and no `dagster/fncli/dagster/` remain, and nothing outside `project/handover/` points at `scripts/fncli`. What is left: the gitea-mirror branch still has `fncli mirror` under `scripts/fncli` (see Q28).

### SR-DEV-04 Schema: baseline migration edited in place

**Happy path:** The shared-resources schema is folded into `001_baseline` (with the old 002), per ADR 0013, because the line is unreleased.

**Validation cases:**
1. `alembic upgrade head`, `downgrade base`, `upgrade head` on a fresh Postgres → all succeed. **[technical]**
2. Only one migration file for the webserver (no `002_*`). **[technical]**
3. `ck_triggers_state_cause_for_rejected` exists: a REJECTED trigger needs a `state_cause`. **[technical]**

**Source:** ADR 0019 §10, ADR 0013; tests handover ("checked before handoff").

### SR-DEV-05 Dev cluster ownership guard

**Happy path:** Only one worktree owns the dev cluster at a time. Deploy, upgrade and teardown check it.

**Validation cases:**
1. `make deploy-owner` shows the owner. **[technical]**
2. A deploy from another worktree is refused unless forced. **[technical]**

**Source:** commit `c47e2044` (PR #552). Control board note.

### SR-DEV-06 End-to-end script

**Happy path:** `scripts/e2e_shared_resources.sh` drives the whole flow on the local `kind-fn` cluster with fncli.

**Validation cases:**
1. Watched PR → trigger YIELDED with a task → task SUCCESS → results PR opened. **[business]**
2. Unwatched PR → no trigger for the link. **[business]**
3. Invalid PR → REJECTED, no task. **[business]**
4. Teardown leaves nothing, and setting up again works. **[technical]**

**Source:** `project/handover/e2e-qa-plan.md`, tests handover.

> **Uncertain (Q21):** The script "has never been run". The QA plan (`e2e-qa-plan.md`) names the branch `moonshot/fncli-e2e`, which no longer exists on origin. Is the plan still the one to run?

---

### 3.10 Gitea mirror (GM)

Precedence for this section: ADR 0020 (with its "Decisions changed by the 2026-10-17 review"), then the README and the plan.

### GM-01 The mirror is self-contained

**Happy path:** The service has no knowledge of the federated node. No webserver calls, no shared schema, no Dagster. It runs beside Gitea.

**Validation cases:**
1. No import of `app.*` from the webserver or Dagster in `gitea-mirror/`; no call to the node's API. **[technical]**
2. The node uses a mirror by registering the Gitea repository as an ordinary trigger repository (no node code change needed). **[business]**

**Source:** ADR 0020 "Decision".

> **Uncertain (Q22):** ADR 0020 status line says "Proposed", but it is built and reviewed (2026-10-17). The control board says the mirror was un-parked on 2026-10-17 for an end-to-end plan. The branch descriptions still say "PARKED 2026-10-16". I treated it as built and in scope.

### GM-02 Outbound only, GitHub.com upstream only

**Happy path:** The service polls GitHub and pushes to Gitea. Nothing inbound is exposed to the internet. `upstream_uri` must be `https://github.com/<owner>/<repo>`.

**Validation cases:**
1. `POST /mirrors` with `upstream_uri` on another host → 400. **[business]**
2. `POST /mirrors` with userinfo, port, query or fragment in `upstream_uri` → 400. **[technical]**
3. The GitHub token is only ever sent to github.com. **[technical]**

**Source:** ADR 0020 "Decisions changed by the 2026-10-17 review".

### GM-03 Merged PRs become Gitea PRs marked manually-merged

**Happy path:** Per merged PR into the base branch, the service pushes the head as `pr/<n>`, opens a Gitea PR, and marks it `manually-merged` at GitHub's `merge_commit_sha`. The repository is a normal repository with `allow_manual_merge`. No comments, reviews or open PRs.

**Validation cases:**
1. A merged GitHub PR → a merged Gitea PR with `merge_commit_sha` equal to GitHub's. **[business]**
2. An open or closed-unmerged GitHub PR → not mirrored. **[business]**
3. Works for merge-commit, squash and fast-forward merges. **[technical]**
4. The repository is created with `allow_manual_merge: true`; the default branch is set to the base branch after the first push. **[technical]**

**Source:** ADR 0020 "What it does"; SPIKE.md; README "Sync behaviour".

> **Uncertain (Q23):** A rebase merge with rewritten SHAs was never found upstream and is untested (ADR 0020, SPIKE, plan). I expect it to behave like squash. Not verified.

### GM-04 PRs are replayed in merged order, with the base rewound

**Happy path:** For each PR, in `merged_at` order, the Gitea base branch is force-pushed to `merge_commit_sha^1`, the PR is opened, the base is fast-forwarded to `merge_commit_sha`, and the PR is marked merged. This makes the Gitea PR files endpoint return the right files.

**Validation cases:**
1. A merge-commit PR → `GET /pulls/{index}/files` returns its files (not an empty list). **[business]**
2. After a PR fails, the Gitea base branch is restored to the upstream tip. **[technical]**
3. A PR that keeps failing is quarantined (recorded as an error) and does not block the other PRs. **[technical]**
4. A per-mirror lock stops two syncs of one mirror running together (`POST /mirrors/:id/resync` → 409 while locked). **[technical]**

**Source:** ADR 0020 "What it does"; SPIKE.md; README "Sync behaviour".

### GM-05 Both PR numbers are stored and sent

**Happy path:** Gitea numbers PRs itself, so its number differs from GitHub's. The mirror stores both and the event carries both.

**Validation cases:**
1. After mirroring GitHub PR #126 as the first Gitea PR → `mirrored_pull_requests` has `number: 126`, `gitea_pr_number: 1`. **[technical]**
2. The webhook event has `number` (GitHub's) and `gitea_pr_number`. **[business]**
3. The event `merged_at` is GitHub's time (Gitea's merged time is the sync time). **[business]**

**Source:** ADR 0020 "What it does" and "Webhooks".

### GM-06 Sync starts from now; no history backfill

**Happy path:** Creating a mirror sets the cursor to now. Branches are pushed in full, but no older PRs are mirrored.

**Validation cases:**
1. `POST /mirrors` → cursor is about the creation time. **[business]**
2. A PR merged before the mirror was created is not mirrored. **[business]**
3. The cursor does not skip a PR with the same `updated_at` as another; it only moves past settled PRs. **[technical]**

**Source:** ADR 0020; README "Sync behaviour".

### GM-07 Authors are shadow Gitea users

**Happy path:** Each PR author is a Gitea user named after the GitHub login, acted as through the admin `Sudo` header, so `raised_by` matches upstream. Users are preloaded from contributors and collaborators on mirror creation and created on demand.

**Validation cases:**
1. A PR by GitHub user `alice` → the Gitea PR's author is the shadow user for `alice`. **[business]**
2. `POST /mirrors` returns `users_sync` (ok, skipped or failed). **[technical]**
3. A pre-existing non-shadow Gitea account with the same name → error, not reused. **[technical]**

**Source:** ADR 0020 "What it does"; README "Sync behaviour".

> **Uncertain (Q24):** ADR 0020 says users are "named after the GitHub login". The README (written after the review) says shadow users get a `gh-` prefix. I follow the README (later) but the ADR was not updated. Then the Gitea author name is `gh-alice`, and `raised_by` would not match upstream. Which is intended?

### GM-08 A PR is recorded before the cursor advances; repeats are harmless

**Happy path:** `unique(mirror_id, number)` plus recording the row before the cursor moves means a crash causes only a harmless repeat. Before opening a PR the engine looks for an existing Gitea PR for head `pr/<n>`.

**Validation cases:**
1. Sync twice with no new upstream PRs → the second run changes nothing (no new Gitea PRs, no new rows). **[business]**
2. A failure after the Gitea PR was opened but before its row was recorded → the retry resumes from the merge step and opens no second PR. **[technical]**

**Source:** ADR 0020; README "Sync behaviour" and "Known gaps"; plan finding 2.

### GM-09 Webhooks are generic subscriptions

**Happy path:** Anyone registers an endpoint with a secret reference for the HMAC key and an optional mirror filter. The service does not know who listens.

**Validation cases:**
1. `POST /webhooks {url, secret_namespace, secret_key, mirror_id}` → 201. The secret must exist and have a `token` field, or 400. **[technical]**
2. A webhook with `mirror_id: null` receives events for all mirrors; one with a `mirror_id` only for that mirror. **[business]**
3. A disabled webhook receives nothing. **[technical]**
4. `POST /webhooks/:id/test` sends a signed `ping`; a failure → 502 with the exception class. **[technical]**

**Source:** ADR 0020 "Webhooks".

### GM-10 Event body and signature

**Happy path:** After the PR is pushed to Gitea, a `pull_request.mirrored` event is POSTed to each matching endpoint, signed with HMAC-SHA256. The body matches `gitea-mirror/schema/pull_request.mirrored.json`.

**Validation cases:**
1. The body has `event`, `delivery_id`, `mirror`, `number`, `gitea_pr_number`, `title`, `author`, `merged_at`, `merge_commit_sha`, and validates against the JSON schema. **[technical]**
2. `X-Gitea-Mirror-Signature: sha256=<hex>` equals the HMAC of the raw body with the webhook's secret. **[technical]**
3. `X-Gitea-Mirror-Delivery` equals `delivery_id` and is the same UUID on every retry. **[business]**
4. `X-Gitea-Mirror-Timestamp` is sent but not signed (receivers must dedupe on the delivery id). **[technical]**

**Source:** ADR 0020 "Webhooks" and "Decisions changed by the 2026-10-17 review".

> **Uncertain (Q25):** The README's example body still shows `"delivery_id": "17"` (a row id), while the ADR and the README text say it is a UUID. The README example is stale. Confirm the UUID wins.

### GM-11 Delivery is from an outbox: at-least-once with retries

**Happy path:** Deliveries are queued, sent with 5 attempts and backoff from 30 seconds doubling. Only a 2xx counts. One bad webhook does not block the others.

**Validation cases:**
1. A receiver that fails then succeeds → the delivery is retried and ends `delivered`. **[business]**
2. After 5 failed attempts → `failed`, visible at `GET /webhooks/:id/deliveries`. **[business]**
3. A 3xx response counts as a failure; redirects are not followed. **[technical]**
4. A webhook whose secret lacks `token` does not stop other deliveries. **[technical]**
5. There is no redeliver route; an operator uses the in-pod helper `requeue_failed`. **[technical]**

**Source:** ADR 0020 "Webhooks" and review decisions; README.

### GM-12 Webhook URL policy

**Happy path:** In-cluster and private targets are allowed. Loopback, link-local, unspecified and the API server are refused. Redirects are not followed.

**Validation cases:**
1. `POST /webhooks` with `http://127.0.0.1/...` → 400. **[technical]**
2. `POST /webhooks` with `http://169.254.169.254/...` → 400. **[technical]**
3. `POST /webhooks` with `http://svc.ns.svc.cluster.local/...` → accepted. **[business]**
4. A URL with credentials → 400. **[technical]**

**Source:** ADR 0020 "Decisions changed by the 2026-10-17 review"; README "Input rules".

> **Uncertain (Q26):** Hosts are only checked at registration, ping and patch. DNS rebinding at delivery time is a known gap (plan). Does this matter for the MVP?

### GM-13 Own database, own API, bearer token

**Happy path:** The service has its own database `gitea_mirror` and its own cluster-only API. Every route except `/health` needs `Authorization: Bearer <token>`. Unknown fields are rejected.

**Validation cases:**
1. `GET /mirrors` with no token → 401. **[business]**
2. The app does not start if `GITEA_MIRROR_API_TOKEN` is unset or empty. **[technical]**
3. `POST /mirrors` with an unknown field → 400. **[technical]**
4. A duplicate upstream URI, or Gitea owner and repo → 409. **[technical]**
5. `GET /mirrors/:id/status` returns `cursor`, `last_sync_at`, `last_success_at`, `last_error`, `prs_mirrored`, `token_expired`. **[business]**

**Source:** ADR 0020 "State and configuration"; README "API".

### GM-14 Credentials are read by reference and passed safely

**Happy path:** GitHub tokens and HMAC keys are Kubernetes secrets named by `secret_namespace` and `secret_key`. They are never stored in the mirror's database and never put in a git remote URL or command line.

**Validation cases:**
1. No token appears in the `mirrors` or `webhooks` rows. **[technical]**
2. Git credentials are passed through `GIT_CONFIG_COUNT` environment variables, not argv. **[technical]**
3. An expired GitHub token gives a clear `token_expired` status, not a crash loop. **[business]**

**Source:** ADR 0020; README "Sync behaviour"; plan finding 13.

### GM-15 Health and resilience

**Happy path:** `GET /health` needs no token and reports the database and the sync thread.

**Validation cases:**
1. Healthy → 200 `{"status": "ok", "sync": {"alive": true, ...}}`. **[business]**
2. The database down, the sync thread dead, or no tick within 3 times the interval → 503. **[technical]**
3. An error in one mirror's tick does not stop the other mirrors. **[technical]**

**Source:** README "API"; plan finding 12.

### GM-16 Deployment: chart, RBAC, one replica

**Happy path:** The chart deploys the mirror behind `giteaMirror.enabled`. The service account has `get` on only the secrets it needs. The network policy allows egress to GitHub, Gitea, Postgres and webhook endpoints. One replica only. The Gitea admin init job creates the access token into `gitea-mirror-gitea-token`.

**Validation cases:**
1. `helm template` with `giteaMirror.replicaCount: 2` fails to render. **[technical]**
2. `helm unittest` for the mirror templates passes. **[technical]**
3. Install without `helm --wait`; the pod starts once the init job has created `gitea-mirror-gitea-token`. **[technical]**
4. The pod runs with a read-only root filesystem and has startup and liveness probes. **[technical]**

**Source:** ADR 0020 "Needed alongside it"; plan review table (findings 1, 17, 18).

> **Uncertain (Q27):** The chart and the install order were **not verified on a real cluster** (plan "Not verified"). The mirror was also never run against the real GitHub API, or over a real network for webhooks.

### GM-17 fncli mirror commands

**Happy path:** `fncli mirror add, list, status, resync, users-sync, delete, disable, enable` and `fncli mirror webhook add, list, deliveries, delete, disable, enable` call the service API.

**Validation cases:**
1. `fncli mirror --help` lists those commands. **[technical]**
2. `fncli mirror add` followed by `fncli mirror status` shows a mirror with a cursor. **[business]**

**Source:** ADR 0020 "Needed alongside it"; plan stage 8.

> **Uncertain (Q28):** On the gitea-mirror branch these commands live in `scripts/fncli` and import `fncli.dagster.utils` and `fncli.dagster.config`. On shared-resources, fncli is now `dagster/fncli` and those modules are gone (it imports `app.*`). The mirror commands must be ported to `dagster/fncli/cmds/mirror.py`. Do that when the branches merge?

### GM-18 Mirror tests

**Happy path:** Unit tests run with Postgres in Docker. Integration tests run against a real Gitea in Docker with recorded GitHub responses.

**Validation cases:**
1. `cd gitea-mirror && ./run_tests.sh` passes (336 passed, 29 skipped without Gitea at the last record). **[technical]**
2. `./run_gitea_tests.sh` passes with a real Gitea 28.1.0 (365 passed at the last record). **[technical]**
3. Alembic upgrade, downgrade, upgrade, check shows no drift. **[technical]**

**Source:** plan "Verified in a sandbox".

> **Uncertain (Q29):** `gitea-mirror/e2e/PLAN.md` and the `e2e/` scripts (mentioned on the control board) are **not on `origin/moonshot/gitea-mirror`** and I did not read them. They are uncommitted in the mirror's worktree. I did not use that worktree, as instructed.

### GM-19 The node-side webhook receiver is not part of this build

**Happy path:** The receiver that maps an event to a trigger repository and reuses the batch ingest is a later, node-side change. Until then, the node polls the mirrored Gitea repository like any other.

**Validation cases:**
1. No route in the webserver accepts mirror webhooks. **[business]**
2. A Gitea repository registered as a trigger repository is polled by the normal ingest sensor. **[business]**

**Source:** ADR 0020 "Needed alongside it"; plan "Hooking the node up (later)".

---

## 4. Out of scope / parked

| Item | Reason |
|---|---|
| Narrowing Dagster's secret RBAC | Ticket exists. User secrets share the release namespace. Decision 2026-10-17. |
| Credential rotation restarting Dagster | Dropped. Decision 2026-10-17. |
| Legacy models: registries, whitelisted images, the `project-name` header, data access requests | Parked. Decision 2026-10-17. They only moved under `/global`. |
| `/projects/:pid/users` | Comes later, not now. Users are node-level Keycloak users; project access is via data access requests (legacy). |
| Sensor redesign (per-PR job, delivery as an op, mirror webhook replacing ingest polling) | Parked. Decision 2026-10-17; `dagster-sensors-plan.md`. |
| Flask to FastAPI | Parked after the MVP. |
| Auth rework and normal-user permissions | Later full rewrite. Only the super user and the Dagster system user matter now (tests handover). |
| Drain and enabled guards on editing, deleting or unlinking resources | Replaced by pinning a task to its configuration and by soft delete (ADR 0019). Worst case a project keeps failing or lacks a secret. |
| Handling a project with no results link | Not for the MVP. Comment only (SR-RES-07). |
| Mirror webhook receiver on the node, `mirror_uri` and `mirror_secret_id` on trigger repositories | Later, node-side (ADR 0020). |
| Mirror: history backfill, open PRs, comments, reviews, branch deletion, other git hosts | Out of the mirror's scope (ADR 0020, README known gaps). |
| Real-time updates | Never a requirement. |
| Webhooks from GitHub straight into the node, Argo CD, one mirror per project, `disabled_reason` string, a flat compatibility API | Rejected in ADRs 0018, 0019 and 0020. |
| Audit and `@auth`/`@audit` changes | Out of scope (tests handover). |
| `audit` details overflow on a 4096-char `url` | Known, not fixed, out of scope. |

---

## 5. Open questions for the owner

Block A is bugs from the review. Block B has one question per note in the text (same Q number). Block C is smaller items. The A bugs are also in the `moonshot/s*` branch descriptions.

**A. Bugs found in review, still unfixed in code. Do they block the MVP?**

These are not requirements. The review found them and I checked the code: they are still there.

- **B1. Duplicate path in one PR gives a 500 for the whole batch.** The `# Claude (issue 1)` comment in `pr_ingest.py` is still there. Fix: de-duplicate changed-file paths.
- **B2. Fan-out racing a backfill can lose a trigger.** No row lock in `pull_request_fanout.py`. Fix: a per-repository lock.
- **B3. A PR merged in the same second as the cursor can be lost.** The poll uses `merged_at >`. Fix: poll with `>=`.
- **B4. A stale global cursor can replay a gap.** A link created with no stored PRs starts at the global cursor. Fix: start at `max(latest stored, now)`.
- **B5. A provider returning an empty file list.** The PR would be stored with no files and match nothing for good. The fix is to treat empty as truncated or refuse it.

**B. Notes in the text**

1. **Q1** (SR-GLOB-01): `PATCH /global/secrets/<label>` has no admin check. Accept for the MVP?
2. **Q2** (SR-GLOB-04): Confirm dataset `PATCH` returns 200 and task and PR lists clamp `page` and `per_page` below 1 (both marked "(?)" in ADR §12 item 15).
3. **Q3** (SR-PR-02): The code also stores a file `status`. OK?
4. **Q4** (SR-PR-03): The match rule needs a `.json` file with status `added` under `watch_dir`. The ADR says only "watch_dir against the path". Is the stricter rule intended?
5. **Q5** (SR-PR-03): Fan-out makes triggers for links of disabled projects, but ingest does not poll for them. Intended?
6. **Q6** (SR-PR-04): Is "no trigger at fan-out, REJECTED at evaluate when no watched file" the right reading of "REJECTED instead of IGNORED"?
7. **Q7** (SR-TASK-01): `cancel`, `logs`, `results/approve` and `results/block` return 501. Is "routes exist, not implemented" the MVP intent?
8. **Q8** (SR-TASK-05): Retry on a SUCCESS task returns 400. Intended?
9. **Q9** (SR-TASK-06): Task creation on a disabled project returns 409. Decided 2026-10-19.
10. **Q10** (SR-RES-02): POST `/results` through an inactive link returns 409 (marked "(?)").
11. **Q11** (SR-RES-06): A SUCCESS task with no result row and a revoked results link is silently skipped. ADR says "fails with a recorded error", and re-activating the link may not re-trigger delivery. Which behaviour?
12. **Q12** (SR-RES-07): The results link can be deleted in any project state (a soft delete). Is the "block unlinking while in flight" comment still wanted?
13. **Q13** (SR-SENS-03): The ingest tick raises after the loop if any repository failed. Acceptable?
14. **Q14** (SR-SENS-07): Should a revoked project secret link also be refused at use, or only a disabled secret?
15. **Q15** (SR-SENS-10): `pull_request_sync` loops over all projects, including disabled ones. Intended?
16. **Q16** (SR-HC-01): Healthchecks have no ADR. Confirm the status values and "failed check is still HTTP 200".
17. **Q17** (SR-API-01): The `whitelisted_images` blueprint is not registered, but `openapi.json` still lists it. Should it answer?
18. **Q18** (SR-API-03): ADR 0019 and ADR 0017 are behind the 2026-10-17 decisions. Update them before review? (ADR 0015 already says fncli is in `dagster/fncli` with no copies.)
19. **Q19** (SR-DEV-01): Resolved. Dagster plus fncli: 470 passed (346 + 124).
20. **Q20** (SR-DEV-03): Resolved. The move is done and committed. Only the mirror branch's `scripts/fncli` edits remain (Q28).
21. **Q21** (SR-DEV-06): The e2e script has never run. Is `e2e-qa-plan.md` still the plan (its branch `moonshot/fncli-e2e` is gone)?
22. **Q22** (GM-01): ADR 0020 says "Proposed"; branch descriptions say "PARKED"; the control board says un-parked for e2e. Treat the mirror as in scope and built?
23. **Q23** (GM-03): Rebase merges with rewritten SHAs are untested.
24. **Q24** (GM-07): Shadow users: ADR says named after the login; README says `gh-` prefix. Which one?
25. **Q25** (GM-10): The README example `delivery_id` is stale (`"17"`). UUID wins?
26. **Q26** (GM-12): DNS rebinding at delivery time is not covered. Needed for the MVP?
27. **Q27** (GM-16): Chart, install order, real GitHub and real network webhooks are not verified.
28. **Q28** (GM-17): `fncli mirror` must be ported to `dagster/fncli/cmds/mirror.py` (it uses the deleted `fncli.dagster.*` modules). When?
29. **Q29** (GM-18): `gitea-mirror/e2e/PLAN.md` was not read (not on origin).

**C. Smaller open items found while reading**

- The mirror's finding 11 (advisory lock connection idle in transaction for a whole sync) is open and unverified under pgbouncer.
- `ensure_user` in the mirror is not atomic across concurrent runs.
- `project.in_flight_task_ids` has a possible cartesian product in the "undelivered" subquery (s0b description). It may report tasks as in flight wrongly. It predates the moonshot.
- `naive_utc` in `dtos/trigger_repository.py` does not convert a non-Z offset to UTC, and `validate_initial_cursor` can raise a `TypeError` (500) on `+00:00` input (s4 description).
- fncli `get_or_assign_*` returns an existing link even if it points at different settings.
