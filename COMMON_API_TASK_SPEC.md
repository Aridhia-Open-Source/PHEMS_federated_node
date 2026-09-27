# CommonAPI Task Specification & Implementation Plan

## Context

PHEMS implements [The Common API](https://github.com/federated-data-sharing/common-api) — a federated data sharing standard that defines the structure and lifecycle of API calls across federated nodes. The webserver's Task API is expected to implement this spec.

This document maps the current Task API implementation against the CommonAPI specification, identifies compatibility gaps with the new four-layer Task model (PullRequest/ApiRequest → TaskRequest → Task → TaskResult), and sequences the work needed for full spec compliance.

---

## Part 1: CommonAPI Task Specification

### External Reference
- **Spec Repository:** https://github.com/federated-data-sharing/common-api
- **PHEMS Context:** Mentioned in webserver README.md as the standard for federated node API structure
- **Implementation Status:** Task endpoints exist in `webserver/app/tasks_api.py` but most are stubbed (`raise NotImplementedException()`)

### Task Lifecycle (CommonAPI Model)

Tasks in the CommonAPI spec follow a lifecycle:
1. **Submission** — POST /tasks with task definition (name, description, executors, tags, resources, repository)
2. **Validation** — POST /tasks/validate to check task definition without creation
3. **Polling** — GET /tasks/{id} to check status (waiting → running → terminated)
4. **Results Access** — GET /tasks/{id}/results (approved) or GET /tasks/{id}/logs
5. **Approval/Blocking** — POST /tasks/{id}/results/approve and POST /tasks/{id}/results/block for governance
6. **Cancellation** — POST /tasks/{id}/cancel to stop a scheduled or running task

### Current OpenAPI Schema Definition

Extracted from `webserver/app/static/openapi.json`:

#### TaskPostBody (create a task)
```json
{
  "required": ["executors", "name", "tags", "project_id"],
  "properties": {
    "name": { "type": "string", "maxLength": 256 },
    "description": { "type": "string", "maxLength": 4096 },
    "executors": {
      "type": "object",
      "required": ["image"],
      "properties": {
        "image": { "type": "string", "maxLength": 256 },
        "command": { "type": "array", "items": { "type": "string" } },
        "env": { "type": "object" }
      }
    },
    "tags": {
      "type": "object",
      "required": ["dataset_id"],
      "properties": {
        "dataset_id": { "type": "string" },
        "dataset_name": { "type": "string" },
        "custom_tag": { "type": "string" }
      }
    },
    "resources": {
      "type": "object",
      "properties": {
        "cpu_cores": { "type": "integer" },
        "ram_gb": { "type": "integer" },
        "disk_gb": { "type": "integer" },
        "preemptible": { "type": "boolean" },
        "zones": { "type": "string" }
      }
    },
    "repository": { "type": "string" },
    "project_id": { "type": "integer" }
  }
}
```

#### TaskById (GET /tasks/{id} response)
```json
{
  "properties": {
    "id": { "type": "string" },
    "created_at": { "type": "string" },
    "updated_at": { "type": "string" },
    "title": { "type": "string" },
    "description": { "type": "string" },
    "docker_image": { "type": "string" },
    "dataset_id": { "type": "integer" },
    "project_id": { "type": "integer" },
    "requested_by": { "type": "string" },
    "status": {
      "type": "object",
      "properties": {
        "running": { "type": "object" },
        "terminated": { "type": "object" },
        "waiting": { "type": "object" }
      }
    }
  }
}
```

**Status Object Format** (WES-style): One of `running`, `terminated`, `waiting` is present, containing state-specific metadata.

---

## Part 2: Current Implementation Status

### Endpoints Defined (webserver/app/tasks_api.py)

| Endpoint | Method | Status | Auth Scope | Notes |
|----------|--------|--------|------------|-------|
| `/tasks/service-info` | GET | ✅ Implemented | `can_do_admin` | Returns name + doc |
| `/tasks` | GET | ❌ NotImplemented | `can_admin_task` | List tasks with pagination |
| `/tasks` | POST | ❌ NotImplemented | `can_exec_task` | Create a new task |
| `/tasks/validate` | POST | ✅ Implemented | `can_exec_task` | Validates task spec (calls `Task.validate()`) |
| `/tasks/{id}` | GET | ❌ NotImplemented | `can_exec_task` | Get single task + status |
| `/tasks/{id}/cancel` | POST | ❌ NotImplemented | `can_admin_task` | Cancel scheduled/running task |
| `/tasks/{id}/results` | GET | ❌ NotImplemented | `can_exec_task` | Get task results (if approved) |
| `/tasks/{id}/logs` | GET | ❌ NotImplemented | `can_exec_task` | Get task execution logs |
| `/tasks/{id}/results/approve` | POST | ❌ NotImplemented | `can_admin_task` | Approve result release |
| `/tasks/{id}/results/block` | POST | ❌ NotImplemented | `can_admin_task` | Block result release |

### Current Task Model (app/models/task.py)

**Existing fields (unchanged):**
- id, project_id, pr_repository_id, pr_number, pr_spec, request_id
- title, description, docker_image, status (hardcoded 'scheduled' — inconsistent), created_at, updated_at
- dataset_id, requested_by
- Multiple resource fields (cpu_cores, ram_gb, disk_gb, etc.)
- validate() method — comprehensive, currently works but takes kwargs and silently drops unknowns

**State of Task.status:**
- Currently hardcoded to string `'scheduled'`
- Not a valid `TaskStatus` enum member (pre-existing bug)
- Five live Dagster `run_status_sensor`s write **PullRequest.status** (QUEUED→STARTED→SUCCESS/FAILURE/CANCELLED), not Task.status
- Fixing Task.status requires re-pointing those sensors (out of scope for this plan)

### Known Inconsistencies

1. **Status representation mismatch**: OpenAPI expects status object (running/terminated/waiting), but Task.status is hardcoded to 'scheduled' string
2. **No Task creation path**: No code anywhere creates Task rows — all execution tracking is on PullRequest.status today
3. **Request ambiguity**: Task has `request_id` FK (→ Data Access Requests table), but new ApiRequest trigger adds `api_request_id` — both named "request" semantically but point to different tables
4. **Implicit serialization gap**: OpenAPI schema shows `docker_image`, `title` but Task model stores `spec` (JSON blob containing the execution definition) — conversion between spec and flattened fields is implicit in current code

---

## Part 3: New Task Model (Four-Layer Architecture)

### Design Overview

```
PullRequest (GitHub trigger)     ApiRequest (API trigger)
         ↓                                  ↓
         └──────────────→ TaskRequest ←────┘
                            ↓
                          Task ← (cache of Dagster execution + results metadata)
                            ↓
                        TaskResult ← (where results were delivered)
```

### New Fields on Task (from DVC_GITEA_DB_SCHEMA.md)

All nullable — Task is currently unreachable by live code, so this is purely additive:

```python
api_request_id = Column(Integer, ForeignKey('api_requests.id', ondelete='SET NULL'), nullable=True)
git_commit_sha = Column(String(40), nullable=True)
results_path = Column(String(512), nullable=True)
trigger_payload = Column(JSON, nullable=True)
```

### Compatibility with CommonAPI Spec

✅ **Compatible** — New fields are database-only, not exposed via OpenAPI responses unless explicitly serialized.

**Reasoning:**
1. API response shape is determined by serialization logic (sanitized_dict() / response model), not table schema
2. New fields can be added without breaking CommonAPI responses
3. Existing CommonAPI-required fields (id, created_at, requested_by, project_id, status, etc.) remain unchanged in the database
4. The new layer (TaskRequest, results delivery via TaskResult) is a *refinement*, not a replacement — doesn't conflict with the CommonAPI task submission flow

**Risk:** If any endpoint currently serializes Task.__dict__ directly (common anti-pattern), the new JSON/nullable fields would appear in the response. Worth auditing before go-live.

---

## Part 4: Work Sequencing

### Phase 1: Schema (Current/Immediate)
**Deliverable:** DVC_GITEA_DB_SCHEMA.md + Alembic migration baseline
- ✅ New models: ResultsRepository, ResultsBackend, ApiRequest
- ✅ Updated Task model with new fields
- ✅ SqlaColumn helper for timestamp standardization
- ✅ Migration cleanup (delete 20 old migrations, generate one baseline)
- **Impact on CommonAPI:** None — database changes only

### Phase 2: API Endpoint Implementation
**Timeline:** After Phase 1 is deployed, before results delivery is live
**Scope:** Implement the currently-stubbed endpoints in tasks_api.py

| Endpoint | Work | Dependency | CommonAPI Alignment |
|----------|------|-----------|---------------------|
| POST /tasks | Task creation + ApiRequest wiring | Phase 1 | Must create Task row + set created_at, requested_by |
| GET /tasks/{id} | Query Task, serialize status | Phase 2a | Must convert hardcoded status to CommonAPI status object |
| GET /tasks | List with pagination | Phase 2a | Use pagination helper (already exists) |
| POST /tasks/{id}/cancel | Dagster run cancel RPC | Phase 2a | Rare (most tasks finish via Dagster); fallback to kill container |
| GET /tasks/{id}/results | Check TaskResult.approved, return path | Phase 2b | Must wait for TaskResult model + approval workflow |
| POST /tasks/{id}/results/approve | Set TaskResult.approved | Phase 2b | Governance gating (who can approve?) |
| POST /tasks/{id}/results/block | Set TaskResult.blocked | Phase 2b | Governance gating |
| GET /tasks/{id}/logs | Query Dagster API or k8s logs | Phase 2a | Forwarding only; no schema changes needed |

**Critical Blocker for Phase 2:** The five live `run_status_sensor`s must be re-pointed from `PullRequest.status` to `Task.status` before endpoints can report accurate status. This is a Dagster change (out of scope here but sequenced as Phase 2a prerequisite).

### Phase 3: Results Delivery Wiring
**Timeline:** After Phase 2, parallel with results-repo auto-provisioning
**Scope:** transfer_op.py integration with Task fields

- transfer_op.py already expects `task.trigger_payload` and `task.results_backend` to exist ✅ (will be present after Phase 1)
- After results commit, populate `task.git_commit_sha` and `task.results_path`
- Populate `trigger_payload` at task-creation time (Phase 2)
- No changes needed to CommonAPI shape — results access is via GET /tasks/{id}/results (Phase 2b)

### Phase 4: Sensor Wiring (Dagster Changes)
**Timeline:** Parallel with Phase 2, blocks Phase 2a completion
**Scope:** Not in this plan (webserver-only constraint), but documented here for sequencing

- Re-point `task_queued_sensor`, `task_started_sensor`, etc. from `PullRequest.status` → `Task.status`
- Implications: No impact on CommonAPI (status field moves, but shape stays same)
- Risk: Five sensors currently write QUEUED/STARTED/SUCCESS/FAILURE/CANCELLED — must preserve those enum values

---

## Part 5: CommonAPI Compliance Checklist

### Spec Alignment (Pre-Implementation Audit)

- [ ] **Endpoints**: All 10 endpoints in tasks_api.py match CommonAPI structure
- [ ] **Request Schema**: TaskPostBody matches spec (name, description, executors, tags, resources, repository, project_id)
- [ ] **Response Schema**: TaskById status field returns object (running/terminated/waiting), not string
- [ ] **Error Handling**: Implement CommonAPI error codes (4xx for validation, 5xx for server)
- [ ] **Pagination**: GET /tasks uses standard page/per_page params (already in OpenAPI)
- [ ] **Authentication**: All endpoints use Keycloak tokens + audit logging ✅ (inherited from auth decorators)
- [ ] **Ownership Check**: does_user_own_task() already validates before returning results/logs

### Known Divergences from CommonAPI (Document & Accept)

1. **Task triggering method**: PHEMS supports both PR-based (GitHub) and API-based (POST /tasks) triggers; CommonAPI may assume single trigger model. Clarify in docs.
2. **Status granularity**: Hardcoded 'scheduled' vs. CommonAPI expected waiting→running→terminated. Fix in Phase 2a sensor wiring.
3. **Spec field flattening**: TaskPostBody takes flattened executors/tags/resources; Task.spec stores JSON blob. Conversion logic exists but not explicitly documented.

---

## Part 6: Risk Assessment

| Risk | Severity | Mitigation | When |
|------|----------|-----------|------|
| Task.status still hardcoded 'scheduled' after Phase 1 | HIGH | Re-point sensors in Phase 2a (Dagster work). Endpoints must handle in response serialization. | Phase 2 |
| New Task fields appear in API response | MEDIUM | Audit sanitized_dict() + response models before Phase 2 go-live. Use explicit field allowlist. | Phase 2 planning |
| ApiRequest vs. existing request_id confusion | LOW | Document in model docstrings + API docs. Use different relationship names (already: api_request_id). | Phase 2 docs |
| Results approval governance undefined | MEDIUM | Design approval workflow + gating before Phase 2b. Who approves? How are decisions logged? | Phase 2b spec |
| Dagster sensor wiring blocks Phase 2 | HIGH | Sequence Phase 2a work (endpoints, status object) with Dagster re-pointing. Agreed out-of-scope here but hard dependency. | Phase 2 planning |

---

## Part 7: Implementation Order (Recommended)

### Immediate (Phase 1 — Schemas)
1. Write + merge DVC_GITEA_DB_SCHEMA.md (this session)
2. Delete old migrations, generate baseline (this session)
3. Deploy migration to dev/test

### Next Sprint (Phase 2a — Endpoints + Status)
1. **Prerequisite (Dagster):** Re-point run_status_sensors to Task.status ← *Not this session, separate Dagster PR*
2. Implement POST /tasks endpoint (create Task + ApiRequest)
3. Implement GET /tasks/{id} endpoint (query Task, serialize status to CommonAPI object format)
4. Implement GET /tasks endpoint (list with pagination)
5. Implement GET /tasks/{id}/logs endpoint (Dagster API forwarding)
6. Implement POST /tasks/{id}/cancel endpoint (Dagster run cancel)
7. Audit + fix any Task field leakage in response models

### Later (Phase 2b — Results Governance)
1. Design approval workflow (who, when, how logged)
2. Implement POST /tasks/{id}/results/approve
3. Implement POST /tasks/{id}/results/block
4. Implement GET /tasks/{id}/results (check approval status)

### Parallel (Phase 3 — Transfer Op Integration)
1. Confirm transfer_op.py has access to task.trigger_payload + task.results_backend
2. After commit, populate task.git_commit_sha + task.results_path
3. Test E2E results delivery

---

## Summary

The new Task model is **spec-compatible with CommonAPI** because:
1. New database fields don't force API response changes
2. CommonAPI task submission flow (POST /tasks with executors/tags/resources) stays intact
3. Task status representation can be fixed without schema changes (just serialization logic + sensor re-pointing)
4. Results delivery (new feature) layers on top without breaking existing endpoints

**Critical path to full CommonAPI compliance:**
- Phase 1: Database schema (ready now)
- Phase 2a: Endpoints + Dagster sensor re-pointing (blocked on Dagster work outside this scope)
- Phase 2b: Results governance (define approval model)
- Phase 3: Results delivery ops integration (parallel, independent)

This plan preserves all existing CommonAPI guarantees while enabling the new four-layer architecture (TaskRequest + Task + TaskResult) that the DVC results delivery design requires.
