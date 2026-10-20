# Deploy and health checks

Does the node come up, and does it say so truthfully? Do this section first: every other section assumes it passes.

Needs: `kubectl` access to the node's cluster, the Dagster UI, an admin login, and `fncli` if the node is the dev cluster (see [the index](README.md)).

## All pods are running and the Dagster code location loads

1. `kubectl get pods -A`. Look for the backend, the Dagster webserver, daemon and code server, Postgres, Keycloak and (on the dev cluster) Gitea.
2. Open the Dagster UI, Deployment, and open the code location.

- **Expected:** every pod is `Running` or `Completed`. The code location loads with no error and lists the jobs and the twelve sensors. The only known exception is a crash-looping `keycloak-realm-init` pod ([known issues](known-issues.md)).
- **Rule:** the components and the sensor and job inventory are in [docs/architecture/flows.md#components-and-network].
- **Automated by:** Manual only. `dagster/app/tests/test_definitions.py` checks the wiring in a test process, not a deployed cluster.
- [ ] Pass
- [ ] Fail — notes:

## The install hooks finished

1. `kubectl get jobs -A` and `kubectl get pods -A | grep -i init`.

- **Expected:** the database init, migration and Keycloak init hooks are `Completed`. The schema is the single baseline migration, applied once. Check the hook names on your release.
- **Rule:** one baseline migration ([Global resources, linked to projects]).
- **Automated by:** Partly automated: `webserver/integration_tests/` runs the Keycloak initialiser against a real Keycloak over several runs; it misses the chart's hooks on a real cluster.
- [ ] Pass
- [ ] Fail — notes:

## The images are the ones under test

1. `kubectl get pods -A -o custom-columns=NS:.metadata.namespace,POD:.metadata.name,IMAGE:.spec.containers[*].image`.
2. Write the backend, Dagster and run-image tags in the results header (see [the index](README.md)).

- **Expected:** the tags match the release being tested, including the run image that task pods and delivery use.
- **Rule:** the end-to-end README requires images built from the branch under test, `pypipes-fn` included ([dagster/fncli/tests/e2e/README.md]).
- **Automated by:** Manual only.
- [ ] Pass
- [ ] Fail — notes:

## Every sensor starts stopped, and starts together

1. Before starting anything: `fncli sensor-status` (or Dagster UI, Automation).
2. `fncli start-sensor --sensor all`.
3. Wait three sensor intervals. `fncli sensor-status` again.

- **Expected:** step 1 shows twelve sensors, all `STOPPED` on a fresh install. After step 3 all twelve are running and their last ticks are skipped (with a reason) or successful. No `FAILURE` tick.
- **Rule:** sensors default to `STOPPED` and can be started in any order ([The Dagster pipeline: ingest as an op, twelve sensors, one interval, retries]).
- **Automated by:** Partly automated: `dagster/app/tests/test_definitions.py`, `dagster/app/tests/test_config.py` (stopped by default) and `dagster/fncli/tests/test_sensor.py` (`all` covers twelve); they miss the deployed chart value and real ticks. The end-to-end suites need the sensors running first.
- [ ] Pass
- [ ] Fail — notes:

## Sensors tick at the configured interval

1. Read the configured minimum interval (`DAGSTER_SENSORS_MIN_INTERVAL_SECONDS`, chart value `fnDagster.sensors.minIntervalSeconds`; the default is 30 seconds).
2. In the Dagster UI open one sensor and read the times of its last ticks.

- **Expected:** ticks are at least the configured interval apart; no sensor is ticking much slower than the others (a tick can take longer when the daemon is busy).
- **Rule:** one interval for every sensor ([The Dagster pipeline: ingest as an op, twelve sensors, one interval, retries]).
- **Automated by:** Partly automated: `dagster/app/tests/test_config.py` checks the default and the environment override; it misses the real daemon.
- [ ] Pass
- [ ] Fail — notes:

## The global healthcheck and each GlobalResource's healthcheck are truthful

1. `GET /global/healthcheck` with an admin token.
2. For one dataset, Secret, GitProvider, TriggerRepository and ResultsRepository: `GET /global/datasets/<id>/healthcheck`, `/global/secrets/<label>/healthcheck`, `/global/providers/<id>/healthcheck`, `/global/repositories/triggers/<id>/healthcheck`, `/global/repositories/results/<id>/healthcheck`.

- **Expected:** `ok` when everything is reachable. A failure (a wrong token, an unreachable database or git host) shows in the body with a 200, never a 500, and the global check reports an error when any one fails. No response contains a Secret value.
- **Rule:** the healthcheck routes are listed in [HANDOVER.md] ("Routes").
- **Automated by:** Partly automated: `webserver/tests/test_healthchecks_all.py` mocks the connections; it misses real reachability, real tokens and the real datasets database.
- [ ] Pass
- [ ] Fail — notes:

## The project healthcheck and the dataset check pass

1. `fncli project-healthcheck` (exit code 0 and `ok` expected).
2. `fncli verify-project`.

- **Expected:** both exit 0. On a node that is not set up with fncli, use `GET /projects/<pid>/healthcheck` and the project's link healthchecks (`/projects/<pid>/repositories/triggers/<id>/healthcheck`, `.../results/<id>/healthcheck`, `/projects/<pid>/datasets/<id>/healthcheck`, `/projects/<pid>/secrets/<label>/healthcheck`).
- **Rule:** a project reports its links' health ([HANDOVER.md], "Routes").
- **Automated by:** Partly automated: both fncli commands run in the setup steps of every end-to-end suite (dev cluster, Gitea only); `webserver/tests/test_healthchecks_all.py` covers the shapes. Neither covers a deployed node with GitHub.
- [ ] Pass
- [ ] Fail — notes:

[docs/architecture/flows.md#components-and-network]: ../../docs/architecture/flows.md#components-and-network

<!-- link definitions -->
[Global resources, linked to projects]: ../decisions/0006-global-resources-and-project-links.md
[HANDOVER.md]: ../../HANDOVER.md
[The Dagster pipeline: ingest as an op, twelve sensors, one interval, retries]: ../decisions/0014-dagster-pipeline-ops-sensors-and-retries.md
[dagster/fncli/tests/e2e/README.md]: ../../dagster/fncli/tests/e2e/README.md
