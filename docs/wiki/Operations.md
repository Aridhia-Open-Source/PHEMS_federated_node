# Operations

How to look after a running Federated Node 2.x: start the sensors, switch things on and off, check that it is healthy, and work out why a pull request did nothing.


## Start the sensors

Every Dagster sensor starts **stopped**, so nothing is polled and no task runs until you start them. Do it once the first project is enabled. The order does not matter, and after a reinstall you start them again.

**With the API** (admin):

```sh
curl -sS -X PATCH "$FN/dagster/sensors" "${AUTH[@]}" -d '{"status": "RUNNING"}' | jq
curl -sS "$FN/dagster/sensors" "${AUTH[@]}" | jq        # every sensor, its status and latest tick
```

**With the Dagster UI.** It has no login, so reach it by port-forward and never publish it:

```sh
kubectl port-forward -n federated-node svc/federatednode-dagster-webserver 3000:80
```

Open http://localhost:3000, go to **Automation**, and turn on all twelve sensors.

The sensors, by group:

| Group | Sensors | Job |
|---|---|---|
| `ingest` | `git_pull_request_ingest_sensor` | Polls each trigger repository once and stores new merged pull requests |
| `evaluate` | `git_pull_request_evaluate_sensor` | Turns each stored pull request into a task, or rejects it with a cause |
| `launcher` | `task_launcher_sensor` | Starts a Dagster run for each pending task |
| `status` | five run-status sensors, `task_reconcile_sensor` | Copy the run's status onto the task |
| `delivery` | `task_results_delivery_sensor`, `results_pull_request_sync_sensor`, `results_delivery_retry_sensor` | Push results, track the results pull request, retry failures |

How often they tick is the chart value `fnDagster.sensors.minIntervalSeconds` (30 seconds by default), and how long a failed run waits before a retry is `retryIntervalSeconds` (60 seconds). To pause the node, stop the sensors the same way, with `{"status": "STOPPED"}`.


## Switch things on and off

Two flags sit on every resource. **Enabled** is a switch anyone allowed to manage the resource can flip. **Revoked** is admin only and takes effect at once. A resource is **active** only when it is enabled and not revoked, and only active ones are used.

| To stop | Do this |
|---|---|
| A whole project | `PATCH /projects/<id>` with `{"enabled": false}`, or `{"revoked": true}` (admin) |
| One project's use of one resource | `PATCH` the assignment: `/projects/<id>/datasets/<dataset_id>`, `/projects/<id>/repositories/triggers/<id>`, `/projects/<id>/repositories/results/<id>` |
| A resource for every project | `PATCH /global/datasets/<id>`, `/global/repositories/triggers/<id>`, `/global/repositories/results/<id>` or `/global/providers/<id>` with `enabled` or `revoked` |
| A credential | `PATCH /global/secrets/<label>`. Disabling it also disables the datasets and repositories that use it, and moves its value to the quarantine namespace. They stay off when you turn the secret back on |

What happens to work in flight:

- The launcher fails a pending task, with the cause in its `state_cause`, when anything it uses is revoked or deleted.
- A result for a revoked or deleted results repository is recorded as `REVOKED` and nothing is delivered.
- A result for a disabled one is retried once it is switched back on.

`DELETE` is a soft delete: the record leaves the API, its assignments go with it, and the name is free again. Deleting a dataset or repository that projects still use is a `409` listing them. The full table of what each state does is in the repo's [revoke-and-enabled.md](https://github.com/Aridhia-Open-Source/PHEMS_federated_node/blob/beta/docs/architecture/revoke-and-enabled.md).


## Checking on it

| Question | Where to look |
|---|---|
| Can everything be reached? | `GET /global/healthcheck`, `GET /projects/<id>/healthcheck`, and per resource `GET /global/datasets/<id>/healthcheck`, `/global/secrets/<label>/healthcheck`, `/global/providers/<id>/healthcheck`, `/global/repositories/triggers/<id>/healthcheck`, `/global/repositories/results/<id>/healthcheck` |
| What is this project doing? | `GET /projects/<id>/tasks` |
| Is a run stuck or failing? | The Dagster UI, **Runs**, for the logs of each step |
| Are the sensors running? | `GET /dagster/sensors`, or the Dagster UI **Automation** page |
| Whole-node checklist | The repo's [deploy and health checklist](https://github.com/Aridhia-Open-Source/PHEMS_federated_node/blob/beta/project/QA/deploy-and-health.md) |

### Reading a run

Open the Dagster UI by port-forward (above), and go to **Runs**. A task's run is tagged with the task's id. Its logs show each step, including whatever the container wrote to stdout and stderr.

### A pull request was merged and nothing happened

| Cause | How you see it |
|---|---|
| Sensors are stopped (the default) | `GET /dagster/sensors`: `STOPPED` |
| The project is disabled, or an assignment is inactive | The project or assignment shows `enabled` false or `revoked` true |
| The pull request does not add a `.json` file under `watch_dir`, or targets another branch | No trigger is made for that project (it is skipped and logged) |
| It was merged before the trigger repository was assigned or the project enabled | Skipped by design. Enable with `backfill`, or merge a new one |
| It adds more than one spec file, or the spec is not valid | The trigger is `REJECTED` and `state_cause` says why |
| A token is wrong or expired | The resource's healthcheck fails and names it. Rotate it with `PATCH /global/secrets/<label>` |
| The task stays pending | `state_cause` on the task: usually the dataset assignment is inactive or its secret is disabled. Fix the cause, then `POST /projects/<id>/tasks/<task_id>/retry` |
| The task starts but its container cannot reach the database | The container times out connecting. The database is not in `taskNetworkPolicy.datasetEgress` ([Deploy: Core](./Deploy-Core#let-tasks-reach-their-dataset)) |

### Results not delivered

A succeeded task whose results do not appear: check the task's results (`GET /projects/<id>/tasks/<task_id>/results`). A failed delivery shows its error and is retried by the `delivery` sensors. The usual causes are a results zip over 10 MiB (`fnDagster.results.maxZipBytes`) and a token without write access to the results repository. A task that **failed** delivers nothing.


## Known limits in the beta

- The per-run folders on the shared results volume are not removed after delivery. Watch the volume's size.
- A result over the size cap has no other route: it fails.
- Cancelling a task, reading its logs through the API, and approving or blocking results are not built.
- Not built yet: registering container registries and allowing only listed images, permissions per dataset for each user, review of a task before its results leave, and file datasets (DuckDB, SQLite).
- The Dagster UI has no login. Reach it only by port-forward.

The repo's [known issues](https://github.com/Aridhia-Open-Source/PHEMS_federated_node/blob/beta/project/QA/known-issues.md) list the open items, with what the node does today.
