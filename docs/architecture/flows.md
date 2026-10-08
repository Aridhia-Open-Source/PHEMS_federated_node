# Flows and components

How a merged pull request becomes a task, a run, and a results pull request. Decisions: [index](../../project/decisions/README.md). Entities and states: [entities.md](entities.md).

## End to end

```mermaid
flowchart TD
    A([PR merged in the trigger repository]) --> B[git_pull_request_ingest_sensor]
    B -->|"saves PullRequestTrigger UNKNOWN"| C[git_pull_request_evaluate_sensor]
    C -->|"RunRequest per repo with UNKNOWN PRs"| D[evaluate_repository_pull_requests_job]
    D -->|"no watched file"| I1[trigger IGNORED + state_cause]
    D -->|"several files or invalid spec"| I2[trigger REJECTED + state_cause]
    D -->|"valid spec: POST .../pull_requests/n/task"| E[trigger YIELDED + Task PENDING]
    E --> F[task_launcher_sensor]
    F -->|"RunRequest task/id/attempt"| G[k8s_pipes_job]
    G -->|"launches"| P[[task pod in the task namespace, artifacts volume]]
    G --> H["run-status sensors (QUEUED, RUNNING, SUCCESS, FAILED, CANCELED)"]
    H -->|"PATCH /tasks/id"| T[Task status mirrors the run]
    G -->|"run SUCCESS"| J[task_results_delivery_sensor]
    J -->|"RunRequest deliver/task/attempt"| K[deliver_results_job]
    K -->|"zip, spec.json, metadata.json pushed to a branch"| L[result PUSHED]
    K -->|"PR from branch into default branch"| M[result OPENED]
    M --> N[results_pull_request_sync_sensor]
    L --> N
    N -->|"sync_results_pull_requests_job"| O{provider state}
    O -->|merged| Q([result MERGED])
    O -->|closed| R([result CLOSED])
    O -->|open| M
```

All sensors are STOPPED by default and started by the operator ([0009](../../project/decisions/0009-sync-reconciler-and-operational-rules.md)). The delivery job only runs after a task run succeeds; a failed delivery is re-launched by hand.

## Sequence across fncli, backend, Dagster and the git host

```mermaid
sequenceDiagram
    autonumber
    actor Dev as Developer
    participant CLI as fncli
    participant Git as Gitea / GitHub
    participant BE as Backend API
    participant DG as Dagster (daemon + run pods)
    participant K8s as Kubernetes

    Dev->>CLI: setup-project
    CLI->>BE: create project, secrets, trigger and results repository, dataset
    CLI->>Git: create repos and tokens (Gitea, via localhost:4000)
    CLI->>K8s: store tokens in the secrets
    Dev->>CLI: start-sensor all
    CLI->>DG: GraphQL start sensors (3000)
    Dev->>CLI: open-pr --merge
    CLI->>Git: branch, commit spec file, PR, merge

    loop every 10 s while sensors run
        DG->>BE: list trigger repositories
        DG->>K8s: read each repository's token
        DG->>Git: list closed pulls since the cursor
        DG->>BE: POST pull requests batch (UNKNOWN)
    end
    DG->>BE: list UNKNOWN pull requests
    DG->>Git: PR files, spec file at the merge commit
    DG->>BE: POST pull request task (YIELDED) or PATCH IGNORED / REJECTED
    DG->>BE: list PENDING tasks of enabled projects
    DG->>K8s: k8s_pipes_job starts the task pod
    DG->>BE: PATCH task QUEUED, RUNNING, SUCCESS
    DG->>BE: POST /results (task, results repository)
    DG->>Git: clone results repository, push branch with results.zip, spec.json, metadata.json
    DG->>BE: PATCH result PUSHED, then OPENED (number, url)
    DG->>Git: open PR from branch
    Dev->>CLI: merge-results-pr
    CLI->>Git: merge results PR
    DG->>Git: get PR state (sync sensor)
    DG->>BE: PATCH result MERGED (merged_at, merge_commit_sha)
```

## Components and network

```mermaid
flowchart LR
    subgraph Host["Developer host (WSL)"]
        FN["fncli"]
        TILT[Tilt]
        REG[("registry localhost:5001")]
        FWD["port-forwards: backend 5000, Dagster UI 3000, Gitea 4000, Postgres 5432, datasets DB 5433, Keycloak 8080"]
    end
    subgraph Kind["kind cluster kind-fn"]
        subgraph FNNS["namespace fn"]
            BE["Backend (Flask, port 5000)"]
            DB[(Postgres db)]
            DDB[(datasets db)]
            GITEA["Gitea service gitea.fn.svc:4000"]
            DWS[Dagster webserver]
            DD[Dagster daemon]
            CS["Code server dagster-fn gRPC"]
            RUN["Run pods: k8s_pipes_job, deliver_results_job (image dagster-fn:tilt-run)"]
            VOL[("artifacts volume")]
        end
        TNS["Task pods (task namespace)"]
        KC["Keycloak (namespace keycloak)"]
    end
    EXT[GitHub API]

    TILT -->|builds, live update| REG
    REG --> BE
    REG --> CS
    REG --> RUN
    FN -->|"localhost:5000"| FWD
    FN -->|"localhost:4000 (fn.svc translated)"| FWD
    FN -->|":3000 GraphQL"| FWD
    FWD --> BE
    FWD --> GITEA
    FWD --> DWS
    BE --> DB
    BE -->|validates tokens| KC
    DD -->|"sensors, API calls"| BE
    DD -->|"clone, API gitea.fn.svc:4000"| GITEA
    DD -->|launches| RUN
    DD --> CS
    RUN -->|"PATCH results, git push"| BE
    RUN --> GITEA
    RUN --> TNS
    RUN --- VOL
    TNS --- VOL
    TNS --> DDB
    DD -.->|"provider github"| EXT
    RUN -.->|"provider github"| EXT
```

The run pod (not the daemon) delivers results because it mounts the artifacts volume. Task pods run in `DAGSTER_TASK_NAMESPACE` (default: the release namespace). GitHub is reached over its API only when a repository's provider is `github`.

## Sensor and job inventory

All sensors have `default_status=STOPPED` and a 10 s minimum interval.

| Name | Kind | Watches / reads | Launches or writes | Defined in |
|---|---|---|---|---|
| `git_pull_request_ingest_sensor` | sensor | trigger repositories, provider pulls | saves `PullRequestTrigger` batch (UNKNOWN) | `sensors/git/__init__.py`, `pr_ingest.py` |
| `git_pull_request_evaluate_sensor` | sensor | UNKNOWN pull requests of enabled projects | `evaluate_repository_pull_requests_job` per repository, unless one is in flight | `sensors/git/pr_evaluate.py` |
| `evaluate_repository_pull_requests_job` | job (max 3 concurrent) | UNKNOWN PRs, spec at merge commit | task (YIELDED), or IGNORED or REJECTED with cause; op retries 3x | `sensors/git/evaluate_job.py` |
| `task_launcher_sensor` | sensor | PENDING tasks of enabled projects | `k8s_pipes_job` run, key `task/<id>/<attempt>`, tag `trigger=task` | `sensors/task/launcher.py` |
| `k8s_pipes_job` | job | task spec and dataset (run config) | task pod, artifacts | `definitions/jobs.py`, `pipes.py` |
| `task_queued_sensor`, `task_started_sensor`, `task_success_sensor`, `task_failure_sensor`, `task_canceled_sensor` | run-status sensors on `k8s_pipes_job` | runs tagged `trigger=task` | `PATCH /tasks/<id>` status, run id, times | `sensors/task/run_status.py` |
| `task_results_delivery_sensor` | run-status sensor (SUCCESS) on `k8s_pipes_job` | succeeded task runs | `deliver_results_job`, key `deliver/<task>/<attempt>`, tags `trigger=delivery`, `delivery_task_id` | `sensors/task/delivery.py` |
| `deliver_results_job` | job (run pod) | artifacts volume, task, results repository | branch, results PR, result PUSHED then OPENED | `delivery/results.py`, `git_push.py` |
| `results_pull_request_sync_sensor` | sensor | results PUSHED or OPENED | `sync_results_pull_requests_job` unless in flight | `sensors/task/pull_request_sync.py` |
| `sync_results_pull_requests_job` | job | provider PR state | result OPENED, MERGED or CLOSED, number, url, merge fields | `sensors/task/pull_request_sync.py` |
| `noop_job` | job | nothing | smoke test of the code location and run launcher | `definitions/jobs.py` |
