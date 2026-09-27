# DVC + Gitea Implementation via Agents

**Goal:** Parallelize implementation using agents for tedious work, keep complex/interesting work for humans.

**Timeline:** 3 days (day 1 parallel, day 2 sequential, day 3 integration + testing)

**Philosophy:** Agents are good at clear-spec, isolated tasks. Use them for DB + API scaffolding. Humans handle Dagster logic, sensor wiring, infrastructure.

---

## Agent Assignments

### Agent 1: Database Migrations

**Task:** Generate Alembic migrations for schema changes.

**Input:**
- Existing model file: `webserver/app/models/task.py`, `project.py`, etc.
- Schema spec from DVC_GITEA_RESULTS_PLAN.md (section "Database Schema")
- Existing migration structure (from `webserver/alembic/versions/`)

**Output:**
- `webserver/alembic/versions/xxxx_add_dvc_schema.py` (new tables + columns)
- `webserver/alembic/versions/xxxx_drop_unused_tables.py` (remove delivery_targets, etc.)

**Spec:**

```
New tables:
  - results_repositories: id (PK), uri (unique), owned_by_federated_node (BOOLEAN), created_at, updated_at
  - api_requests: id (PK), user_id, project_id (FK), payload (JSON), created_at

Updated tables:
  - projects: add dvc_backend (STRING, required), dvc_config (JSON, required), results_repository_id (FK, NOT NULL)
  - tasks: add s3_path (STRING, nullable), data_hash (STRING, nullable), git_commit_sha (STRING, NOT NULL), api_request_id (FK, nullable)

Removed tables:
  - delivery_targets
  - task_deliveries
  - storage_providers

Indexes:
  - tasks(project_id, status)
  - tasks(git_commit_sha)
```

**Success Criteria:**
- Migrations are idempotent
- Foreign key constraints are correct
- Existing task data is preserved (backward compat)
- Can roll back cleanly

**Duration:** 2-3 hours

**Risk:** Low (clear spec, isolated from logic)

---

### Agent 2: Webserver API

**Task:** Write new/updated Flask/FastAPI endpoints.

**Input:**
- Existing endpoints: `webserver/app/routes/`
- Task model from Agent 1 output (new schema)
- DVC_GITEA_RESULTS_PLAN.md (API requirements section)

**Output:**
- `webserver/app/routes/api_requests.py` (new)
- Updates to `webserver/app/routes/projects.py` (add dvc_backend, dvc_config, results_repository_id)
- Updates to `webserver/app/routes/tasks.py` (return s3_path, data_hash, git_commit_sha)

**Spec:**

```
New endpoints:
  - POST /api/projects/{project_id}/api_requests
    Input: {"docker_image": "...", "params": {...}, "metadata": {...}}
    Output: ApiRequest object with id
    
  - GET /api/projects/{project_id}/api_requests/{request_id}
    Output: ApiRequest object + linked tasks

Updated endpoints:
  - PATCH /api/projects/{project_id}
    Add to input schema: dvc_backend, dvc_config, results_repository_id
    
  - GET /api/tasks/{task_id}
    Add to output: s3_path, data_hash, git_commit_sha
    
  - GET /api/tasks?project_id=X
    Same as above
```

**Success Criteria:**
- Endpoints match existing patterns (authentication, validation, error handling)
- Schema matches task model
- Tests pass (if tests exist)
- Can accept/return new fields without breaking existing clients

**Duration:** 3-4 hours

**Risk:** Medium (needs to match existing patterns, but isolated from logic)

---

### Agent 3: Test Suite (Optional, parallel)

**Task:** Write E2E + unit tests for new functionality.

**Input:**
- New endpoints from Agent 2
- Schema from Agent 1
- Test patterns from existing tests

**Output:**
- `webserver/tests/test_api_requests.py` (new)
- Updates to `webserver/tests/test_tasks.py` (test new fields)

**Spec:**

```
Test cases:
  - POST /api/projects/{id}/api_requests creates task correctly
  - GET /api/tasks returns s3_path, data_hash, git_commit_sha
  - PATCH /api/projects/{id} accepts dvc_backend, dvc_config
  - New tables exist in database
  - Foreign key constraints work
```

**Duration:** 2-3 hours

**Risk:** Low (follows existing patterns)

---

## Human Work (Not Delegated)

### Task 1: Dagster Op (dvc_push_and_commit)

**Why humans:** Complex logic, requires understanding DVC + git + S3 interaction, error handling, retry logic.

**Scope:**
- Write op: `dagster/app/ops/dvc_push_and_commit.py`
- DVC remote config per task
- Git clone + commit logic
- Error handling (dvc push fails, git push fails)
- Idempotency checks

**Duration:** 8-10 hours

**Dependencies:** None (standalone)

---

### Task 2: Sensor Wiring (API Request → Task)

**Why humans:** Must integrate with existing PR sensor, understand trigger_source, dataset injection.

**Scope:**
- API request sensor: hook into task creation flow
- Ensure trigger_payload is set correctly
- Wire up dataset injection (from memory notes)
- Test against existing PR sensor (no conflicts)

**Duration:** 4-6 hours

**Dependencies:** Agent 1 (new schema), Agent 2 (new endpoints)

---

### Task 3: Gitea + K8s Setup (Optional, if doing self-hosted)

**Why humans:** Infrastructure, networking, secrets management. Needs verification/testing.

**Scope:**
- Helm chart deployment (values.yaml)
- SSH key generation + mounting
- Persistent storage (PVC)
- DNS/internal access
- Automated repo creation endpoint

**Duration:** 4-6 hours (1 day)

**Dependencies:** None

---

### Task 4: E2E Testing & Integration

**Why humans:** Catches integration bugs agents can't see.

**Scope:**
- Spin up full stack (DB, webserver, Dagster, Gitea)
- Trigger task via API
- Verify results in S3
- Verify git commit created
- Verify metadata.json in both S3 and git

**Duration:** 4-6 hours

**Dependencies:** All agents done, all human tasks done

---

## Execution Timeline

### Day 1 (Parallel)

**Agents (morning):**
- Agent 1: Database migrations (2-3 hours)
- Agent 2: API endpoints (3-4 hours)
- Agent 3: Tests (2-3 hours)

**Humans (simultaneously):**
- Task 3: Gitea + K8s setup (4-6 hours) [if doing self-hosted]

**EOD:** Code review of agent outputs, spot-check migrations, API contracts

### Day 2 (Sequential)

**Morning (2-3 hours):**
- Integrate Agent 1 + Agent 2 code into main
- Run migrations locally, verify schema
- Test new API endpoints

**Afternoon (6-8 hours):**
- Human Task 1: Write Dagster op (dvc_push_and_commit)
- Human Task 2: Wire up API request sensor
- Preliminary testing

### Day 3 (Integration + Testing)

**Morning (2-3 hours):**
- Human Task 4: E2E testing
- Fix integration bugs
- Debug git + DVC interaction

**Afternoon (2-3 hours):**
- Polish, final testing
- Document deployment steps
- Ready for production

---

## Agent Prompts (Ready to Use)

### Agent 1 Prompt

```
You are implementing database schema changes for a DVC + Git results delivery system.

Context:
- Webserver is Python with SQLAlchemy ORM
- Migrations use Alembic
- Existing models are in webserver/app/models/

Task:
Generate two Alembic migrations:

1. Add new tables:
   - results_repositories (id PK, uri unique, owned_by_federated_node BOOLEAN, created_at, updated_at)
   - api_requests (id PK, user_id, project_id FK, payload JSON, created_at)

2. Update existing tables:
   - projects: add dvc_backend (STRING, required), dvc_config (JSON, required), results_repository_id (FK → results_repositories, NOT NULL)
   - tasks: add s3_path (STRING, nullable), data_hash (STRING, nullable), git_commit_sha (STRING, NOT NULL), api_request_id (FK → api_requests, nullable)

3. Drop tables:
   - delivery_targets
   - task_deliveries
   - storage_providers

4. Add indexes:
   - tasks(project_id, status)
   - tasks(git_commit_sha)

Generate Alembic migration files following the pattern in webserver/alembic/versions/.
Ensure migrations are idempotent and include rollback logic.
```

### Agent 2 Prompt

```
You are implementing API endpoints for a task + API request management system.

Context:
- Webserver is Python Flask/FastAPI
- Existing endpoints follow patterns in webserver/app/routes/
- Task schema now includes: s3_path, data_hash, git_commit_sha, api_request_id

Task:
Write endpoints:

1. POST /api/projects/{project_id}/api_requests
   - Accept: {"docker_image": "model:v1.2.3", "params": {...}, "metadata": {...}}
   - Create ApiRequest row
   - Return: ApiRequest object with id

2. PATCH /api/projects/{project_id}
   - Add to input schema: dvc_backend (string), dvc_config (JSON), results_repository_id (int)
   - Update project, return updated project

3. GET /api/tasks/{task_id}
   - Add to response: s3_path, data_hash, git_commit_sha

4. GET /api/tasks?project_id=X
   - Same as above

Follow existing patterns for:
- Authentication
- Error handling
- Validation
- Response format
```

### Agent 3 Prompt (if using)

```
You are writing tests for new API endpoints and database schema.

Context:
- Tests are in webserver/tests/
- Existing test patterns use pytest + fixtures

Task:
Write test cases:

1. test_create_api_request: POST /api/projects/{id}/api_requests creates task
2. test_update_project_dvc_config: PATCH accepts new fields
3. test_task_response_includes_s3_metadata: GET task returns s3_path, data_hash, git_commit_sha
4. test_database_schema: Verify new tables exist, foreign keys work
5. test_backward_compat: Existing task fields still work

Use existing test patterns and fixtures.
```

---

## Verification Checklist

### After Agent 1 (Migrations):
- [ ] Migrations apply cleanly
- [ ] Migrations roll back cleanly
- [ ] Foreign keys are correct
- [ ] Indexes exist
- [ ] No data loss on existing tasks

### After Agent 2 (API):
- [ ] Endpoints respond to requests
- [ ] New fields are returned
- [ ] Validation works (e.g., missing required fields)
- [ ] Authentication still works
- [ ] Existing endpoints still work

### After Agent 3 (Tests):
- [ ] All tests pass
- [ ] Coverage includes new code
- [ ] Tests are runnable

### After Human Tasks:
- [ ] E2E: Task triggered via API → results in S3 + git
- [ ] E2E: Task triggered via PR → results in S3 + git
- [ ] Dagster retries work (dvc push idempotent)
- [ ] Git commits have correct metadata
- [ ] No conflicts with existing sensors

---

## Risk Mitigation

**Risk: Agents misunderstand schema**
- Mitigation: You review Agent 1 output, test migrations locally before committing

**Risk: Agents break existing endpoints**
- Mitigation: Agent 2 output is reviewed, existing tests must pass

**Risk: Sensor integration breaks**
- Mitigation: You do this part, not agents. High domain knowledge required.

**Risk: Timeline slips**
- Mitigation: Agents work in parallel (day 1), humans focus on hard parts (day 2-3)

---

## Why This Works

1. **Agents are fast at tedious work** (DB schema, API scaffolding) → Day 1 parallel work
2. **Humans focus on complex logic** (Dagster, sensor wiring, infrastructure) → Day 2-3 sequential
3. **Clear hand-off:** Agents output code, humans integrate + test
4. **Low risk:** DB + API are isolated from business logic
5. **Parallelization:** 3 agents working simultaneously while humans do unblocked work

---

## Next Steps

1. Review DVC_GITEA_RESULTS_PLAN.md (architecture + schema)
2. Spawn agents with prompts above (Agent 1, 2, 3 in parallel)
3. While agents work: Do Gitea setup (if self-hosted)
4. Integrate agent outputs (end of day 1)
5. Day 2: Dagster op + sensor wiring
6. Day 3: E2E testing + polish
7. Deploy

---

---

## Future Architecture: Trigger Abstraction

**Post-MVP refactor (when adding SQS/webhooks/Kafka):**

Current MVP: Unified sensor that scans both PR and API tables.

Future: Extract each trigger type into a `Trigger` interface for extensibility:

```python
class Trigger(ABC):
    @abstractmethod
    def get_pending_items(self): pass
    
    @abstractmethod
    def make_run_request(self, item): pass

class PullRequestTrigger(Trigger):
    # PR-specific logic: fetch from DB, validate from GitHub file
    
class ApiRequestTrigger(Trigger):
    # API-specific logic: fetch from DB, validate from payload

class SQSTrigger(Trigger):
    # Future: fetch from SQS, validate message format

# Unified sensor
class UnifiedTriggerSensor:
    triggers = [
        PullRequestTrigger(...),
        ApiRequestTrigger(...),
        # SQSTrigger(...),  # Add when needed
    ]
    
    def __call__(self):
        for trigger in self.triggers:
            for item in trigger.get_pending_items():
                yield trigger.make_run_request(item)
```

**Why this matters:**
- One code path (no if/else)
- Each trigger owns its logic
- Dead simple to add SQS trigger later (just implement Trigger)
- Testable (mock individual triggers)

**For MVP:** Ship with inline trigger logic in unified sensor. Refactor to Trigger abstraction post-launch when you actually add SQS.

---

**Ready to spawn agents? Use the prompts above. You've got this.**
