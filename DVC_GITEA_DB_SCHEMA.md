# DVC/Gitea Results Delivery Database Schema

**Version:** Baseline  
**Last Updated:** 2026-09-25  
**Scope:** Webserver models supporting results delivery and trigger management

---

## Overview

This document captures the **complete target database schema** for the PHEMS webserver after implementing results-delivery infrastructure (git + DVC backends) and results repository management. The baseline consolidates 15 existing tables (removing legacy `delivery_targets`/`task_deliveries`) with 3 new tables (`results_repositories`, `results_backends`, `api_requests`), and extends 2 tables (`projects`, `tasks`) with new fields.

---

## Existing Tables (13 total)

### Core Domain

#### `projects`
Owner/project hierarchy. Projects scope datasets, repositories, tasks, and delivery configuration.

| Column | Type | Nullable | Default / Constraint |
|--------|------|----------|----------------------|
| id | Integer | No | PK, autoincrement |
| name | String(256) | No | UNIQUE |
| description | String(4096) | Yes | — |
| default_dataset_id | Integer | Yes | FK→datasets.id RESTRICT (deferred, circular) |
| results_repository_id | Integer | Yes | FK→results_repositories.id RESTRICT (**NEW**) |
| created_at | DateTime | No | server_default=now() |
| updated_at | DateTime | No | server_default=now(), onupdate=now() |

**Relationships:**
- `datasets` (1:N) — cascade
- `default_dataset` (1:1 deferred)
- `requests` (1:N) — back_populates
- `trigger_repositories` (1:N) — back_populates
- `whitelisted_images` (1:N) — cascade
- `delivery_targets` (1:N) — **DELETED**
- `results_repository` (1:1) — back_populates (**NEW**)
- `results_backend` (1:1, uselist=False) — back_populates (**NEW**)
- `api_requests` (1:N) — back_populates (**NEW**)

---

#### `datasets`
Database connection metadata. Projects have one default dataset for task runs; tasks can override via tags.

| Column | Type | Nullable | Default / Constraint |
|--------|------|----------|----------------------|
| id | Integer | No | PK, autoincrement |
| name | String(256) | No | UNIQUE |
| host | String(256) | No | — |
| port | Integer | No | default=5432 |
| schema | String(256) | Yes | — |
| schema_write | String(256) | Yes | — |
| type | String(256) | No | server_default='postgres' |
| extra_connection_args | String(4096) | Yes | — |
| project_id | Integer | No | FK→projects.id RESTRICT |
| created_at | DateTime | No | server_default=now() |
| updated_at | DateTime | No | server_default=now(), onupdate=now() |

**Relationships:**
- `project` (1:N reverse) — back_populates
- `catalogues` (1:N) — cascade
- `dictionaries` (1:N) — cascade
- `requests` (1:N) — back_populates (through requests.dataset_id)

---

#### `tasks`
Individual task runs. Created via PR trigger (inert today, not wired) or API submit (not yet implemented).

| Column | Type | Nullable | Default / Constraint |
|--------|------|----------|----------------------|
| id | Integer | No | PK, autoincrement |
| name | String(256) | No | — |
| docker_image | String(256) | No | — |
| description | String(4096) | Yes | — |
| status | String(256) | No | default='scheduled' |
| requested_by | String(256) | No | — |
| review_status | Boolean | Yes | — |
| dataset_id | Integer | Yes | FK→datasets.id CASCADE |
| project_id | Integer | No | FK→projects.id RESTRICT, indexed |
| trigger_source | String(16) | No | server_default=TriggerSource.API.value |
| pr_repository_id | Integer | Yes | — (composite FK, see below) |
| pr_number | Integer | Yes | — (composite FK, see below) |
| request_id | Integer | Yes | FK→requests.id SET NULL |
| dagster_run_id | String(64) | Yes | UNIQUE |
| started_at | DateTime | Yes | — |
| completed_at | DateTime | Yes | — |
| exit_code | Integer | Yes | — |
| reason | String(256) | Yes | — |
| artifact_key | String(512) | Yes | — |
| params | JSON | No | server_default='{}' |
| reviewed_by | String(256) | Yes | — |
| reviewed_at | DateTime | Yes | — |
| api_request_id | Integer | Yes | FK→api_requests.id SET NULL (**NEW**) |
| git_commit_sha | String(40) | Yes | (**NEW**) |
| results_path | String(512) | Yes | (**NEW**) |
| trigger_payload | JSON | Yes | (**NEW**) |
| created_at | DateTime | No | server_default=now() |
| updated_at | DateTime | No | server_default=now(), onupdate=now() |

**Constraints:**
- FK composite: (pr_repository_id, pr_number) → (pull_requests.trigger_repository_id, pull_requests.number), SET NULL
- CHECK: (pr_repository_id IS NULL) = (pr_number IS NULL) — both or neither

**Indexes:**
- ix_tasks_dataset_status: (dataset_id, status)
- ix_tasks_requested_by: (requested_by)
- ix_tasks_trigger_source_status: (trigger_source, status)
- ix_tasks_pull_request: (pr_repository_id, pr_number)

**Relationships:**
- `dataset` (1:N reverse)
- `project` (1:N reverse)
- `request` (0:1, back_populates)
- `api_request` (0:1, back_populates) — **NEW**

---

#### `trigger_repositories`
GitHub/Gitea repositories watched for pull requests.

| Column | Type | Nullable | Default / Constraint |
|--------|------|----------|----------------------|
| id | Integer | No | PK, autoincrement |
| uri | String(4096) | No | UNIQUE, validated (strip schema) |
| watch_dir | String(4096) | No | — |
| base_branch | String(256) | No | default='main' |
| project_id | Integer | No | FK→projects.id RESTRICT |
| initial_cursor | DateTime | No | server_default=now() |
| created_at | DateTime | Yes | server_default=now() |
| updated_at | DateTime | Yes | onupdate=func.now() |

**Relationships:**
- `project` (1:N reverse) — back_populates
- `pull_requests` (1:N, cascade) — back_populates

---

#### `pull_requests`
Merged pull requests. Lifecycle: UNKNOWN → (IGNORED|INVALID|READY) → (QUEUED|STARTED|SUCCESS|FAILURE|CANCELLED). Job-lifecycle states written by Dagster run_status_sensors.

| Column | Type | Nullable | Default / Constraint |
|--------|------|----------|----------------------|
| trigger_repository_id | Integer | No | PK, FK→trigger_repositories.id CASCADE |
| number | Integer | No | PK (composite with repo_id) |
| title | String(256) | No | — |
| raised_by | String(256) | No | — |
| merged_at | DateTime | No | validated (ISO 8601) |
| saved_at | DateTime | Yes | server_default=now() |
| merge_commit_sha | String(40) | No | — |
| spec | JSON | No | default={} |
| status | String(32) | No | default=UNKNOWN, server_default=UNKNOWN.value |

**Relationships:**
- `trigger_repository` (N:1) — back_populates

---

#### `requests` (Data Access Requests, DAR)
Project access approvals. Unrelated to `api_requests` (new).

| Column | Type | Nullable | Default / Constraint |
|--------|------|----------|----------------------|
| id | Integer | No | PK, autoincrement |
| title | String(256) | No | — |
| description | String(4096) | Yes | — |
| requested_by | String(256) | No | — |
| project_name | String(256) | No | — |
| status | String(256) | No | default='pending' |
| proj_start | DateTime | No | — |
| proj_end | DateTime | No | — |
| dataset_id | Integer | Yes | FK→datasets.id CASCADE |
| project_id | Integer | Yes | FK→projects.id RESTRICT (backfilled, nullable) |
| created_at | DateTime | No | server_default=now() |
| updated_at | DateTime | No | server_default=now(), onupdate=now() |

**Relationships:**
- `dataset` (1:N reverse)
- `project` (1:N reverse) — back_populates

---

#### `catalogues`
Data catalog metadata per dataset.

| Column | Type | Nullable | Default / Constraint |
|--------|------|----------|----------------------|
| id | Integer | No | PK, autoincrement |
| title | String(256) | No | — |
| version | String(256) | Yes | default='1' |
| description | String(4096) | No | — |
| dataset_id | Integer | Yes | FK→datasets.id CASCADE |
| created_at | DateTime | No | server_default=now() |
| updated_at | DateTime | No | server_default=now(), onupdate=now() |

**Constraints:** UNIQUE(title, dataset_id)

**Relationships:**
- `dataset` (1:N reverse)

---

#### `dictionaries`
Data dictionary entries (field-level metadata).

| Column | Type | Nullable | Default / Constraint |
|--------|------|----------|----------------------|
| id | Integer | No | PK, autoincrement |
| table_name | String(256) | No | — |
| field_name | String(256) | No | — |
| label | String(256) | Yes | default='' |
| description | String(4096) | No | — |
| dataset_id | Integer | Yes | FK→datasets.id CASCADE |
| created_at | DateTime | No | server_default=now() |
| updated_at | DateTime | No | server_default=now(), onupdate=now() |

**Constraints:** UNIQUE(table_name, dataset_id, field_name)

**Relationships:**
- `dataset` (1:N reverse)

---

#### `registries`
Container image registries (public/private).

| Column | Type | Nullable | Default / Constraint |
|--------|------|----------|----------------------|
| id | Integer | No | PK, autoincrement |
| url | String(256) | No | — |
| needs_auth | Boolean | No | default=True |
| active | Boolean | No | default=True |

**Relationships:**
- `whitelisted_images` (1:N) — cascade

---

#### `whitelisted_images`
Per-project container image allowlist.

| Column | Type | Nullable | Default / Constraint |
|--------|------|----------|----------------------|
| id | Integer | No | PK, autoincrement |
| name | String(256) | No | — |
| tag | String(256) | Yes | — |
| sha | String(256) | Yes | — |
| registry_id | Integer | Yes | FK→registries.id CASCADE |
| project_id | Integer | No | FK→projects.id CASCADE |

**Relationships:**
- `registry` (1:N reverse)
- `project` (1:N reverse) — back_populates

---

#### `audit`
API request audit trail.

| Column | Type | Nullable | Default / Constraint |
|--------|------|----------|----------------------|
| id | Integer | No | PK, autoincrement |
| ip_address | String(256) | No | — |
| http_method | String(256) | No | — |
| endpoint | String(256) | No | — |
| requested_by | String(256) | No | — |
| status_code | Integer | Yes | — |
| api_function | String(256) | Yes | — |
| details | String(4096) | Yes | — |
| event_time | DateTime | Yes | server_default=now() |

---

## New Tables (3 total)

### Results Infrastructure

#### `results_repositories`
Git repositories where task results are stored. Managed by the federated node or externally.

| Column | Type | Nullable | Default / Constraint |
|--------|------|----------|----------------------|
| id | Integer | No | PK, autoincrement |
| uri | String(4096) | No | UNIQUE (repo URL) |
| owned_by_federated_node | Boolean | No | server_default='true' |
| created_at | DateTime | No | server_default=now() |
| updated_at | DateTime | No | server_default=now(), onupdate=now() |

**Relationships:**
- `projects` (1:N) — back_populates

---

#### `results_backends`
Backend configuration for task result storage: git (direct commit) or cloud (S3/Azure/GCP via DVC).

| Column | Type | Nullable | Default / Constraint |
|--------|------|----------|----------------------|
| id | Integer | No | PK, autoincrement |
| project_id | Integer | No | FK→projects.id CASCADE, **UNIQUE** (1:1) |
| type | String(16) | No | server_default='git', enum: git\|s3\|azure\|gcp |
| config | JSON | No | server_default='{}', validated per type |
| created_at | DateTime | No | server_default=now() |
| updated_at | DateTime | No | server_default=now(), onupdate=now() |

**Enum:** `BackendType` — git, s3, azure, gcp (str.Enum, stored as string)

**Config validation (at save time):**
- **git:** no required fields (config optional)
- **s3:** url (required), access_key_id (required), secret_access_key (required)
- **azure:** url (required), account_key OR connection_string (one required)
- **gcp:** url (required), projectname (required)

**Relationships:**
- `project` (1:1) — back_populates

---

#### `api_requests`
API-submitted task trigger payloads. Immutable record; populates tasks.trigger_payload and task.api_request_id.

| Column | Type | Nullable | Default / Constraint |
|--------|------|----------|----------------------|
| id | Integer | No | PK, autoincrement |
| user_id | String(256) | No | — |
| project_id | Integer | No | FK→projects.id CASCADE |
| payload | JSON | No | server_default='{}' |
| created_at | DateTime | No | server_default=now() |

**Relationships:**
- `project` (1:N) — back_populates
- `tasks` (1:N) — back_populates

**Note:** `api_requests` (new, triggers task) is unrelated to `requests` table (DAR approvals). Distinct purposes despite similar names.

---

## Removed Tables (2 total)

These tables and their associated enums are **deleted** in this baseline; no data migration path exists (legacy, unused in live code).

- **`delivery_targets`** (table) — legacy results delivery configuration
  - **`DeliveryTargetType`** enum (github, http, azcopy) — no longer used
  - **`HttpAuthScheme`** enum (Bearer, Basic) — no longer used
- **`task_deliveries`** (table) — legacy delivery attempts
  - **`DeliveryStatus`** enum (PENDING, RUNNING, SUCCESS, FAILURE) — no longer used

---

## Enums (Unchanged from Existing)

These enums are **not modified** by this baseline and continue to be used by live Dagster sensors.

### `PullRequestStatus` (app/models/pull_request_status.py)
PR processing lifecycle + job lifecycle:
- UNKNOWN, IGNORED, INVALID, READY (sensor processing states)
- QUEUED, STARTED, SUCCESS, FAILURE, CANCELLED (job states — written by run_status_sensors)

### `TaskStatus` (app/models/task_status.py)
Task run states (currently unused; Task.status is a hardcoded string 'scheduled').

### `TriggerSource` (app/models/task_status.py)
Task origin: API or GitHub PR.

### `BackendType` (app/models/results_backend.py) — **NEW**
Results storage backend type: git, s3, azure, gcp.

---

## Foreign Key Relationships Diagram

```
projects
  ├── datasets (1:N)
  ├── requests (1:N via requests.project_id)
  ├── trigger_repositories (1:N)
  ├── whitelisted_images (1:N)
  ├── results_repository (1:1 nullable, RESTRICT)
  ├── results_backend (1:1, CASCADE)
  └── api_requests (1:N)

datasets
  ├── catalogues (1:N)
  ├── dictionaries (1:N)
  └── requests (1:N)

trigger_repositories
  └── pull_requests (1:N, CASCADE)

pull_requests
  └── (composite FK back to tasks via pr_repository_id, pr_number)

tasks
  ├── dataset (N:1)
  ├── project (N:1)
  ├── request (0:1 via request_id)
  └── api_request (0:1 via api_request_id) — NEW

results_repositories
  └── projects (1:N reverse)

results_backends
  └── project (1:1)

api_requests
  ├── project (N:1)
  └── tasks (1:N)

registries
  └── whitelisted_images (1:N)

whitelisted_images
  ├── registry (N:1)
  └── project (N:1)

audit
  (no relationships — immutable log)
```

---

## Not in This Baseline

- **Dagster file changes:** PullRequestStatus values remain unchanged; no sensor rewiring
- **New API routes:** CRUD for results_repositories/results_backends/api_requests deferred (scaffold the models only)
- **Task creation wiring:** PR→Task conversion, API trigger→Task creation remain unimplemented
- **TaskStatus redesign:** No restructuring of the Task.status column or enum split (follow-up work)
- **Task.__init__ cleanup:** Hardcoded 'scheduled' status and **kwargs silent drop remain as-is

---

## Migration Strategy

All 20 existing migration files in `webserver/migrations/versions/` are deleted. A single fresh baseline migration is generated from the updated models, with `down_revision = None`. This assumes no production database history needs preservation.

**Migration flow:**
1. Delete all 20 versions/*.py files
2. Update env.py imports: remove delivery_target/task_delivery, add results_repository/results_backend/api_request
3. `alembic revision --autogenerate -m "baseline"` with down_revision = None
4. Verify autogenerated schema matches this doc
5. `alembic upgrade head` on a fresh dev DB

---

## Verification Checklist

- [ ] All 13 existing tables present with correct columns/constraints
- [ ] 3 new tables created with FK relationships wired
- [ ] `projects.results_repository_id` nullable (RESTRICT on deletion)
- [ ] `tasks` new fields nullable (api_request_id SET NULL, git_commit_sha, results_path, trigger_payload)
- [ ] 2 tables (delivery_targets, task_deliveries) and their enums removed
- [ ] ResultsBackend.config validation logic in place
- [ ] PullRequestStatus/TaskStatus enums unchanged
- [ ] alembic upgrade/downgrade round-trip works
- [ ] pytest webserver/tests passes with db.create_all()
- [ ] No dagster files touched
