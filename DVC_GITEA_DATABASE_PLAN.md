# Results Delivery: Webserver DB Schema Rewrite

## Context

We've been designing a results-delivery feature (DVC_GITEA_RESULTS_PLAN.md / DVC_GITEA_AGENTS_PLAN.md) that lets a project store task results either directly in a Gitea/GitHub git repo (`git` backend) or in S3/Azure/GCP via DVC, with `.dvc` pointers + `metadata.json` committed to git either way. The `dagster/app/definitions/sensors/github/transfer_op.py` op (already written this session) implements that flow and expects `project.results_backend.type`/`.config` and `task.trigger_payload` to exist — none of that exists in the webserver schema yet.

Separately, the existing schema has accumulated drift worth cleaning up while we're touching migrations: `created_at`/`updated_at` are hand-copied into 8 models with two different (inconsistent) conventions, and `delivery_targets`/`task_deliveries` (the old, conflated delivery-target design) are being replaced by the new `results_backends`/`results_repositories` model.

**Investigation turned up an important constraint that shapes this plan's scope:** there is no live "PR → Task" conversion today. The PR trigger flow (`pr_trigger.py`) launches `k8s_pipes_op` directly via a Dagster `RunRequest` and never creates a webserver `Task` row. Status instead lives entirely on `pull_requests.status`, actively written by five wired-and-running Dagster `run_status_sensor`s (`task_queued_sensor` etc. in `dagster/app/definitions/sensors/github/__init__.py`) that PATCH `pull_requests.status` through QUEUED→STARTED→SUCCESS/FAILURE/CANCELLED. Removing those values from `PullRequestStatus` would break that live PATCH validation. Per your direction, **this plan does not touch any dagster files** — it's scoped purely to webserver models/migrations (plus the enum values dagster will read via the API, which we get right by designing them here). Task itself, by contrast, is currently **fully inert** — `POST /tasks` is `raise NotImplementedException()` and nothing anywhere creates a `Task` row — so there's no live-code risk in extending its schema now; actually wiring Task creation + re-pointing the run-status sensors from `PullRequest.status` to `Task.status` is real, separate follow-up work (matches "Human Task 2: Sensor Wiring" in DVC_GITEA_AGENTS_PLAN.md).

**Sequence for this work:** (1) write a schema markdown doc capturing the full target schema, (2) update SQLAlchemy models to match it, (3) delete all existing Alembic migrations and generate one fresh baseline from the updated models.

---

## 1. Schema markdown doc

New file: `DVC_GITEA_DB_SCHEMA.md` (repo root, alongside the existing `DVC_GITEA_RESULTS_PLAN.md` / `DVC_GITEA_AGENTS_PLAN.md`).

Contents:
- Full current schema as a reference baseline (all 13 existing tables, columns, FKs — already gathered from exploration, just needs transcribing)
- **New tables** (full column lists, see §3 below): `results_repositories`, `results_backends`, `api_requests`
- **Updated tables**: `projects` (+ `results_repository_id`, nullable for now), `tasks` (+ `api_request_id`, `git_commit_sha`, `results_path`, `trigger_payload`)
- **Removed tables**: `delivery_targets`, `task_deliveries` (and their model files, enums `DeliveryTargetType`/`HttpAuthScheme`/`DeliveryStatus`)
- FK relationship diagram (text, matching the existing style found in the exploration report)
- `BackendType` enum definition (`git` | `s3` | `azure` | `gcp`) and the config-shape-per-type it implies
- A short explicit **"Not in this pass"** section: `PullRequestStatus`/`TaskStatus` unchanged, no dagster file changes, no Task-creation wiring, no new API routes/CRUD for the new tables (that's the natural next step, but separate from a DB-schema plan)

---

## 2. `SqlaColumn` helper + timestamp standardization

`webserver/app/models/__init__.py` currently only holds the lazy `ModelRegistry`. Add alongside it:

```python
from sqlalchemy import Column, DateTime
from sqlalchemy.sql import func


class SqlaColumn:
    """Factory for standardized column definitions shared across models."""

    def created_at(self, **kwargs) -> Column:
        return Column(DateTime(timezone=False), nullable=False, server_default=func.now(), **kwargs)

    def updated_at(self, **kwargs) -> Column:
        return Column(DateTime(timezone=False), nullable=False, server_default=func.now(), onupdate=func.now(), **kwargs)


sqla_column = SqlaColumn()
```

Each call returns a fresh `Column` (required — SQLAlchemy `Column` objects can't be shared across tables). `server_default=func.now()` is preserved deliberately: `BaseModel.is_field_required()` treats any column with a `server_default` as *not* required in request bodies — dropping it would make `created_at`/`updated_at` suddenly "required" in `Project.validate()` etc.

**Retrofit every model that already has genuine `created_at`/`updated_at` columns** to use `sqla_column.created_at()` / `sqla_column.updated_at()`, and drop the redundant Python-side `self.created_at = datetime.now()` / `self.updated_at = datetime.now()` sets in `__init__` where present (now dead weight now that the DB `server_default` is authoritative):

- `catalogue.py`, `dictionary.py` — also drop the `created_at: datetime = datetime.now()` constructor param (evaluated once at import time, a footgun; the DB default already covers it)
- `dataset.py`, `project.py`, `request.py`, `task.py`
- `trigger_repository.py` — this one currently has the "loose" convention (nullable, no `server_default` on `updated_at`); standardizing brings it in line with the rest (not-null, `server_default` on both)

**Not touched:** `pull_requests.saved_at` and `audit.event_time` are semantically distinct timestamps (not created_at/updated_at), left as-is. `registries`, `whitelisted_images` have no timestamp columns today — not adding any (out of scope, not requested).

---

## 3. New models

### `app/models/results_repository.py`

```python
class ResultsRepository(db.Model, BaseModel):
    __tablename__ = 'results_repositories'

    id = Column(Integer, primary_key=True, autoincrement=True)
    uri = Column(String(4096), unique=True, nullable=False)
    owned_by_federated_node = Column(Boolean, nullable=False, server_default='true')
    created_at = sqla_column.created_at()
    updated_at = sqla_column.updated_at()

    projects = relationship('Project', back_populates='results_repository')
```

### `app/models/results_backend.py`

Follows the `DeliveryTarget` precedent (type enum stored as plain string, JSON config blob) — closest existing pattern in the codebase.

```python
class BackendType(str, Enum):
    GIT = "git"
    S3 = "s3"
    AZURE = "azure"
    GCP = "gcp"

    def __str__(self):
        return self.value


class ResultsBackend(db.Model, BaseModel):
    __tablename__ = 'results_backends'

    id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(Integer, ForeignKey('projects.id', ondelete='CASCADE'), unique=True, nullable=False)
    type = Column(String(16), nullable=False, server_default=BackendType.GIT.value)
    config = Column(JSON, nullable=False, default=dict, server_default='{}')
    created_at = sqla_column.created_at()
    updated_at = sqla_column.updated_at()

    project = relationship('Project', back_populates='results_backend')

    def __init__(self, project_id: int, type: str = BackendType.GIT.value, config: dict | None = None):
        self.project_id = project_id
        self.type = BackendType(type).value  # raises ValueError on invalid type, matching DeliveryTarget.__init__
        self.config = config or {}

    @validates('config')
    def validate_config(self, key, config):
        """Backend-specific required-field check, run at save time (per-type, not a deep schema validator)."""
        if self.type == BackendType.GIT.value:
            return config or {}
        if not config or 'url' not in config:
            raise InvalidDBEntry(f"{self.type} config must include 'url'")
        if self.type == BackendType.S3.value:
            required = ['access_key_id', 'secret_access_key']
        elif self.type == BackendType.AZURE.value:
            if 'account_key' not in config and 'connection_string' not in config:
                raise InvalidDBEntry("azure config must include 'account_key' or 'connection_string'")
            required = []
        elif self.type == BackendType.GCP.value:
            required = ['projectname']
        else:
            raise InvalidDBEntry(f"unknown backend type: {self.type}")
        missing = [f for f in required if f not in config]
        if missing:
            raise InvalidDBEntry(f"{self.type} config missing required fields: {missing}")
        return config
```

`project_id` is `unique=True` — one backend row per project (1:1), simpler than a partial-unique-index "one enabled target" pattern since there's no enabled/disabled toggle needed here.

### `app/models/api_request.py`

```python
class ApiRequest(db.Model, BaseModel):
    __tablename__ = 'api_requests'

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String(256), nullable=False)
    project_id = Column(Integer, ForeignKey('projects.id', ondelete='CASCADE'), nullable=False)
    payload = Column(JSON, nullable=False, default=dict)
    created_at = sqla_column.created_at()

    project = relationship('Project', back_populates='api_requests')
    tasks = relationship('Task', back_populates='api_request')
```

No `updated_at` — like `pull_requests`, this is an immutable record of what was submitted (payload doesn't change after submission; unlike PRs there's no separate spec-fetch step, since the payload arrives whole in the POST body).

**Naming note for the doc:** `api_requests` (new — triggers a task run) is unrelated to the existing `requests` table (Data Access Requests — DAR approval workflow). Flag this explicitly in the schema doc since the names are easy to confuse.

---

## 4. Updated models

### `app/models/project.py`

Add:
```python
results_repository_id = Column(Integer, ForeignKey('results_repositories.id', ondelete='RESTRICT'), nullable=True)
```
Nullable per your call — avoids breaking `POST /projects` (and the `conftest.py` `project` fixture) until Gitea auto-provisioning exists. No circular-FK complexity here (unlike `default_dataset_id`), since `results_repositories` doesn't reference `projects`.

Relationships:
```python
results_repository = relationship('ResultsRepository', back_populates='projects')
results_backend = relationship('ResultsBackend', back_populates='project', uselist=False)
api_requests = relationship('ApiRequest', back_populates='project')
```

### `app/models/task.py`

Add (all nullable — Task is currently unreachable by any live code path, so this is purely additive):
```python
api_request_id = Column(Integer, ForeignKey('api_requests.id', ondelete='SET NULL'), nullable=True)
git_commit_sha = Column(String(40), nullable=True)
results_path = Column(String(512), nullable=True)
trigger_payload = Column(JSON, nullable=True)
```
- `api_request_id` mirrors the existing `pr_repository_id`/`pr_number` composite-FK pattern but for the new trigger type — **distinct from** the existing `request_id` FK (→ `requests`, the DAR table). Don't confuse the two.
- `git_commit_sha` / `results_path` — set after `transfer_op` commits results to the results repo; needed so the API can report "where are my results" without parsing git log.
- `trigger_payload` — the uncommitted `transfer_op.py` already calls `self.backend_api.get_task_by_run_id(...).trigger_payload` expecting this field to exist; it doesn't yet. Adding it here closes that gap. (Populating it — copying `pr.spec` or `api_request.payload` at task-creation time — is part of the Task-creation wiring that's explicitly out of scope for this pass.)

No other `Task` fields are touched. `Task.validate()`, the `__init__` (which currently drops PR/API-trigger kwargs silently since it takes `**kwargs` and ignores it), and the hardcoded `status = 'scheduled'` string (not a valid `TaskStatus` member — a pre-existing inconsistency) are left exactly as-is; noted in the schema doc as a known follow-up, not fixed here.

### Delete entirely

- `app/models/delivery_target.py` (model + `DeliveryTargetType`/`HttpAuthScheme` enums)
- `app/models/task_delivery.py` (model + `DeliveryStatus` enum)
- Remove `DeliveryTarget`/`TaskDelivery` entries from `ModelRegistry` in `app/models/__init__.py`, add `ResultsRepository`/`ResultsBackend`/`ApiRequest` entries in their place (same lazy `cached_property` pattern).
- No webserver route currently exposes `DeliveryTarget`/`TaskDelivery` (`grep` found no `delivery_targets_api.py`/`task_deliveries_api.py`), so no route cleanup needed.

---

## 5. Enums — explicitly unchanged

`PullRequestStatus` (`app/models/pull_request_status.py`) and `TaskStatus`/`TriggerSource` (`app/models/task_status.py`) are **not modified** in this plan, for the reason in Context: the five live `run_status_sensor`s write QUEUED/STARTED/SUCCESS/FAILURE/CANCELLED through `PullRequestStatus` today, and we're not touching dagster. New enum: `BackendType` (git/s3/azure/gcp) per §3, following the existing `str, Enum` + string-column convention (no SQLAlchemy `Enum` type — matches codebase-wide practice).

---

## 6. Migrations

1. Delete all 20 files in `webserver/migrations/versions/`.
2. Update the explicit per-module import list in `webserver/migrations/env.py`: remove `app.models.delivery_target` / `app.models.task_delivery`, add `app.models.results_repository`, `app.models.results_backend`, `app.models.api_request`.
3. Generate one fresh migration off the updated models: `alembic revision --autogenerate -m "baseline"` (or hand-write mirroring `03cbb166eec1_init.py`'s style) with `down_revision = None` — this becomes the new sole baseline.
4. Sanity-check the autogenerated diff against the schema doc from §1 before treating it as final (autogenerate sometimes misses server-side details like partial indexes — there are none of those left after removing `delivery_targets`, but worth a manual read-through).

This assumes no existing deployed database needs its data/history preserved — confirm that's still true for whatever environments run this webserver today before applying.

---

## 7. Test fixtures

`webserver/tests/conftest.py` — no changes strictly required since `results_repository_id` stays nullable (the `project` fixture's `Project(name="TestProject"); project.add()` keeps working as-is). If later work makes it non-nullable, the fixture will need a `ResultsRepository` created first.

---

## Explicitly out of scope for this plan

- Any dagster file changes (sensor wiring, Task creation on PR/API trigger, re-pointing `run_status_sensor`s to `Task.status`)
- New/updated API routes for `results_repositories`/`results_backends`/`api_requests` (CRUD, Gitea auto-provisioning on project create)
- Redesigning `PullRequestStatus`/`TaskStatus` (e.g. splitting job-lifecycle out into a separate column) — flagged as a real open question but blocked on the "no dagster changes yet" constraint, since the live sensors write through the current enum via the generic PATCH endpoint
- Fixing the `Task.status` hardcoded `'scheduled'` literal or the `__init__`'s silently-dropped `**kwargs`

---

## Verification

1. `cd webserver && alembic upgrade head` against a fresh dev DB — confirms the single new baseline applies cleanly.
2. `alembic downgrade base` then `alembic upgrade head` again — confirms round-trip works (only one revision, but still worth checking `downgrade()` is implemented correctly).
3. `pytest webserver/tests` — since tests use `db.create_all()`/`db.drop_all()` from the models directly (not via Alembic), this validates the model definitions independently of the migration; existing fixtures should pass unchanged.
4. Manually diff the schema doc (§1) against `python -c "from app.helpers.base_model import Base; ..."` introspection or the autogenerated migration, table by table, to catch anything autogenerate missed.
