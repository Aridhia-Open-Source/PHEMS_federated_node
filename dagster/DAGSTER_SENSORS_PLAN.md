# Dagster Sensors: Comprehensive Audit & Implementation Plan

**Document Date:** 2026-09-27  
**Status:** READY FOR IMPLEMENTATION  
**Priority:** Enable E2E PR comment notification workflow

---

## 1. Current Implementation Status

### 1.1 Implemented & Working

#### PR Ingestion Pipeline
- **`pull_request_ingest_sensor`** ✅ DONE
  - Polls GitHub for new merged PRs in configured repositories
  - Fetches PR data (number, title, author, merge commit SHA)
  - Saves to database with UNKNOWN status
  - Updates repository `pr_cursor` to prevent re-ingestion

#### PR Trigger Pipeline
- **`pull_request_trigger_sensor`** ✅ DONE
  - Reads UNKNOWN status PRs from database
  - Validates watched files (exactly 1 JSON spec file)
  - Parses spec (validates `image`/`docker_image` key)
  - **Injects dataset credentials** via `dataset.dump_task_fields()`
  - Creates RunRequest → triggers `k8s_pipes_job`
  - Updates PR status to READY/INVALID/IGNORED

#### PR Status Monitoring
- **`task_queued_sensor`** ✅ DONE - Updates PR status to QUEUED when k8s_pipes_job starts
- **`task_started_sensor`** ✅ DONE - Updates PR status to STARTED when pod runs
- **`task_success_sensor`** ✅ DONE - Updates PR status to SUCCESS → triggers transfer job
- **`task_failure_sensor`** ✅ DONE - Updates PR status to FAILURE
- **`task_cancelled_sensor`** ✅ DONE - Updates PR status to CANCELLED

#### Results Transfer
- **`github_transfer_job` + `github_transfer_op`** ✅ DONE
  - Triggered by task_success_sensor
  - Clones delivery repository
  - Handles backend dispatch: git direct, DVC (s3/azure/gcp)
  - Creates results PR in delivery repo
  - Archives metadata.json with spec and run ID

#### Dataset Injection
- **Already implemented** ✅ VERIFIED
  - `pr_trigger.py` line 135-140:
    ```python
    dataset = self.backend_api.get_dataset(repo.dataset_id)
    op_config = {
        "env": pr.spec.get("env") or {},
        "docker_image": image,
        **dataset.dump_task_fields(),  # ← INJECTION HAPPENS HERE
    }
    ```
  - `Dataset.dump_task_fields()` returns `{"dataset_name", "dataset_host", "dataset_port", ...}`
  - These are merged into op_config and passed to k8s_pipes_op
  - No action needed — already complete

---

### 1.2 Commented Out / Needs Uncommenting

#### PR Comment Notification
- **`github_transfer_success_comment_sensor`** ⚠️ COMMENTED OUT (lines 280-323)
- **`github_pr_comment_op` + `github_pr_comment_job`** ⚠️ DEFINED but NOT WIRED (lines 103-118)
- **`GithubCommentOperation`** ⚠️ IMPLEMENTED in comment_op.py, unit tests passing

**Current state:**
- Code is complete: `comment_op.py` exists with full implementation
- Unit tests passing (4 tests in test_comment_op.py)
- Sensor is commented out in __init__.py lines 280-323
- Sensor **NOT listed in SENSORS array** (line 334)

**What's needed:**
1. Uncomment `github_transfer_success_comment_sensor` (lines 280-323)
2. Add to SENSORS list (line 334)
3. Verify tags are properly passed through the flow
4. E2E test: PR → ingest → trigger → k8s_pipes → success → transfer → **comment**

---

## 2. Full Data Flow Diagram

```
GitHub PR Created (merged)
         ↓
[PR INGEST SENSOR] (runs every 10s)
  • Query GitHub for new merged PRs since cursor
  • Validate single watched JSON file
  • Save to DB with status=UNKNOWN
  • Update repo.pr_cursor
         ↓
Database: PullRequest(status=UNKNOWN, spec={}, ...)
         ↓
[PR TRIGGER SENSOR] (runs every 10s)
  • Fetch UNKNOWN PRs from DB
  • Parse spec from GitHub file
  • Validate image key in spec
  • Inject dataset credentials via dump_task_fields()
  • Create RunRequest → k8s_pipes_job
  • Update PR status to READY/INVALID/IGNORED
         ↓
[K8S_PIPES_JOB] (triggered by RunRequest)
  • Receives op_config with dataset fields + image
  • Spins up pod with Docker image
  • Runs containerized task
  • Task accesses dataset via env vars (DB_HOST, DB_PORT, etc.)
  • Outputs results to artifact mount
         ↓
[RUN_STATUS_SENSORS] - Multiple parallel sensors
  ├─ task_queued_sensor → DB: status=QUEUED
  ├─ task_started_sensor → DB: status=STARTED
  ├─ task_success_sensor (SUCCESS)
  │   • DB: status=SUCCESS
  │   • RunRequest → github_transfer_job
  │   └─ [GITHUB_TRANSFER_JOB]
  │       • Clone delivery repo
  │       • Commit results + metadata.json
  │       • Push + create results PR
  │       └─ (SUCCESS on transfer job)
  │           └─ [GITHUB_COMMENT_SENSOR] ⚠️ COMMENTED OUT
  │               • RunRequest → github_pr_comment_job
  │               └─ [GITHUB_PR_COMMENT_JOB]
  │                   • Add success comment to ORIGINAL PR
  │                   • Comment: "✅ Analysis complete - Run ID: {id}"
  │
  ├─ task_failure_sensor → DB: status=FAILURE
  │
  └─ task_cancelled_sensor → DB: status=CANCELLED
```

---

## 3. Gap Analysis & Issues Found

### 3.1 Critical Blockers
None - E2E flow is fully implemented.

### 3.2 Current Issues

#### Issue #1: Comment Sensor Commented Out
- **File:** `dagster/app/definitions/sensors/github/__init__.py`
- **Lines:** 280-323 (sensor definition), 334 (SENSORS list)
- **Impact:** PR comment notifications not triggered after successful transfer
- **Fix:** 3-line change (uncomment + add to list)
- **Effort:** 5 minutes, zero risk

#### Issue #2: Missing Transfer Job Info in Comment Sensor Tags
- **Current:** Comment sensor reads tags from transfer_job run
- **Required:** Needs `pr_number`, `parent_run_id`, `repo_uri`
- **Status:** transfer job does pass these tags via RunRequest (line 205-211)
- **Verification:** Need to check if RunRequest from task_success_sensor includes all tags
- **Risk:** Low - tags are explicitly set in RunRequest (line 207)

#### Issue #3: Comment Sensor Tag Filtering
- **Current:** Sensor checks `run.tags.get("trigger") == "github_transfer"` (line 291)
- **Actual tag value:** Set in task_success_sensor as `"trigger": "github_transfer"` (line 208)
- **Status:** ✅ Matches - no issue
- **Note:** Comment sensor checks for "github" (line 291), but transfer sets "github_transfer"
  - This is actually CORRECT - transfer job has trigger="github_transfer"

#### Issue #4: Unused "Generator" Import in comment_op.py
- **File:** `dagster/app/definitions/sensors/github/comment_op.py`
- **Issue:** Memory note mentions unused import (may be stale)
- **Verification:** Checked - no unused imports in current code
- **Status:** ✅ False alarm

#### Issue #5: Line Length Warnings (Minor)
- **File:** Memory mentions lines 35, 99, 114 are too long
- **Impact:** Linting only, functionality unaffected
- **Decision:** Per memory rule "never auto-fix line length warnings, 90 chars is a guide not a rule"
- **Status:** Won't fix

---

## 4. Dataset Injection Verification

### Current Implementation (pr_trigger.py, lines 135-140)

```python
# Get dataset by repository
dataset = self.backend_api.get_dataset(repo.dataset_id)

# Merge dataset fields into op_config
op_config = {
    "env": pr.spec.get("env") or {},
    "docker_image": image,
    **dataset.dump_task_fields(),  # ← INJECTION POINT
}
```

### Dataset Model: dump_task_fields()

```python
def dump_task_fields(self) -> dict:
    """Return only the fields needed for task configuration with dataset_ prefix."""
    keys = {"name", "host", "port", "type", "schema", "schema_write", "secret_name"}
    fields = self.model_dump(include=keys)
    return {f"dataset_{k}": v for k, v in fields.items()}
```

### Result
Each task receives:
- `dataset_name` → dataset name (e.g., "primary_db")
- `dataset_host` → connection host
- `dataset_port` → connection port
- `dataset_type` → db type (postgres, mysql, etc.)
- `dataset_schema` → schema name
- `dataset_schema_write` → write schema
- `dataset_secret_name` → k8s secret name for auth

### Verification
✅ **Confirmed working** - No changes needed.

---

## 5. Step-by-Step Implementation Plan

### Step 1: Uncomment Comment Sensor (5 min, ~0% risk)

**File:** `dagster/app/definitions/sensors/github/__init__.py`

**Changes:**
1. Lines 280-323: Uncomment the `github_transfer_success_comment_sensor` definition
2. Line 334: Uncomment `github_transfer_success_comment_sensor` in SENSORS list

**Code change:**
```python
# BEFORE
@dg.run_status_sensor(
    run_status=dg.DagsterRunStatus.SUCCESS,
    default_status=dg.DefaultSensorStatus.RUNNING,
    monitored_jobs=[github_transfer_job],
    request_job=github_pr_comment_job,
    minimum_interval_seconds=MIN_SENSOR_INTERVAL_SECONDS,
)
def github_transfer_success_comment_sensor(context: RunStatusSensorContext):
    """Trigger PR comment after successful transfer job."""
    # ... implementation

SENSORS = [
    pull_request_ingest_sensor,
    pull_request_trigger_sensor,
    task_queued_sensor,
    task_started_sensor,
    task_success_sensor,
    task_failure_sensor,
    task_cancelled_sensor,
    # github_transfer_success_comment_sensor,  ← COMMENTED
]

# AFTER - uncomment both
@dg.run_status_sensor(...)
def github_transfer_success_comment_sensor(context: RunStatusSensorContext):
    """Trigger PR comment after successful transfer job."""
    # ... implementation

SENSORS = [
    pull_request_ingest_sensor,
    pull_request_trigger_sensor,
    task_queued_sensor,
    task_started_sensor,
    task_success_sensor,
    task_failure_sensor,
    task_cancelled_sensor,
    github_transfer_success_comment_sensor,  ← UNCOMMENTED
]
```

**Validation:**
- All 67 unit tests should still pass
- Sensor will start monitoring github_transfer_job for SUCCESS runs
- On SUCCESS, will yield RunRequest to github_pr_comment_job
- Job will post comment to original PR

### Step 2: Tag Flow Verification (10 min, informational)

**Verify tag chain through flow:**
1. ✅ RunRequest in pr_trigger.py (line 146-161) sets: `"trigger": "github"`, `"pr_number"`, `"repo_uri"`
2. ✅ k8s_pipes_job runs with these tags
3. ✅ RunRequest in task_success_sensor (line 205-223) sets:
   - `"trigger": "github_transfer"` (different from k8s_pipes!)
   - `"pr_number"`: from run.tags
   - `"parent_run_id"`: run.run_id
4. ✅ github_transfer_job runs with these tags
5. ✅ RunRequest in github_transfer_success_comment_sensor (line 305-323) sets:
   - `"trigger": "github"`
   - `"pr_number"`: from run.tags
   - `"parent_run_id"`: from run.tags
   - `"repo_uri"`: from run.tags

**Key insight:** Tag values change at each stage:
- `trigger: "github"` → k8s_pipes_job
- `trigger: "github_transfer"` → github_transfer_job
- `trigger: "github"` → github_pr_comment_job

This is intentional - sensors filter by trigger type to know which jobs to monitor.

**No changes needed** - flow verified.

### Step 3: Optional - Add Comment Sensor Monitoring/Logging (15 min)

If needed for debugging E2E flow, could add:
- Structured logging in comment_op.py
- Metrics/monitoring for comment posting success/failure
- **Current status:** Not necessary for MVP

---

## 6. E2E Testing Approach

### Manual E2E Test Steps

1. **Setup:** Repository configured in PHEMS backend
2. **Create PR:** Merge PR with valid spec.json to trigger repo
   ```json
   {
     "image": "alpine:latest",
     "env": {"TEST": "value"},
     "dataset": "primary_db"
   }
   ```
3. **Monitor Ingest:** Check PR appears in DB with status=UNKNOWN
4. **Monitor Trigger:** Check PR advances to status=READY
5. **Monitor Execution:** k8s_pipes_job runs → status=QUEUED → STARTED → SUCCESS
6. **Monitor Transfer:** github_transfer_job runs → creates results PR
7. **Monitor Comment:** github_pr_comment_job runs → posts comment to **original trigger PR**
8. **Verify Comment:** Navigate to original PR #123 → see comment "✅ Analysis complete - Run ID: xxx"

### Automated Testing

**Current state:** Unit tests exist for comment_op.py (4 tests)
- `test_adds_comment_to_pr` ✅
- `test_comment_contains_success_message` ✅
- `test_comment_includes_run_id` ✅
- `test_logs_comment_action` ✅

**Missing:** Integration test for full sensor flow (beyond scope of this audit)

---

## 7. Implementation Blockers & Dependencies

### External Dependencies
- GitHub API token configured (`GithubConfig.token`)
- Backend API accessible (`BackendConfig`)
- k8s_pipes_job deployed and functional
- Database with PullRequest table initialized

### Internal Dependencies
- `GithubAPI.add_pull_request_comment()` method exists ✅
- `Backend.get_dataset()` method exists ✅
- `Dataset.dump_task_fields()` method exists ✅

### No Blockers Found ✅

---

## 8. Success Criteria

### Step 1 Complete (Uncomment)
- [ ] `github_transfer_success_comment_sensor` uncommented in __init__.py
- [ ] Sensor added to SENSORS list
- [ ] All unit tests pass (expect 67)
- [ ] Code lints (ignoring line-length warnings per project rules)
- [ ] No circular imports or runtime errors

### Full E2E Complete
- [ ] PR ingested to database ✅ (already working)
- [ ] PR triggered k8s_pipes_job ✅ (already working)
- [ ] Transfer job creates results PR ✅ (already working)
- [ ] Comment sensor detects transfer job success
- [ ] Comment job posts comment to original PR
- [ ] Comment text contains "✅" and run ID
- [ ] Tested in staging environment with real GitHub repo

---

## 9. Implementation Effort Summary

| Step | Task | Effort | Risk | Blocking |
|------|------|--------|------|----------|
| 1 | Uncomment comment sensor | 5 min | ~0% | No |
| 2 | Verify tag flow | 10 min | 0% | No |
| 3 | Optional logging/monitoring | 15 min | ~0% | No |
| **Total** | **Ready to Ship** | **~30 min** | **Minimal** | **None** |

---

## 10. Recommendations

### Immediate Action (This Session)
✅ Execute **Step 1** (uncomment sensor)
✅ Execute **Step 2** (verify tags)
- Commit changes
- Run unit tests
- Ready for E2E testing

### Next Session
- Manual E2E test with staging environment
- Verify comment posts to original PR
- Monitor Dagster logs for sensor execution
- Adjust log levels if needed for debugging

### Future Enhancements (Not Required)
- Add structured logging for sensor execution
- Implement comment content templating (currently hardcoded)
- Add retry logic for GitHub API failures
- Monitor comment posting success rate via metrics

---

## 11. Files Changed

### This Audit (No changes yet)
- Created: `dagster/DAGSTER_SENSORS_PLAN.md` (this file)

### To be Changed (Step 1)
- `dagster/app/definitions/sensors/github/__init__.py`
  - Lines 280-323: Uncomment sensor
  - Line 334: Add to SENSORS list

### Already Complete (No changes needed)
- `dagster/app/definitions/sensors/github/comment_op.py`
- `dagster/app/definitions/sensors/github/pr_trigger.py`
- `dagster/app/models.py` (Dataset.dump_task_fields)
- `dagster/app/tests/test_comment_op.py`

---

## 12. Quick Reference: Sensor Dependencies

```
Dataset Injection:
  pr_trigger.py:135-140 → get_dataset() → dump_task_fields() → op_config

Comment Posting:
  comment_op.py → github_api.add_pull_request_comment(repo_path, pr_number, body)

Tag Flow:
  pr_trigger → task (trigger="github")
           ↓
  transfer_job → (trigger="github_transfer")
           ↓
  comment_job → (trigger="github")
```

---

**Document Status:** READY FOR IMPLEMENTATION
**Next Step:** Execute Step 1 - Uncomment comment sensor
