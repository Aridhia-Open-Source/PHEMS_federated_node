# Entities and state machines

The final backend schema (`webserver/migrations/versions/001_baseline.py`), the two inheritance trees, and the three state machines. Decisions: [0001](../../project/decisions/0001-polymorphic-triggers.md), [0003](../../project/decisions/0003-project-scoped-git-repositories.md), [0008](../../project/decisions/0008-polymorphic-result-and-forward-only-state.md), [0009](../../project/decisions/0009-sync-reconciler-and-operational-rules.md), [0017](../../project/decisions/0017-task-status-written-by-run-status-sensors.md).

Not drawn: `audit`, `registries`, `whitelisted_images`, `catalogues`, `dictionaries`, `dars` (disconnected, [0014](../../project/decisions/0014-dar-rename-and-detached-auth.md)) and `results_backends` (present in the baseline, unused by the pipeline).

## Schema

```mermaid
erDiagram
    projects {
        int id PK
        string name UK
        bool enabled
        int default_dataset_id FK
    }
    secrets {
        int id PK
        int project_id FK
        string label "unique per project"
        enum provider "K8S"
        string key UK "name in the store"
        string namespace
    }
    datasets {
        int id PK
        int project_id FK
        int secret_id FK
        string name UK
        string host
        string type
    }
    trigger_repositories {
        int id PK
        int project_id FK
        int secret_id FK
        string uri "unique per project"
        string provider
        string api_uri
        string watch_dir
        string base_branch
        datetime initial_cursor
    }
    results_repositories {
        int id PK
        int project_id FK "unique, one per project"
        int secret_id FK
        string uri
        string provider
        string api_uri
        string target_dir
        bool owned_by_federated_node
    }
    triggers {
        int id PK
        string type "PR or API"
        int project_id FK
        string state "UNKNOWN YIELDED IGNORED REJECTED"
        string state_cause "set only for IGNORED and REJECTED"
    }
    pull_request_triggers {
        int trigger_id PK, FK
        int trigger_repository_id FK
        int number "unique with repository"
        string title
        string raised_by
        string merge_commit_sha
        datetime merged_at
        json payload
    }
    api_request_triggers {
        int trigger_id PK, FK
        string user_id
        json payload
    }
    tasks {
        int id PK
        int project_id FK
        int trigger_id FK, UK "one task per trigger"
        int dataset_id FK
        string name
        string docker_image
        string status
        int attempt
        string requested_by
        string dagster_run_id UK
        datetime started_at
        datetime completed_at
        int exit_code
        json spec
        json params
    }
    results {
        int id PK
        string type "PR"
        int task_id FK
        int results_repository_id FK
        int attempts
        string error
    }
    pull_request_results {
        int result_id PK, FK
        string state "UNKNOWN PUSHED OPENED MERGED CLOSED"
        string branch
        string commit_sha
        int number
        string url
        datetime merged_at
        string merge_commit_sha
    }

    projects ||--o{ secrets : owns
    projects ||--o{ datasets : owns
    projects ||--o{ trigger_repositories : owns
    projects ||--o| results_repositories : "has one"
    projects ||--o{ triggers : "scopes"
    projects ||--o{ tasks : "scopes"
    secrets ||--o{ datasets : "credentials of"
    secrets ||--o{ trigger_repositories : "token of"
    secrets ||--o{ results_repositories : "token of"
    trigger_repositories ||--o{ pull_request_triggers : "watched PRs"
    triggers ||--o| pull_request_triggers : "is a"
    triggers ||--o| api_request_triggers : "is a"
    triggers ||--o| tasks : "yields"
    datasets |o--o{ tasks : "runs on"
    tasks ||--o{ results : "delivered as"
    results_repositories ||--o{ results : "receives"
    results ||--o| pull_request_results : "is a"
```

Composite foreign keys `(project_id, secret_id)` on `datasets`, `trigger_repositories` and `results_repositories` tie each to a secret of its own project. A `results` row is unique per `(task_id, results_repository_id)`. `projects.default_dataset_id` closes a cycle with `datasets` and is added last in the migration.

## Inheritance trees

```mermaid
classDiagram
    class Trigger {
        +int id
        +string type
        +int project_id
        +string state
        +string state_cause
        +set_state(state, state_cause)
        +requested_by()
        +task_id()
    }
    class PullRequestTrigger {
        +int trigger_repository_id
        +int number
        +string title
        +string raised_by
        +string merge_commit_sha
        +datetime merged_at
        +dict payload
    }
    class ApiRequestTrigger {
        +string user_id
        +dict payload
    }
    Trigger <|-- PullRequestTrigger : type PR
    Trigger <|-- ApiRequestTrigger : type API

    class Result {
        +int id
        +string type
        +int task_id
        +int results_repository_id
        +int attempts
        +string error
    }
    class PullRequestResult {
        +string state
        +string branch
        +string commit_sha
        +int number
        +string url
        +datetime merged_at
        +string merge_commit_sha
        +set_state(state)
    }
    Result <|-- PullRequestResult : type PR
```

`state` is on the `Trigger` parent (the verdict is the same for any kind) but on the `PullRequestResult` child (the delivery lifecycle belongs to the delivery kind), see [0008](../../project/decisions/0008-polymorphic-result-and-forward-only-state.md). The trigger side is the merged pull request we watch; the result side is the pull request we open.

## Trigger state

```mermaid
stateDiagram-v2
    [*] --> UNKNOWN : ingest sensor records a merged PR
    UNKNOWN --> YIELDED : valid spec, task created in the same transaction
    UNKNOWN --> IGNORED : no new .json under watch_dir (state_cause)
    UNKNOWN --> REJECTED : several files, invalid spec, or backend 400 (state_cause)
    YIELDED --> [*]
    IGNORED --> [*]
    REJECTED --> [*]
```

`state_cause` is required for `IGNORED` and `REJECTED` and forbidden otherwise (check constraint and `set_state`). An `ApiRequestTrigger` is validated inside `POST /tasks`: it is recorded `REJECTED` (with the cause) when invalid, else `YIELDED` with its task, and is never `UNKNOWN` for long.

## Task status

```mermaid
stateDiagram-v2
    [*] --> PENDING : task created
    PENDING --> QUEUED : run queued
    QUEUED --> RUNNING : run started
    PENDING --> RUNNING : run started (queued event skipped)
    RUNNING --> SUCCESS : run succeeded
    RUNNING --> FAILED : run failed
    QUEUED --> CANCELED : run canceled
    RUNNING --> CANCELED : run canceled
    FAILED --> PENDING : POST /tasks/id/retry, attempt + 1
    CANCELED --> PENDING : POST /tasks/id/retry, attempt + 1
    SUCCESS --> [*]
```

Only the run-status sensors write the status; the backend does not enforce the order. Delivery never changes it ([0017](../../project/decisions/0017-task-status-written-by-run-status-sensors.md)).

## PullRequestResult state

```mermaid
stateDiagram-v2
    [*] --> UNKNOWN : POST /results (idempotent)
    UNKNOWN --> PUSHED : branch pushed (delivery job)
    PUSHED --> OPENED : results PR opened (delivery job)
    PUSHED --> OPENED : PR found by branch (sync sensor)
    OPENED --> MERGED : PR merged (sync sensor)
    OPENED --> CLOSED : PR closed unmerged (sync sensor)
    PUSHED --> MERGED : delivery found its PR already merged
    PUSHED --> CLOSED : delivery found its PR already closed
    MERGED --> [*]
    CLOSED --> [*]
```

Forward only: `UNKNOWN < PUSHED < OPENED < MERGED = CLOSED`. A PATCH to the same state is accepted; to an earlier state, or out of `MERGED`/`CLOSED`, is a 400. A failed delivery leaves the state and sets `error` and `attempts`.
