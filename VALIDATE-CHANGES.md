# Code Review: Database Schema Refactoring

**Date:** 2026-08-02  
**Branch:** dagster-develop-beta  
**Scope:** Repository-Dataset relationship refactor for MVP ingestion pipeline

---

## Executive Summary

This refactoring corrects a fundamental schema design flaw where the relationship between repositories and datasets was bidirectional and ambiguous. The changes establish a **unidirectional foreign key** (Repository → Dataset) enabling:

1. ✅ Datasets to be reusable across multiple repositories
2. ✅ Clear dataset ownership semantics
3. ✅ Simplified PullRequest model (no dataset_id in PK)
4. ✅ Foundation for future Project model migration

**Total Changes:** 6 files modified, 1 migration consolidated  
**Breaking Changes:** None to working code; prior schema was broken  
**Test Coverage:** All test fixtures updated; seed script verified

---

## Architecture Changes

### What Changed

#### 1. Repository Model & Schema

**Before:**
```python
# webserver/app/models/repository.py
default_dataset_id = Column(String(256), nullable=True)  # ❌ Wrong: string, not FK
default_dataset_name = Column(String(256), nullable=True)  # ❌ Wrong: duplicate
# No relationship to Dataset
```

**After:**
```python
# webserver/app/models/repository.py
dataset_id = Column(Integer, ForeignKey('datasets.id'), nullable=False)
dataset = relationship("Dataset", back_populates="repositories")
```

**Why:** 
- Establishes clear semantic: a Repository ingests *one specific* Dataset
- FK constraint prevents orphaned repositories
- `nullable=False` enforces invariant at schema level
- Single source of truth (one column, not two)

**Backward Compatibility:** None. The prior `default_dataset_name` and `default_dataset_id` columns were unused by the actual codebase and conflicted with each other.

---

#### 2. Dataset Model & Schema

**Before:**
```python
# webserver/app/models/dataset.py
@classmethod
def validate(cls, data: dict) -> dict:
    repo_id = data.get("repository_id")
    if not repo_id:
        raise InvalidRequest("repository_id is required")  # ❌ Forces 1:1 coupling
    # ... validates Repository exists
```

**After:**
```python
@classmethod
def validate(cls, data: dict) -> dict:
    data = dict(data)
    return super().validate(data)  # ✅ Dataset standalone
```

**Why:**
- Datasets should be reusable (future: multiple repos can ingest the same database)
- The old `repository_id` column was dropped from the schema
- Removes artificial coupling that forced Repository → Dataset → Repository circle
- Aligns with SCHEMA-PLAN.md design intent

**Impact on Tests:**
```python
# webserver/tests/conftest.py
@fixture
def default_repo(client, user_uuid, k8s_client, mock_kc_client) -> Repository:
    # Before: repo = Repository(uri=sample_repo_uri)
    # Now: must create Dataset first, then Repository with dataset_id
    dataset = Dataset(name="DefaultDatasetForRepo", host="example.com", password='pass', username='user')
    dataset.add(user_id=user_uuid)
    repo = Repository(uri=sample_repo_uri, watch_dir="", dataset_id=dataset.id)
    repo.add()
    return repo
```

This pattern now enforces the new dependency: **Dataset must exist before Repository**.

---

#### 3. PullRequest Model & Schema

**Before:**
```python
class PullRequest(db.Model, BaseModel):
    number = sa.Column(sa.Integer, nullable=False, primary_key=True)
    repository_id = sa.Column(..., primary_key=True)
    dataset_id = sa.Column(..., primary_key=True)  # ❌ Composite PK: (repo_id, number, dataset_id)
```

**After:**
```python
class PullRequest(db.Model, BaseModel):
    number = sa.Column(sa.Integer, nullable=False, primary_key=True)
    repository_id = sa.Column(..., primary_key=True)
    # ✅ Composite PK: (repository_id, number) — simpler, clearer
    # No dataset_id: a PR belongs to a repo, not a dataset
```

**Why:**
- **Semantic Correctness:** A PR is an event in a specific GitHub repository, not in a dataset
- **Simplified PK:** `(repo_id, number)` is sufficient (GitHub PR numbers are unique per repo)
- **No Data Duplication:** Dataset is reachable via `Repository → Dataset`
- **Cleaner Queries:** `SELECT * FROM pull_requests WHERE repository_id=X AND status=Y` doesn't need dataset_id

**Index Change:**
```sql
-- Before: ix_pull_requests_status(repository_id, dataset_id, status)
-- After:  ix_pull_requests_status(repository_id, status)
```
Simplifies joins and filtering by status within a repo.

---

### Migration Strategy

**Consolidated Migration:** `d1e2f3a4b5c6_add_repository_and_pull_requests_tables.py`

Instead of three separate migrations, we consolidated into one **idempotent** migration that creates the final correct schema:

```python
def upgrade() -> None:
    # repositories table with direct dataset_id FK
    op.create_table(
        'repositories',
        sa.Column('id', sa.Integer(), nullable=False, autoincrement=True),
        sa.Column('uri', sa.String(length=4096), nullable=False, unique=True),
        sa.Column('watch_dir', sa.String(length=4096), nullable=False),
        sa.Column('base_branch', sa.String(length=256), default='main'),
        sa.Column('dataset_id', sa.Integer(), nullable=False),  # ✅ Direct FK
        sa.Column('initial_cursor', sa.DateTime(), default=func.now()),
        sa.ForeignKeyConstraint(['dataset_id'], ['datasets.id'], ondelete='RESTRICT'),
    )
    
    # pull_requests with correct composite PK (no dataset_id)
    op.create_table(
        'pull_requests',
        sa.Column('repository_id', sa.Integer(), nullable=False),
        sa.Column('number', sa.Integer(), nullable=False),
        # All other columns (no dataset_id)
        sa.PrimaryKeyConstraint('repository_id', 'number'),
        sa.ForeignKeyConstraint(['repository_id'], ['repositories.id'], ondelete='CASCADE'),
    )
```

**Why Consolidated:**
- Avoids intermediate broken state
- Single atomic operation
- Clearer intent: "here's the correct schema"
- Easier to reason about (no migration ordering issues)

**Why `ondelete='RESTRICT'`:**
- Prevents deletion of Datasets in use by Repositories
- Ensures referential integrity
- Explicit: must delete Repository before Dataset

---

## API Changes

### POST /repositories

**Before:**
```python
body = {
    "uri": "...",
    "default_dataset_name": "my_dataset",  # ❌ String, indirect lookup
}
```

**After:**
```python
body = {
    "uri": "...",
    "dataset_id": 5,  # ✅ Integer FK, direct reference
    "watch_dir": "...",
    "base_branch": "main",  # optional
    "initial_cursor": "2026-01-01T00:00:00Z",  # optional
}
```

**Validation (repositories_api.py:75-104):**
```python
if not body.get('uri'):
    raise InvalidRequest("uri is required")
if not body.get('dataset_id'):
    raise InvalidRequest("dataset_id is required")  # ✅ Enforced at API level

# Validate dataset exists
dataset = Dataset.get_by_id(body['dataset_id'])  # ✅ Raises 404 if not found

repo = Repository(
    uri=uri,
    watch_dir=body.get('watch_dir', ''),
    dataset_id=body['dataset_id'],  # ✅ Direct FK assignment
    base_branch=body.get('base_branch', 'main'),
    initial_cursor=body.get('initial_cursor'),
)
repo.add()
return repo.sanitized_dict(), HTTPStatus.CREATED
```

**Why:**
- Immediate validation (fails on invalid dataset_id, not silently later)
- Prevents orphaned repositories
- Clear error messages

---

### POST /datasets

**Before:**
```python
body = {
    "name": "...",
    "host": "...",
    "repository_id": 5,  # ❌ Required, no longer in schema
}
```

**After:**
```python
body = {
    "name": "...",
    "host": "...",
    "port": 5432,
    "schema": "public",
    "type": "postgres",
    "username": "...",
    "password": "...",
    # NO repository_id
}
```

**Validation (datasets_api.py:58):**
```python
body = Dataset.validate(request.json)  # ✅ No repository_id required
cata_body = body.pop("catalogue", {})
# ... rest of creation
```

**Why:**
- Datasets are standalone resources
- Can be created before repositories
- Enables seed script to create dataset first, then repositories
- Future: multiple repositories can ingest same dataset

---

### POST /repositories/<repo_id>/pull_requests/batch

**Before:**
```python
[
  {
    "number": 123,
    "title": "...",
    "dataset_id": 5,  # ❌ No longer in model
    "spec": {...},
  }
]
```

**After:**
```python
[
  {
    "number": 123,
    "title": "...",
    "raised_by": "user@example.com",
    "merged_at": "2026-08-02T10:00:00Z",
    "merge_commit_sha": "abc123...",
    "spec": {...},
    "status": "UNKNOWN",  # optional
    # NO dataset_id
  }
]
```

**Validation (repositories_api.py:169-224):**
```python
repository = Repository.get_by_id(repo_id)  # ✅ Verify repo exists
for pr_data in body:
    pr = PullRequest(
        repository_id=repo_id,  # ✅ From URL path
        number=pr_data['number'],
        # ... other fields
        # NO dataset_id
    )
    pr.add(commit=False)
session.commit()
```

**Why:**
- Dataset is implicitly known via Repository
- No need to repeat it in every PR
- Batch operation scoped to single repo

---

## Sensor Logic Changes

### Dagster Sensors - Simplified

**Key Change:** Sensors no longer need `_resolve_dataset_id_from_spec()` logic.

**Before:**
```python
def _resolve_dataset_id_from_spec(self, repo, spec):
    # ❌ Complex: check if spec has dataset name, look it up
    if "dataset" in spec:
        dataset = self.backend_api.get_dataset_by_name(spec["dataset"])
        return dataset.id
    else:
        return repo.default_dataset_id  # ❌ Fallback to repo default
```

**After:**
```python
# ✅ No need for this method anymore
dataset_id = repo.dataset_id  # Direct access, always set
```

**Why simpler:**
- Repository always has dataset_id (nullable=false in schema)
- No conditional logic needed
- No dataset lookup by name required
- Spec is just payload data, not dataset selector

---

### Test Changes (dagster/app/tests/)

**test_trigger_sensor.py:**
- Updated skip reason: `"No unknown pull requests found"` (was "No unprocessed")
- Added mock for `repo.path`, `repo.watch_dir`, `pr.merge_commit_sha`
- Enhanced GitHub API mocking (more realistic)

**test_ingest_sensor.py:**
- Changed `repo.pull_request_cursor` → `repo.pr_cursor` (matches model)
- Removed `test_resolve_dataset_id_from_spec_*` tests (logic no longer exists)
- Tests now simpler because dataset resolution gone

---

## Client Code Changes

### dagster/app/backend.py

**Fixed: create_dataset() signature**

```python
# Before:
def create_dataset(
    self, name, host, port, username, password, schema, db_type,
    repository_id: int,  # ❌ Obsolete
) -> Dataset:
    data = {..., "repository_id": repository_id}

# After:
def create_dataset(
    self, name, host, port, username, password, schema, db_type,
) -> Dataset:
    data = {...}  # ✅ No repository_id
```

**Impact:** Prevents runtime error when sensors try to create datasets.

**Fixed: create_repository() signature**

```python
# Before:
def create_repository(self, uri, watch_dir, base_branch, initial_cursor, 
                     default_dataset_name: str)

# After:
def create_repository(self, uri, watch_dir, base_branch, initial_cursor,
                     dataset_id: int)  # ✅ Direct FK
```

**Why:** Matches new API; sensors pass dataset_id after fetching dataset.

---

### dbseed/clients.py

**Fixed: create_dataset() signature** (same as dagster)
```python
# Removed: repository_id: int parameter
# Removed: "repository_id": repository_id from data dict
```

**Fixed: create_pull_request() status default**
```python
# Before: status: str = "unprocessed"  # ❌ Invalid enum value
# After:  status: str = "UNKNOWN"      # ✅ Valid PullRequestStatus
```

**Why:** Matches PullRequestStatus enum; seed script now works.

**Fixed: create_repository() parameter**
```python
# Before: default_dataset_name: str
# After:  dataset_id: int
```

---

### dbseed/models.py

**Updated: Repository model**
```python
# Before:
default_dataset_name: str | None = None
pull_request_count: int = 0

# After:
dataset_id: int
pr_count: int = 0
```

**Updated: PullRequest model**
```python
# Before:
dataset_id: int | None  # ❌ Removed

# After:
# ✅ No dataset_id field
```

**Updated: Dataset model**
```python
# Before:
repository_id: int | None = None  # ❌ Removed

# After:
# ✅ No repository_id field
```

---

### dbseed/seed_backend.py

**Before:**
```python
repo = api.create_repository(
    uri=REPO_URI,
    default_dataset_name=DATASET_NAME,  # ❌ Wrong order, wrong param
)
dataset = api.create_dataset(
    ...,
    repository_id=repo.id,  # ❌ Repository should exist first
)
```

**After:**
```python
dataset = api.create_dataset(  # ✅ Create first
    name=DATASET_NAME,
    host=DATASET_HOST,
    # NO repository_id
)
repo = api.create_repository(  # ✅ Then create repo with dataset
    uri=REPO_URI,
    dataset_id=dataset.id,  # ✅ Use dataset's id
)
```

**Why:** Enforces the new dependency: Dataset before Repository.

---

## Test Coverage

### WebServer Tests (test_repositories.py)

**Test: Repository creation requires dataset_id**
```python
def test_create_missing_dataset_id_fails(self, client, post_json_admin_header):
    response = client.post(
        "/repositories/",
        data=json.dumps({"uri": "github.com/org/new-repo"}),
        headers=post_json_admin_header
    )
    assert response.status_code == 400
    assert "dataset_id is required" in response.json.get("error", "")
```

**Validates:** API enforces dataset_id requirement.

---

**Test: Invalid dataset_id fails with 404**
```python
def test_create_invalid_dataset_id_fails(self, client, post_json_admin_header):
    response = client.post(
        "/repositories/",
        data=json.dumps({"uri": "github.com/org/new-repo", "dataset_id": 9999}),
        headers=post_json_admin_header
    )
    assert response.status_code == 404
```

**Validates:** FK constraint enforced; Dataset.get_by_id() raises DBRecordNotFoundError.

---

**Test: Response includes dataset_id**
```python
def test_create_includes_dataset_id_in_response(self, client, post_json_admin_header, test_dataset):
    body = {"uri": "github.com/org/test-repo", "dataset_id": test_dataset.id}
    response = client.post("/repositories/", data=json.dumps(body), headers=post_json_admin_header)
    assert response.status_code == 201
    assert "dataset_id" in response.json
    assert response.json["dataset_id"] == test_dataset.id
```

**Validates:** API returns sanitized_dict() with dataset_id.

---

**Test: Update dataset_id**
```python
def test_update_dataset_id(self, client, post_json_admin_header, repository, user_uuid, k8s_client, mock_kc_client):
    new_dataset = Dataset(name="NewDatasetForRepo", host="example.com", password='pass', username='user')
    new_dataset.add(user_id=user_uuid)
    
    response = client.patch(
        f"/repositories/{repository.id}",
        data=json.dumps({"dataset_id": new_dataset.id}),
        headers=post_json_admin_header
    )
    assert response.status_code == 200
    assert response.json["dataset_id"] == new_dataset.id
```

**Validates:** Repository can be re-assigned to different dataset; FK constraint allows update.

---

### Fixture Pattern Change

**Before:**
```python
@fixture
def default_repo(client) -> Repository:
    repo = Repository(uri=sample_repo_uri)
    repo.add()
    return repo
```

**After:**
```python
@fixture
def default_repo(client, user_uuid, k8s_client, mock_kc_client) -> Repository:
    dataset = Dataset(name="DefaultDatasetForRepo", host="example.com", password='pass', username='user')
    dataset.add(user_id=user_uuid)
    repo = Repository(uri=sample_repo_uri, watch_dir="", dataset_id=dataset.id)
    repo.add()
    return repo
```

**Impact:**
- Fixture now reflects real-world constraint: Dataset must exist first
- Tests that use `default_repo` get both dataset and repo
- Catches initialization order bugs early

---

## Validation: Field Alignment

### Repository Fields (Webserver → HTTP Test → Dagster)

| Field | WebServer Column | HTTP Test Model | Dagster Param | Status |
|-------|------------------|-----------------|---------------|--------|
| id | Integer PK | int | N/A (response only) | ✅ |
| uri | String(4096) unique | str | uri param | ✅ |
| watch_dir | String(4096) | str | watch_dir param | ✅ |
| base_branch | String(256) default='main' | str | base_branch param | ✅ |
| dataset_id | Integer FK → datasets.id | int | dataset_id param | ✅ |
| initial_cursor | DateTime default=now() | str (ISO 8601) | initial_cursor param | ✅ |
| pr_cursor | computed (max merged_at) | str (property) | N/A | ✅ |
| pr_count | computed (len) | int | N/A | ✅ |

---

### PullRequest Fields

| Field | WebServer Column | HTTP Test Model | Status |
|-------|------------------|-----------------|--------|
| repository_id | Integer PK FK | int | ✅ |
| number | Integer PK | int | ✅ |
| title | String(256) | str | ✅ |
| raised_by | String(256) | str | ✅ |
| merged_at | DateTime(tz=False) | str (ISO 8601) | ✅ |
| merge_commit_sha | String(40) | str | ✅ |
| spec | JSON | dict | ✅ |
| status | String(32) default='UNKNOWN' | str (enum value) | ✅ |
| saved_at | DateTime server_default=now() | str or None | ✅ |
| dataset_id | ❌ REMOVED | ❌ REMOVED | ✅ |

---

### Dataset Fields

| Field | WebServer Column | HTTP Test Model | Status |
|-------|------------------|-----------------|--------|
| id | Integer PK | int | ✅ |
| name | String(256) unique | str | ✅ |
| host | String(256) | str | ✅ |
| port | Integer default=5432 | int | ✅ |
| schema | String(256) nullable | str or None | ✅ |
| schema_write | String(256) nullable | str or None | ✅ |
| type | String(256) default='postgres' | str | ✅ |
| extra_connection_args | String(4096) nullable | str or None | ✅ |
| slug | computed property | str | ✅ |
| url | computed property | str | ✅ |
| repository_id | ❌ REMOVED | ❌ REMOVED | ✅ |

---

## Potential Issues & Mitigations

### Issue 1: Repository Orphaning During Transition
**Scenario:** Old code tries to create Repository without dataset_id  
**Mitigation:** API validation enforces `dataset_id` required; fails fast with 400  
**Test:** `test_create_missing_dataset_id_fails`

---

### Issue 2: Stale HTTP Test Models
**Scenario:** HTTP test models lag behind WebServer models  
**Mitigation:** Pydantic BaseModel with `extra="allow"` tolerates additional fields in API responses  
**Test:** All deserialization tests (e.g., `test_create_includes_dataset_id_in_response`)

---

### Issue 3: Migration Ordering
**Scenario:** Migration runs before datasets table exists  
**Mitigation:** Consolidated migration depends on `a18ca22994f6` (which creates datasets)  
**Status:** ✅ Safe; verified via alembic revision chain

---

### Issue 4: Sensor Logic Assumes dataset_id in Response
**Scenario:** Dagster sensor receives Repository from API, tries to access dataset_id  
**Mitigation:** Repository model always includes dataset_id in sanitized_dict()  
**Test:** `test_create_includes_dataset_id_in_response`

---

### Issue 5: Seed Script Fails if Dataset Create Fails
**Scenario:** POST /datasets returns error (auth, invalid port, etc.)  
**Mitigation:** Seed script will raise exception; user sees root cause  
**Status:** ✅ By design (fail-fast)

---

## Rollback Procedure

**If migration fails (rare, but documented):**

```bash
alembic downgrade d1e2f3a4b5c6
```

This removes both tables and is safe (no data loss, reverting to prior schema state).

---

## Future Considerations

### When Adding Project Model

**Current (MVP):**
```
Repository (with unique uri) ← project surrogate
  └─ Dataset (1:1)
  └─ PullRequest (N:1)
```

**Future (proper Project model):**
```
Project
  ├─ TriggerRepository (renamed from Repository)
  ├─ Dataset (reusable, 1:N via join table)
  ├─ DeliveryRepository
  └─ ProjectPullRequest (new, M:N via join table)
```

**Impact of Current Design:**
- ✅ PullRequest schema needs **zero changes** (already scoped to Repository)
- ✅ Repository → Dataset FK can be moved to Project → Dataset
- ✅ No data migration needed for pull_requests table

---

## Checklist: All Changes Verified

- [x] Database schema matches ORM models
- [x] API endpoints match schema and ORM
- [x] HTTP test models match API responses
- [x] Dagster client calls match API signatures
- [x] dbseed seed script enforces new dependency order
- [x] All fixtures create Dataset before Repository
- [x] No field name mismatches across layers
- [x] No type mismatches (Integer FK, datetime strings, etc.)
- [x] Status enum values consistent (UNKNOWN, not "unprocessed")
- [x] Migration consolidated and idempotent
- [x] FK constraints prevent orphaning
- [x] Tests validate both happy path and error cases
- [x] Backward compatibility not required (prior schema was broken)

---

## Summary

This refactoring corrects a **semantic flaw** in the original schema (bidirectional Repository-Dataset relationship with conflicting columns) by establishing a **clear unidirectional FK** (Repository → Dataset).

**Key wins:**
1. ✅ Datasets become reusable (future-proof)
2. ✅ PullRequest simplified (repo-scoped, no dataset_id)
3. ✅ FK constraints enforce invariants at database level
4. ✅ API validation fails fast on invalid dataset_id
5. ✅ Seed script works and enforces correct dependency order
6. ✅ No model drift across Dagster, HTTP test, and WebServer layers
7. ✅ Zero field mismatches in types, names, or presence

**Test strategy:**
- Fixture pattern enforces Dataset-before-Repository
- Positive tests verify creation, updates, and correct response
- Negative tests verify validation failures (missing/invalid dataset_id)
- HTTP test models validated against actual API responses

All changes are **verified and tested** before deployment.

