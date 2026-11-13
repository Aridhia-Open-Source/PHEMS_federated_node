# Fable review session, 2026-11-13: summary

Eight review agents and one checking agent ran against `dagster-develop` (wiki work against `docs/wiki-diagrams`). All reviews were read-only and time-boxed to about 8 minutes each. A ninth agent then tried to refute the findings of the first five reports.

## Where each report is

| Review | Branch | File |
|---|---|---|
| Security | `fable-security-13-11-2026` | `project/reviews/2026-11-13/security-review.md` |
| Code (nexus-api and Dagster) | `fable-code-13-11-2026` | `project/reviews/2026-11-13/code-review.md` |
| Tests | `fable-tests-13-11-2026` | `project/reviews/2026-11-13/test-review.md` |
| Helm chart | `fable-chart-13-11-2026` | `project/reviews/2026-11-13/chart-review.md` |
| Docs against code | `fable-docs-13-11-2026` | `project/reviews/2026-11-13/docs-drift.md` |
| Dagster side | `fable-dagster-13-11-2026` | `project/reviews/2026-11-13/dagster-review.md` |
| Kubernetes | `fable-kubernetes-13-11-2026` | `project/reviews/2026-11-13/kubernetes-review.md` |
| Wiki fixes (commits, not a report) | `fable-wiki-13-11-2026` (on top of `docs/wiki-diagrams`) | `README.md`, `Architecture.md`, `Operations.md` |
| This summary | `fable-summary-13-11-2026` | `project/reviews/2026-11-13/summary.md` |

## How far to trust it

- The check covered 31 findings from the first five reports: 27 confirmed, 3 overstated, 0 wrong, 1 not checked.
- "RAN" below means a local command was executed (`helm template`, `python3 -c`, `git grep`, `ls`). "READ" means the code was read only.
- No test suite, docker build or cluster was touched by anyone.
- The Dagster and Kubernetes reports arrived after the check started, so **none of their findings have been checked by a second agent**.
- Every review was partial. Each report ends with a list of what it did not reach.

## Fix before beta

1. **Any ordinary user can run a task against any project.** `nexus/api/app/tasks_api.py:246` (`post_tasks`) checks only the `can_exec_task` scope. `k8s/federated-node/scripts/realms.json` gives that scope to the `Users` role. The data access request check is off (`models/task.py:150`). The launcher picks up every PENDING task whatever created it (`dagster/app/definitions/sensors/task/launcher.py:29`), there is no image allow-list (`models/task.py:172`), and the pod receives the dataset credentials. Checked: confirmed, high. If the API trigger is legacy, the short fix is to restrict or remove the route rather than build project checks for it.
2. **Task pods can reach every private address.** `k8s/federated-node/templates/task-network-policy.yaml:43-48` allows 10/8, 172.16/12 and 192.168/16 on any port. The check confirmed the policy text; the Kubernetes review adds that this likely includes nexus-api, Keycloak and the Kubernetes API through Traefik (inferred from the policies, not tested).
3. **Tests that never run.** `nexus/api/tests/test_live_client_integration.py:22`, `test_all_tasks_list.py:92` and `test_task_launch.py:19` use `parents[2]`, which is `nexus/`, so their skip conditions are always true (confirmed by evaluating the paths). The fix is `parents[3]` plus mounting `dagster/` in the test compose file. `test_task_run_resources.py:17` uses `parents[3]`, which by path arithmetic should raise `IndexError` in the container; this needs one real run to settle.
4. **Chart suites that never run.** `k8s/federated-node/tests/failures/` is outside the default `tests/*_test.yaml` glob and nothing passes a different one (`build/helm-unittest/Dockerfile:8`, `scripts/run_helm_tests.sh:18`, `.github/workflows/build.yml:183-185`). Confirmed by reading.
5. **One failing project stops pull request evaluation for all projects.** `dagster/app/definitions/sensors/base.py:117` with `sensors/git/pr_evaluate.py:30-32`. From the Dagster review; not second-checked.
6. **A queued or running task whose Dagster run is lost stays that way forever.** `dagster/app/definitions/sensors/task/reconcile.py:57`. From the Dagster review; not second-checked.
7. **A pull request merged in the same second as the cursor is never ingested.** `dagster/app/github.py:60-63`, `gitea.py:58-61`, cursor cut to whole seconds in `nexus/api/app/models/trigger_repository.py:50-55`. Confirmed by reading. Rare, but silent and permanent.

## Park until after beta

- Chart: `gitea.enabled: true` fails to render with the dev example values (`templates/gitea-init-job.yaml:67`, confirmed with `helm template`); `rollMe` random annotation restarts nexus-api on every upgrade and shows permanent drift (`templates/_helpers.tpl:123-125`, confirmed by rendering twice). The second one matters once Flux is in use.
- Kubernetes: Dagster service accounts can read every project secret though the code no longer does (`templates/dagster-user-roles.yaml:15-39`); no Pod Security Admission labels on the namespaces; the run's credentials Secret is only deleted when a final status arrives (`nexus/api/app/tasks_api.py:206-208`).
- Dagster: permanent launch errors retried every tick (`launcher.py:31-35`); ODBC connection string built with an unquoted password (`pipes.py:273-279`); spec file path unquoted in the provider URL (`github.py:90`, `gitea.py:96`).
- Code: a PATCH without `step` succeeds on a final result (`nexus/api/app/results_api.py:207-250`), low to medium.
- Tests: `/dagster/sensors` routes and `POST/GET /global/users` have no test; state rule tests derive expectations from the tables they test; several Keycloak tests have no asserts.
- Docs: ten small mismatches, listed in `docs-drift.md`.
- Wiki: the researcher guide names `fncli trigger`, which is not in `dagster/fncli/cmds/` on `dagster-develop`, `dagster-main` or `beta`.

## Checked and found sound

- Every route has a scope check except login, refresh and health.
- No `shell=True`, `yaml.load`, `pickle`, `verify=False`, `extractall` or f-string SQL in `nexus/api/app` or `dagster/app`.
- Git runs with an argument list; the token goes in a header, not the URL; results zipping skips symlinks; output is confined to the clone.
- The task pod spec already meets the `restricted` Pod Security standard.
- Task egress blocks the public internet and the cloud metadata address.
- No SSRF path found: provider URLs come only from nexus-api.

## Second check, finding by finding

| # | Finding | Report | Verdict | Evidence | Real severity |
|---|---|---|---|---|---|
| 1 | `post_tasks` has no project-level check | security | CONFIRMED | READ `tasks_api.py:246-298`; realms.json: `Users` role holds `can_exec_task` | High |
| 2 | API-created task launches | security | CONFIRMED | READ `launcher.py:29`, `task_config.py:165-192` | High |
| 3 | No image allow-list | security | CONFIRMED | RAN grep and the regex, `models/task.py:118,172` | High with 1 |
| 4 | Task can send credentials out | security | OVERSTATED | READ `task-network-policy.yaml:27-52`, `values.yaml:163-177`: private ranges and DNS only | Medium |
| 5 | Regex accepts trailing newline | security | CONFIRMED | RAN regex | Low |
| 6 | Dead SQL validator | security | CONFIRMED | RAN grep | Low |
| 7 | `test_live_client_integration.py` always skipped | tests | CONFIRMED | RAN python on `parents[2]`/`[3]`; READ compose and test Dockerfile | High (tests) |
| 8 | Two contract tests always skipped | tests | CONFIRMED | RAN python | Medium |
| 9 | `parents[3]` IndexError in container | tests | CONFIRMED (arithmetic only) | RAN python; not run in docker | Unknown until run |
| 10 | `tests/failures/` suites never run | tests | CONFIRMED | READ Dockerfile, script, mise.toml, build.yml | Medium |
| 11 | 409 sensor test has no assert | tests | CONFIRMED | READ `test_task_run_status_sensor.py:127-131` | Low |
| 12 | `__snapshot__` empty | tests | CONFIRMED | RAN ls | Trivial |
| 13 | `gitea.enabled` fails to render | chart | CONFIRMED | RAN helm template: nil pointer at `gitea-init-job.yaml:67` | Medium |
| 14 | `rollMe` random annotation | chart | CONFIRMED | RAN helm template twice, two values | Medium |
| 15 | `keycloak.replicas: 0` renders 2 | chart | CONFIRMED | RAN helm template | Low |
| 16 | No `additionalProperties: false` anywhere | chart | OVERSTATED | RAN: a typo'd key passes; but 3 nodes do set it (`:81,889,898`) | Low |
| 17 | `nodeId` default fails schema | chart | OVERSTATED | RAN: defaults fail on `host`/`storage` anyway | Low |
| 18 | Capacity pattern rejects `Ti` | chart | CONFIRMED | READ `values.schema.json:16-17` | Low |
| 19 | db Service targetPort | chart | CONFIRMED | READ `db-service.yaml:9-11` | Low |
| 20 | Postgres liveness threshold 1, no strategy | chart | CONFIRMED | RAN grep `db-deployment.yaml:54` | Low to medium |
| 21 | Autoscaling values without an HPA | chart | CONFIRMED | RAN grep | Low |
| 22 | Middleware hook-weight without hook | chart | CONFIRMED | READ `middleware.yaml:7-8` | Trivial |
| 23 | PATCH without `step` on a final result | code | CONFIRMED | READ `results_api.py:207-250`, `delivery/results.py:110-130` | Low to medium |
| 24 | Same-second merge never ingested | code | CONFIRMED | READ `github.py:60-63`, `gitea.py:58-61`, `trigger_repository.py:50-55` | Medium |
| 25 | Retry outside `TASK_MOVES` | code | CONFIRMED | READ `tasks_api.py:223-226`, `task_status.py:24-39` (table comment says intended) | Low |
| 26 | Pagination copy differs | code | CONFIRMED (one of three read) | READ `backend.py:83-115` | Trivial |
| 27 | `dev.k8s/` missing | docs | CONFIRMED | RAN ls, git ls-files | Low |
| 28 | `routes.py` missing | docs | CONFIRMED | RAN ls | Low |
| 29 | `auth-mvp-plan.md` reference dead | docs | CONFIRMED | RAN ls | Low |
| 30 | ADR 0024 not in docs/README; 0021 reference wrong | docs | CONFIRMED | RAN grep, ls | Low |
| 31 | fncli README says POST | docs | UNVERIFIED | line read, routes not opened | Low |

Not second-checked: everything in the Dagster and Kubernetes reports, the remaining code findings (reconcile start time, ingest fetching everything before storing, delivery retry decided in Dagster), the "no test" inventory, most chart schema gaps, and three docs items.

## Was it a good use of Fable tokens?

Cost: nine agents at roughly 85k tokens each, about 770k in total. The first batch took the 5-hour window from 60% to its limit in about ten minutes.

Worth it:
- Security, Kubernetes and Dagster reviews. These needed reasoning across files (scope policy, launcher, network policy, pod spec) and produced the findings that matter before beta.
- The second check. It ran `helm template` and path arithmetic, turned leads into facts, and corrected three overstatements.

Not worth it at Fable prices:
- Docs against code. It is a lookup job: does this path, task or route exist. Sonnet or Haiku does it equally well.
- Most of the chart review (schema gaps, missing suites, hard-coded values) and the "which routes have no test" inventory. Mechanical comparison.

What held the result back:
- The 8-minute cap. Every agent spent a large share of its budget getting oriented and stopped with most of its scope unread. Five shallow passes found less per token than two deep ones would have.
- Read-only with nothing run. The cheapest findings to confirm (path arithmetic, `helm template`) were left as guesses until the check.

A better spend of the same tokens:
- One Fable agent, no time cap, tracing the task path end to end: who can create a task, what the launcher accepts, what the pod can reach, what leaves the node. Allowed to run `helm template` and local scripts.
- One Fable agent on the Dagster sensors with the same freedom.
- Everything mechanical on Sonnet, then one Fable pass to check and rank.

## Where to use Sonnet on the 100k-line cumulative PR

The aim is to shrink what a person has to read, then spend Fable only on the part that needs judgement.

Sonnet (or Haiku where marked):
1. **Sort every changed file into a class** (Haiku is enough): generated (`requirements*.txt` with hashes, `openapi.json`, `schema.d.ts`, `package-lock.json`, snapshots), pure moves and renames, docs, tests, chart, real code. Report lines per class. The real review size is probably a fraction of 100k.
2. **One Sonnet agent per package** (`nexus/api`, `nexus/ui`, `dagster/app`, `dagster/fncli`, `k8s/federated-node`, `scripts`): a short summary of what changed and why, and a list of files that look unrelated to the package's purpose.
3. **Find what can be deleted**: files added and never imported, functions with no caller, duplicate helpers, leftover experiments, commented-out code. Each candidate with the grep that shows it is unused.
4. **Find what can be split out**: changes with no dependency on the rest (docs, the Tilt and mise tooling, chart-only changes, the UI) that could land as their own small PRs first.
5. **Apply the mechanical fixes from these reports**: `parents[3]`, the missing asserts, the docs mismatches, the chart test glob.
6. **Write the missing tests** for the routes named in `test-review.md`, copying the existing test patterns.

Fable:
- Decide the landing order once the inventory is in: which slices, in what order, what each depends on.
- Review the slices where a mistake is expensive: auth and scopes, task launch, network policy and RBAC, state rules, results delivery.
- A final check of whatever Sonnet proposes to delete.
