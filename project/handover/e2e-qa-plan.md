# End-to-end QA plan: global resources and Dagster sensors, local Gitea, fncli

For a Claude Code session running on the owner's laptop. It exercises the real stack (webserver, Keycloak, Postgres, Dagster,
Gitea on the `kind-fn` cluster) and checks what the unit tests cannot: that the sensors, the webserver rules and Gitea work together.
Out of scope: the Gitea mirror, auth and normal-user permissions. It runs against the owner's local `kind-fn` cluster only: never a shared or production cluster, and it never tears the cluster down.

**Branch under test:** `moonshot/shared-resources` (global resources, GitProvider, tasks under projects, fncli in `dagster/fncli`). Run it from the `fn-worktrees/moonshot/shared-resources` worktree.

## Rules for the runner

- Run the scenarios in order. Stop if S0 or S1 fails: nothing else is meaningful.
- **Do not fix anything.** Record each scenario as PASS, FAIL or BLOCKED with the evidence, then carry on. Report the bugs; the owner decides.
- Write results to `artifacts/e2e-qa/<date>/results.md` (template at the end) and keep each `project-show` snapshot next to it.
- After a FAIL, capture: `fncli sensor-status`, and the last 200 log lines of the backend and the Dagster code server
  (`kubectl get pods -A | grep -E "backend|dagster"`, then `kubectl logs <pod> --tail=200`).
- Sensors tick at most every 10 seconds. "Wait 2 ticks" means about 30 seconds; the scenarios use 60.
- Only the test project, its global resources and the `QaTwo` project are created or changed. `teardown-project` removes them.

## Setup (once)

From the repo root, with kubectl on context `kind-fn`:

```bash
# Work in the fn-worktrees/moonshot/shared-resources worktree (git pull --ff-only); never switch branches in the main checkout.
# Use the cluster that is already running (kubectl on context kind-fn, tilt green). Only if there is none, create it:
#   make helm_deps && make deploy && tilt up --stream     (see dagster/fncli/EXAMPLES.md "Run the project from scratch")
# NEVER run `make teardown` here: it wipes the owner's dev cluster. Ask first.
pipx install --force --editable './dagster[cli]' && fncli hello-world
QA=artifacts/e2e-qa/$(date +%F-%H%M); mkdir -p "$QA"
snap() { fncli project-show > "$QA/$1.json"; }
prs()  { fncli project-show | jq -c '.trigger_links[0].pull_requests | map({number,state,task_id})'; }
count() { fncli project-show | jq -c '[(.trigger_links[0].pull_requests|length), (.tasks|length)]'; }   # [PRs, tasks]
tasks() { fncli project-show | jq '.tasks|length'; }
wait_for() {  # wait_for '<jq expression that is true when done>' <seconds> [project name]
  local end=$((SECONDS+$2))
  until [ "$(fncli project-show ${3:+--project $3} | jq -r "$1")" = "true" ]; do
    [ $SECONDS -ge $end ] && { echo "TIMEOUT: $1"; return 1; }; sleep 10; done; }
```

## Scenarios

### S0. Preflight
`kubectl config current-context` is `kind-fn`; backend `:5000`, Gitea `:4000` and Dagster `:3000` answer (`curl -sI`); `fncli hello-world` works; `jq` is installed.
**Pass:** all true.

### S1. Setup builds the project
`fncli setup-project && fncli project-healthcheck && fncli verify-project; snap S1`
**Pass:** both exit 0. `project-show` shows one enabled project with one active trigger link, results link and dataset link, no PRs and no tasks (the secrets are global; `secret_links` may be empty).

### S2. Happy path: PR to task to delivery to merged results PR
```bash
fncli start-sensor --sensor all && fncli sensor-status
fncli open-pr --kind watched --merge --watch --timeout 300       # note the PR number it prints
wait_for '.trigger_links[0].pull_requests | any(.state=="YIELDED" and .task_id != null)' 300
wait_for '.tasks | any(.status=="SUCCESS")' 600
wait_for '.results | any(.step=="OPENED")' 300
N=$(fncli project-show | jq '.results[0].number'); fncli merge-results-pr --number "$N"
wait_for '.results | any(.step=="MERGED")' 300
fncli verify-project; fncli verify-repo; snap S2
```
**Pass:** each wait succeeds, the task went PENDING to SUCCESS, the result moved UNKNOWN, PUSHED, OPENED, MERGED, and `verify-project` and `verify-repo` report no problems.

### S3. Invalid spec is rejected, no task
```bash
t0=$(count); fncli open-pr --kind invalid --merge
wait_for '.trigger_links[0].pull_requests | any(.state=="REJECTED")' 180
fncli project-show | jq '.trigger_links[0].pull_requests | map(select(.state=="REJECTED"))'; snap S3
```
**Pass:** the PR is REJECTED, `state_cause` is set, `task_id` is null, the task count did not grow.

### S4. PR outside the watched directory creates no trigger
```bash
c0=$(count); fncli open-pr --kind unwatched --merge; sleep 60; c1=$(count); snap S4; echo "$c0 -> $c1"
```
**Pass:** `$c0` equals `$c1`: no new PR row and no task for the link.

### S5. Idempotency: restarting ingest does not duplicate
```bash
c0=$(count); fncli stop-sensor --sensor ingest; fncli start-sensor --sensor ingest; sleep 60; c1=$(count); echo "$c0 -> $c1"
```
**Pass:** equal. (Run it again after S6 and S7.)

### S6. Revoked link: nothing new, then a backfill
```bash
c0=$(count); t0=$(tasks); fncli link-set trigger --revoked true --expect 200
fncli project-show | jq '.trigger_links[0].active'               # false
fncli open-pr --kind watched --merge; sleep 60; echo "revoked: $c0 -> $(count)"
fncli link-set trigger --revoked false --expect 200
wait_for ".tasks | length >= $((t0+1))" 180; echo "unrevoked: $c0 -> $(count)"; snap S6
```
**Pass:** while revoked the counts are unchanged (no trigger, no task); after un-revoking the missed PR gets its trigger and a task (counts +1 each).

### S7. Disabled link needs the lock, then behaves like revoked
```bash
fncli link-set trigger --enabled false --expect 409               # unlocked: refused
fncli project-set --locked true --expect 200
fncli link-set trigger --enabled false --expect 200               # needs no task in flight: wait for S6's task to finish first
c0=$(count); t0=$(tasks); fncli open-pr --kind watched --merge; sleep 60; echo "disabled: $c0 -> $(count)"
fncli link-set trigger --enabled true --expect 200; fncli project-set --locked false --expect 200
wait_for ".tasks | length >= $((t0+1))" 180; echo "enabled: $c0 -> $(count)"; snap S7
```
**Pass:** the unlocked change is 409; while disabled the counts are unchanged; after enabling the missed PR is picked up (counts +1 each).

### S8. A task in flight blocks lock-gated changes (best effort, timing dependent)
Open a watched PR; as soon as `.tasks` has a task that is not finished:
```bash
fncli open-pr --kind watched --merge
wait_for '.tasks | any(.status=="PENDING" or .status=="QUEUED" or .status=="RUNNING")' 120
fncli project-set --locked true --expect 200
fncli link-set trigger --enabled false --expect 409               # the body lists the task id
fncli project-set --locked false --expect 200
```
**Pass:** 409 naming the task. If the task finishes too fast to catch, mark BLOCKED, not FAIL.

### S9. Disabling a global repository stops its ingest
Wait until the project is drained: no unfinished task and the last result is OPENED or MERGED (a result still IN_PROGRESS makes the next call 409).
```bash
fncli project-set --locked true --expect 200
fncli global-set trigger --enabled false --expect 200
c0=$(count); fncli open-pr --kind watched --merge; sleep 60; echo "global off: $c0 -> $(count)"
fncli global-set trigger --enabled true --expect 200; fncli project-set --locked false --expect 200
sleep 90; echo "global on: $c0 -> $(count)"; snap S9
```
**Pass:** counts unchanged while off. After turning it on, **record** what happens to the PR merged in the gap. Expected: it appears (the cursor is the last stored PR), but the ADR says history is not replayed, so note the actual behaviour either way.

### S10. A second project on the same repository
```bash
fncli second-project-setup QaTwo
t0=$(tasks); fncli open-pr --kind watched --merge
wait_for ".tasks | length >= $((t0+1))" 300                       # the test project
wait_for '.tasks | length >= 1' 300 QaTwo                         # the second project, from the same PR
fncli project-show --project QaTwo | jq '.trigger_links[0].pull_requests, .tasks'
fncli link-set trigger --revoked true --project QaTwo --expect 200
c0=$(count); q0=$(fncli project-show --project QaTwo | jq '.tasks|length')
fncli open-pr --kind watched --merge; sleep 60
echo "test project: $c0 -> $(count)"; echo "QaTwo tasks: $q0 -> $(fncli project-show --project QaTwo | jq '.tasks|length')"
fncli second-project-teardown QaTwo                               # record the status: 204, or 409 if something is in flight
```
**Pass:** both projects get their own trigger and their own task for the same PR (different task ids); after revoking QaTwo's link only the test project gets the next one.

### S11. Token lost: clear failure, then recovery
```bash
fncli delete-gitea-token --entity trigger                         # the repo's stored token is now invalid
c0=$(count); fncli open-pr --kind watched --merge; sleep 60; fncli sensor-status
fncli project-healthcheck; echo "exit $?"; echo "$c0 -> $(count)"
t0=$(tasks); fncli init-git-secret --entity trigger && fncli verify-git-secret --entity trigger
wait_for ".tasks | length >= $((t0+1))" 300; snap S11
```
**Pass:** ingest shows an auth error in `sensor-status` (not a crash loop), `project-healthcheck` exits non-zero, no new trigger; after the new token the PR is ingested and processed. **Record** whether other sensors kept ticking.

### S12. A failing task stays failed
```bash
fncli open-pr --kind failing --merge                              # a valid spec whose task exits non-zero
wait_for '.tasks | any(.status=="FAILED")' 600
fncli project-show | jq '.tasks, .results'; snap S12
```
**Pass:** the task ends FAILED and has no result row; nothing is delivered for it; its status does not change afterwards (check again after 2 minutes).

### S13. Sensors restarted mid-flow
```bash
t0=$(tasks); fncli stop-sensor --sensor all
fncli open-pr --kind watched --merge; sleep 30
fncli start-sensor --sensor all
wait_for ".tasks | (length >= $((t0+1))) and all(.status != \"PENDING\")" 600; snap S13
```
**Pass:** the PR is processed once the sensors start, and no task is left PENDING (the run-status sensors must start before the launcher; `start-sensor --sensor all` orders them).

### S14. Teardown and set-up again
```bash
fncli teardown-project -y
fncli project-show; echo "exit $?"                                # expected: project not found
fncli setup-project && fncli project-healthcheck && fncli verify-project
```
**Pass:** teardown leaves nothing (project, global resources, secrets, Gitea repos and tokens gone), and setting up again works from scratch.

### S15. Known gaps: probe and record, do not count as failures
- **More than 100 merged PRs behind one cursor:** stop ingest, merge 101 watched PRs in a loop (`for i in $(seq 101); do fncli open-pr --kind watched --merge; done`), start ingest. Expected today: ingest errors every tick and nothing is processed (the batch is capped at 100).
- **A revoked secret link is still used:** only if `project-show` lists a secret link (`setup-project` does not create one: otherwise mark BLOCKED). `fncli link-set secret --revoked true`, then open a PR. Expected today: it is still ingested (the token is read without checking).
- **Delivery with no results link:** not testable from fncli; skip.

## Pass criteria
Required: S0 to S7, S9 to S11, S13, S14. S8 is best effort. S12 should pass. S15 is informational.

## Results template (`results.md`)

| Scenario | Result | Evidence (file or command output) | Notes |
|---|---|---|---|
| S0 | | | |

Then: a list of bugs (scenario, the exact commands, expected, actual, logs), the cluster and branch commit, and a one-paragraph verdict:
does the global-resources flow work end to end, and which sensors or rules misbehaved?
