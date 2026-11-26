# 0041 Flux Upgrade Verification

Status: Proposed (draft: options only, codepint chooses)

## Context

Flux (ADR 0031) upgrades a node in place: a new chart version in the site repository becomes the running
release. If the new version is broken (a bad migration, a pod that does not start, a task run that fails), the
node stays broken until someone rolls back, and a rollback cannot undo a migration.

What we are trying to achieve:

1. **Clean upgrades.** An upgrade either finishes and is proven working, or leaves the node as it was. No half
   state, no hand fixes.
2. **No lost work.** Pull requests merged during an upgrade still become tasks; tasks running when it starts
   finish and deliver.
3. **Proof, not hope.** The same checks QA runs (ADR 0040: test cases as YAML, set up and torn down through the
   operator) gate every upgrade: health, login, a `demo-fn` pull-request trigger run with its results PR, and
   the access rules. One set of test cases serves QA, CI and upgrades.
4. **Little to run per site.** Sites are small teams; the mechanism must be cheap to operate and the same at
   every site.

Beta nodes are greenfield; this is about every upgrade after the first deploy. Researchers wait minutes to hours
for results, so a short pause in task runs is acceptable; a broken node or a lost task is not.

## Options

Building blocks shared by several options:

- **Pause switch** (new): one node-wide flag. The launcher starts no new tasks; ingest keeps storing merged pull
  requests and their triggers wait; running tasks finish and deliver. Unpausing launches the waiting triggers,
  so nothing merged during the window is lost. Each project's own `enabled` is left alone (disabling every
  project instead would wake projects an admin switched off on purpose, and the gap rules of ADR 0011 would skip
  or backfill per project).
- **Test project** (new): one allow-listed project that still runs while paused, set up and torn down through
  the operator from the ADR 0040 test cases.
- **Backup** (xo N-165): `pg_dump` of the nexus and Keycloak databases before a migration runs.

### Option 1: pause, upgrade in place, test, resume (Flux and Helm hooks)

- A Helm pre-upgrade hook Job sets the pause, waits until nothing is running, and takes the backup.
- Flux upgrades the release (one version at a time, so migrations need not stay backward compatible).
- Flux's Helm test step (`test.enable` on the HelmRelease) runs the test project's cases; on success it unpauses.
- On failure Flux rolls the release back (remediation) and the backup is restored; the node stays paused until an
  operator looks.
- No new components. Tests the real upgrade on real data. Costs a pause and, on failure, a restore.

### Option 2: the same steps, orchestrated by Flagger

- Flagger's webhooks drive the same gates: confirm-rollout (pause and drain), pre-rollout (run the test cases),
  post-rollout (unpause), rollback.
- But Flagger always runs the old and new versions side by side, so both talk to the same database at once and
  every migration must work with old and new code (expand first, contract a release later).
- Gives a visible rollout state and metrics, at the price of a new component and the migration rule.

### Option 3: Flagger blue/green, no pause

- New pods start next to the live ones on the Gateway API; pre-rollout webhooks run the test cases against the
  new pods; the HTTPRoute moves only when they pass.
- No pause at all. Shared production database, so the expand/contract migration rule applies, and a migration is
  only exercised on production.
- Most useful if task runs ever must not pause.

### Option 4: a throwaway copy with a copy of the production database

- Flux first deploys the new version as a short-lived second release (ADR 0042) with its own in-cluster Postgres,
  filled from a `pg_dump` of production (nexus and Keycloak; records, not datasets, so minutes).
- The migration and the test cases run on the copy; if green, the real release is upgraded (by Option 1 or 3);
  the copy and its data are deleted.
- The copy must not act as production: Dagster sensors and the operator off (or pointed at a test Gitea),
  outbound traffic blocked. The Keycloak copy holds real users and password hashes: it stays in the cluster.
- Tests the exact migration on real data before production is touched; the most moving parts.

### Comparison

| | 1 Pause, in place | 2 Flagger gates | 3 Flagger blue/green | 4 Throwaway copy |
|---|---|---|---|---|
| Clean upgrade (all or nothing) | yes, with restore | yes, with restore | yes | yes, before prod is touched |
| No lost work | yes (pause) | yes (pause) | yes (no pause) | as the option that upgrades prod |
| Migration tested on real data before prod | no (backup instead) | no | no | yes |
| Migrations must stay backward compatible | no | yes | yes | no |
| Task runs pause | yes | yes | no | no for the test, yes/no for the switch |
| New components | none | Flagger | Flagger | copy Job, second release |
| Uses ADR 0040 test cases | yes | yes | yes | yes |

Also, whatever is chosen: turn on Flux's Helm test and rollback on the HelmRelease (cheap, and Option 1 is built
on it).

## Consequences

- Every option needs the ADR 0040 test cases to be runnable unattended against a node; that work comes first.
- Options 1 and 2 need the pause switch and the test project in nexus-api and the launcher.
- Options 1, 2 and the restore path need the backup work (N-165).
- Options 2 and 3 add Flagger to every site and the expand/contract rule to every migration.

## Alternatives considered

- A second cluster per site for staging: the most isolated, the most expensive per site.
- Disable every project instead of a pause switch: loses each project's own `enabled` and needs per-project
  backfill (see Option 1's building blocks).

## Open questions

- Which option for beta, and which later?
- Where the pause flag lives (a nexus-api setting or a record), who may set it, and how the operator and Dagster
  see it.
- How the test project is allow-listed and named; whether it can run on a production node at all.
- Which ADR 0040 test cases gate an upgrade (all, or a smoke subset).
