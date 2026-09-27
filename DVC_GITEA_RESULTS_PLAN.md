# DVC + Gitea Results Delivery Plan (MVP)

## TL;DR (30 seconds)

**Two separate concerns (this is the key insight):**

1. **ResultsBackend** (data storage): DVC → S3/Azure
   - Where files actually live
   - Optimized for performance, dedup, cost
   - Clients don't need to run/own this

2. **ResultsRepository** (audit trail): Git → Gitea/GitHub
   - Where approval/change control lives
   - Pull requests = governance workflow
   - Git log = immutable compliance record
   - Med tech NEEDS this for regulators

**One code path:** `dvc add → dvc push (backend) → git commit → git push (repository)`

**Default:** Both enabled (DVC for data, git for audit). Post-MVP: make git optional if needed.

**Implementation summary:** Rip out delivery_targets/task_deliveries (conflated these concerns). Add ResultsBackend + ResultsRepository. Single dvc_push_and_commit op. Done.

---

## Architecture: Unified Backend Model

### The insight

**One backend choice, multiple storage options:**

1. **ResultsBackend** (git | s3 | azure | gcp): Where data lives
   - `git`: files committed directly to Gitea
   - `s3/azure/gcp`: files pushed via DVC, .dvc pointers to git for audit trail

2. **ResultsRepository** (Git): Always Gitea/GitHub (auto-created), used for audit trail + approval workflow

This matters because:
- Clients pick their storage backend (git is the default, no config needed)
- All backends record an immutable audit trail in git (for compliance)
- Med tech gets git log + commit history for regulators ("prove what ran, when, by whom")

### The flow (varies by backend type):

**If backend type is "git":**
```
Experiment runs → Results produced → Commit files to git repo → Done
```

**If backend type is "s3/azure/gcp":**
```
Experiment runs → Results produced → DVC push to backend → Commit .dvc pointers to git → Done
```

**In both cases:**
```
[1] Handle backend:
    If git: nothing (files stay in artifact dir)
    If s3/azure/gcp: dvc add + dvc push
  ↓
[2] Commit to git:
    Clone results repo
    Copy backend files (raw files or .dvc files)
    Create metadata.json (task context, backend type, remote url)
    Commit everything
    Push to git
  ↓
[3] Update database:
    tasks.backend_type = "git" | "s3" | "azure" | "gcp"
    tasks.git_commit_sha = "<sha>"
    tasks.status = "success"
  ↓
Done. Data in backend, audit trail in git.
```

### Why this works:

- **Flexible:** Clients choose their backend (git by default, no setup needed).
- **One code path:** Same commit-to-git logic for all backends. Branching only on backend type choice.
- **Audit trail guaranteed:** Git has immutable history for all backends (compliance requirement).
- **Data efficient:** DVC deduplication for cloud backends (cost savings).
- **Client-friendly:** Default is git (zero config). Cloud backends optional.
- **Compliance:** "Show me audit log" → git log (works for all backends). "Prove data integrity" → metadata.json + git history.
- **Future-proof:** Adding new backends (e.g., PostgreSQL, S3-compatible) just means adding a new backend type.

---

## Why Clients Pick GitHub (It's Not Just Convenience)

**Liam says:** "Clients picked GitHub because it was easy"

**Reality:** Clients pick GitHub/git because it's the **approval + audit mechanism**

**In med tech, PRs matter:**
- PR = "I want to run this task"
- Review = "Is this approved?"
- Merge = "Yes, run it"
- Commit SHA = Immutable proof it ran
- Git log = Compliance record for regulators

**Why S3 alone isn't enough:**
- S3 = data storage (efficient, but no governance)
- Git = control plane (approval workflow + audit trail)

**Why this architecture works:**
- You (federated-node) manage the data backend (DVC → S3, optimized)
- Client controls the approval backend (GitHub/Gitea, their workflow)
- Regulators get: git log (who did what, when)
- You get: S3 data (deduplicated, cheap)

**One more thing:** Technically the audit could be SVN, a database with immutable logs, or any other system. The point is: separate data storage from governance/audit. Git happens to be great for med tech (already using for code, familiar workflows).

---

## Database Schema

### Core tables (unchanged):

```
projects:
  id (PK)
  name (unique)
  description
  trigger_repository_id (FK → trigger_repositories)
  created_at, updated_at

trigger_repositories:
  id (PK)
  uri (unique)
  watch_dir
  base_branch
  initial_cursor
  created_at, updated_at

pull_requests:
  trigger_repository_id (PK part 1, FK)
  number (PK part 2)
  title, raised_by, merged_at, merge_commit_sha, spec (JSON)
  saved_at

datasets:
  (unchanged)
```

### Updated/New tables:

```
projects (UPDATED):
  + results_repository_id (FK → results_repositories, NOT NULL):
    Where results live (git repo, always auto-created in Gitea)

results_repositories (NEW):
  id (PK)
  uri (unique, git repo URL)
  owned_by_federated_node (BOOLEAN)
    true = Gitea (federated-node managed)
    false = client GitHub (client manages)
  created_at, updated_at

results_backends (NEW):
  id (PK)
  project_id (FK → projects)
  type (ENUM: 'git' | 's3' | 'azure' | 'gcp')
    git: files committed directly to git repo
    s3/azure/gcp: files pushed via DVC, .dvc pointers committed to git
  config (JSON):
    git: {} (empty)
    s3: { "url": "s3://bucket/path", "access_key_id": "...", "secret_access_key": "..." }
    azure: { "url": "azure://container@account.blob.core.windows.net", "account_key": "..." }
    gcp: { "url": "gs://bucket/path", "projectname": "...", "credentials_json": {...} }
  created_at, updated_at
  
  Note: Validation happens at DB save time. Users provide complete config for DVC remote.
```

api_requests (NEW):
  id (PK)
  user_id
  project_id (FK)
  payload (JSON):
    {
      "docker_image": "model:v1.2.3",
      "params": {...},
      "metadata": {...}
    }
  created_at

tasks (UPDATED):
  id (PK)
  project_id (FK)
  trigger_source (STRING: 'PR' | 'API')

  -- Trigger references
  pr_repository_id (FK → trigger_repositories, nullable)
  pr_number (nullable)
  api_request_id (FK → api_requests, nullable)

  -- Execution spec (from PR or API)
  trigger_payload (JSON):
    {
      "docker_image": "model:v1.2.3",
      "params": {...},
      "metadata": {...}
    }

  -- DVC + S3 metadata
  s3_path (STRING: "s3://bucket/data/<hash>")
  data_hash (STRING: "<hash>")

  -- Git metadata (ALWAYS SET)
  git_commit_sha (STRING: "<sha>")

  -- Execution tracking
  status (STRING: 'scheduled' | 'running' | 'success' | 'failed' | 'retrying')
  dagster_run_id (STRING, unique)
  attempt (INT, default 1)

  created_at, updated_at
  started_at (nullable)
  completed_at (nullable)

  -- Keep for later (unused in MVP):
  name, docker_image, description, requested_by
  review_status, reviewed_by, reviewed_at
  dataset_id, params

-- REMOVED:
-- delivery_targets
-- task_deliveries
-- storage_providers
```

---

## Implementation Plan

### 1. **Database migrations** (~2-3 hours)

- [ ] Add to projects: `dvc_backend`, `dvc_config`, `results_repository_id` (NOT NULL)
- [ ] Create results_repositories table
- [ ] Create api_requests table
- [ ] Update tasks: add `s3_path`, `data_hash`, `git_commit_sha` (NOT NULL), `api_request_id`
- [ ] Drop delivery_targets, task_deliveries, storage_providers
- [ ] Add indexes: tasks(project_id, status), tasks(git_commit_sha)

### 2. **Project initialization** (~2-3 hours)

When a project is created:
- [ ] Check if results_repository_id is provided (client's GitHub)
- [ ] If not, auto-create in Gitea: `results-<project-id>`
- [ ] Store results_repository_id in projects table

**Gitea setup (one-time, ~1 day):**
- [ ] Helm chart deployment
- [ ] SSH key auth for Dagster service account
- [ ] Persistent storage (PVC)
- [ ] DNS/internal access
- [ ] Automated repo creation endpoint

### 3. **Webserver API** (~4-6 hours)

- [ ] Remove delivery_targets endpoints
- [ ] Remove task_deliveries endpoints
- [ ] Update projects API: accept `dvc_backend`, `dvc_config`, `results_repository_id`
- [ ] Add api_requests endpoint (POST /api/projects/{id}/api_requests)
- [ ] Update tasks API: return `s3_path`, `data_hash`, `git_commit_sha`
- [ ] Results repository management (if needed for client override)

### 4. **Dagster Results Transfer operation** (~8-10 hours)

Single op: `GithubTransferOperation` (handles all backend types)

**GithubTransferOperation flow:**

```python
def __call__(self):
  # 1. Setup context (extract project, backend type, paths)
  self._setup_context(project_id, pr_number, parent_run_id, repo_uri)
  
  # 2. Clone results repository
  self._setup_repo()
  
  # 3. Handle backend (dispatch on type)
  if self.project.results_backend.type == "git":
    # Git backend: nothing to do, files stay in artifact dir
    pass
  else:  # s3, azure, gcp
    # DVC backends: initialize, configure, add, push
    self._init_dvc()
    self._write_dvc_config()  # From project.results_backend.config
    self._dvc_add_and_push()
  
  # 4. Commit to git (same for all backends)
  self._commit_to_git()
    self._stage_backend_files()  # Copy raw files or .dvc files
    self._write_metadata()       # backend type, remote url, etc.
    self._git_commit_and_push()
  
  # 5. Create pull request
  self._create_results_pr()
  
  return pr_url
```

**Key insight:** No branching in the commit logic. Both backends stage their files, write metadata, and commit the same way.

**Key details:**
- [ ] DVC auth: inject from project.dvc_config as env vars
- [ ] Git auth: SSH keys mounted in pod from Kubernetes secret
- [ ] Error handling: fail if ANY step fails. Dagster retries entire job.
- [ ] Idempotency: dvc push is no-op if hash exists in S3
- [ ] Retries: git push retry logic (transient network failures)
- [ ] Cleanup: remove clone_dir when done

**Backend configuration:**
- User provides complete `.dvc/config` format in `project.results_backend.config`
- No URL building in code — user specifies full remote URL: `s3://bucket/path`, `azure://container@account`, `gs://bucket/path`
- Op just writes the config as-is, lets DVC handle the details
- Validation happens at database save time (ensure required fields are present for backend type)

Example user config for S3:
```json
{
  "url": "s3://my-bucket/results",
  "access_key_id": "AKIA...",
  "secret_access_key": "wJal..."
}
```

Example user config for Azure:
```json
{
  "url": "azure://results@myaccount.blob.core.windows.net",
  "account_key": "DefaultEndpointsProt..."
}
```

Op just writes this to `.dvc/config` and runs `dvc push`. DVC is the source of truth.

**File structure: Git repo organization (all backends)**

```
results-repo/
  results/
    owner/
      repo/
        20260925-145230-abc456/      (timestamp-run_uuid, chronologically sorted)
          metadata.json              (backend type, run info)
          [backend-specific files]
        20260925-150115-abc789/
          metadata.json
          [backend-specific files]
```

**Backend-specific file contents:**

**If backend type is "git":**
```
results/owner/repo/YYYYMMDD-HHMMSS-uuid/
  results.csv
  model.pkl
  metadata.json
```
Files committed directly to git. Metadata indicates `"backend": "git"`.

**If backend type is "s3/azure/gcp":**
```
results/owner/repo/YYYYMMDD-HHMMSS-uuid/
  results.csv.dvc        (pointer file, DVC metadata)
  model.pkl.dvc          (pointer file)
  metadata.json          (includes remote_url)
```
Files pushed to S3/Azure/GCP via DVC. `.dvc` files + metadata committed to git for audit trail.

**Why this structure:**
- Chronologically sorted (timestamp-first naming)
- "Latest" run = `ls | sort | tail -1`
- Flat structure, backend-agnostic
- Git repo is source of truth (same structure for all backends)
- Metadata tells you where data actually lives

**Why this structure:**
- Git has clean audit trail (browse task folders, see attempts, check what changed)
- S3 is human-readable for clients who browse directly (no `.dvc/cache/` complexity)
- DVC handles all backend logic (versioning, integrity, pushing)
- `metadata.json` lives in git for full context (task_id, trigger_source, timestamp, s3_path, data_hash)
- Compliance: "Show me task-001's results" → git log shows commit, git show shows .dvc files + metadata
- Client browsing S3 → sees `task-001/results.csv`, downloads directly

**Implementation in op:**
```python
# In dvc_push_and_commit, organize by timestamp + run_uuid:
from datetime import datetime
import uuid

task_id = task.id
attempt = task.attempt
trigger_time = task.created_at  # or trigger's received_at
run_uuid = task.dagster_run_id  # Dagster's unique run ID

# Format: YYYYMMDD-HHMMSS-<uuid>
timestamp_str = trigger_time.strftime("%Y%m%d-%H%M%S")
run_dir = f"{timestamp_str}-{run_uuid[:8]}"  # e.g., 20260925-145230-abc456

os.makedirs(run_dir, exist_ok=True)

# Copy/move results into run dir
for file in results_files:
  shutil.copy(file, f"{run_dir}/{file}")

# cd into run dir
os.chdir(run_dir)

# Configure DVC remote to store in this run's S3 path
project_path = f"{project.trigger_owner}/{project.trigger_repo}"
run_cmd(f"dvc remote add -d myremote s3://{project.dvc_config['bucket']}/{project_path}/{run_dir}")

# Add results to DVC (creates .dvc files)
run_cmd("dvc add .")

# Push to S3 (DVC pushes to s3://bucket/owner/repo/timestamp-uuid/)
run_cmd("dvc push")

# Extract s3 paths from .dvc files
data_hash = extract_hash_from_dvc_files()
s3_paths = extract_s3_paths_from_dvc_files()

# Create metadata.json
metadata_json = {
  "task_id": task_id,
  "attempt": attempt,
  "trigger_source": task.trigger_source,  # "PR" or "API"
  "trigger_payload": task.trigger_payload,
  "s3_path": f"s3://{project.dvc_config['bucket']}/{project_path}/{run_dir}",
  "data_hash": data_hash,
  "files": s3_paths,
  "timestamp": now_iso(),
}
with open("metadata.json", "w") as f:
  json.dump(metadata_json, f, indent=2)

# Commit all to git
os.chdir("..")
run_cmd("git add .")
run_cmd(f"git commit -m 'Task {task_id}: {timestamp_str}'")
run_cmd("git push origin main")
```

### 5. **Sensor updates** (~1-2 hours)

- [ ] PR sensor: already creates tasks, verify trigger_payload is set
- [ ] API handler: insert into api_requests, create task from it

### 6. **Testing** (~4-6 hours)

- [ ] E2E: trigger task (PR or API) → verify results in S3 + git commit
- [ ] Git retry: if git push fails, verify task retries successfully
- [ ] Gitea: verify auto-repo creation and SSH auth
- [ ] DVC idempotency: run twice, verify dvc push no-ops second time
- [ ] Metadata: verify metadata.json has all required fields

---

## Execution Timeline

| Day | Task | Hours | Status |
|-----|------|-------|--------|
| 1 | Migrations | 2-3 | DB schema |
| 1 | Project initialization | 2-3 | Auto Gitea repo on create |
| 1-2 | Webserver API | 4-6 | Endpoints for dvc_config, results_repo |
| 2-3 | Dagster op | 8-10 | dvc_push_and_commit with git |
| 3 | Sensor updates | 1-2 | Minimal changes |
| 3 | Testing | 4-6 | E2E verification |
| **Total** | | **21-30 hours** | **2-4 days** |

---

## Fallback Options (If Needed Later)

### Option A: DVC only (no git)

**If git becomes a blocker:**

```python
# Remove git block entirely
@dg.op
def dvc_push_only(context, task, results_dir, project):
  dvc_push(results_dir, project.dvc_config)

  return {
    "s3_path": s3_path,
    "data_hash": data_hash,
    # NO git_commit_sha
  }
```

**Changes needed:**
- [ ] Make results_repository_id nullable
- [ ] Make git_commit_sha nullable in tasks
- [ ] Replace dvc_push_and_commit with dvc_push_only op
- [ ] Add if-statement: "if results_repository_id: git_push()"

**Trade-offs:**
- ✅ Simpler (no git auth, no Gitea)
- ❌ No immutable audit trail (DB rows are mutable)
- ❌ Compliance gets harder (no git log)

**Effort:** 2-3 hours (already structured for this)

---

### Option B: Skip Gitea, use GitHub only

**If Gitea ops becomes too much:**

```python
# Same dvc_push_and_commit, just different git_repo.uri
# results_repository_id always points to GitHub

results_repo = github_client.get_repo(project.github_results_repo_id)
# Rest is identical
```

**Changes needed:**
- [ ] Remove Gitea auto-creation logic
- [ ] Require client to provide GitHub results repo
- [ ] Update project creation: accept github_results_repo_id

**Trade-offs:**
- ✅ No Gitea to run/manage
- ✅ Audit trail in GitHub (industry standard)
- ❌ Depends on client having GitHub
- ❌ Slightly higher auth complexity (GitHub tokens)

**Effort:** 1-2 hours (same op, just different git_repo source)

---

### Option C: Zip files (no DVC, no git)

**If DVC becomes complex:**

```python
# Skip DVC entirely
@dg.op
def push_results_zip(context, task, results_dir, project):
  # Create zip
  zip_path = shutil.make_archive(results_dir, 'zip')

  # Add metadata
  with zipfile.ZipFile(zip_path, 'a') as z:
    z.writestr('metadata.json', json.dumps(metadata))

  # Upload to S3
  data_hash = hash_file(zip_path)
  s3_upload(zip_path, f"s3://{bucket}/task-{task.id}.zip")

  return {"s3_path": s3_path, "data_hash": data_hash}
```

**Trade-offs:**
- ✅ No DVC overhead
- ✅ No git operations
- ❌ No deduplication (duplicate files = duplicate uploads)
- ❌ No versioning (one zip per task, immutable)

**Effort:** 2-3 hours (completely different op)

---

## FAQ

**Q: Why is git mandatory?**
A: Audit trail. Every result has an immutable commit history. Compliance asks for it, clients want reproducibility, and it's free versioning.

**Q: Why Gitea if GitHub works?**
A: Clients without GitHub. Fallback for organizations that can't/won't use GitHub.

**Q: What if dvc push fails?**
A: Dagster job fails. Task marked as retrying. On retry, dvc push is idempotent (file already in S3, no-op). Git push still happens.

**Q: What if git push fails?**
A: Dagster job fails. Task marked as retrying. On retry, git push succeeds (or keeps failing). Dagster keeps retrying per job policy.

**Q: Where does metadata live?**
A: Database (tasks table) + git (metadata.json) + S3 (hash, implicit versioning).

**Q: How do clients get results?**
A: S3 path in database, or clone git repo for full history + metadata.

**Q: Do we need the .dvc file?**
A: Locally, yes (DVC needs it to know what to push). After push, metadata lives in database + git.

**Q: What's the data flow for retries?**
A: Same task row. Increment attempt. Update dagster_run_id and git_commit_sha. Full history in git (one commit per attempt).

**Q: Can a client override the results repo?**
A: Yes. When creating project, accept results_repository_id. Default = auto-created Gitea repo.

---

## Implementation Checklist

- [ ] Remove delivery_targets, task_deliveries, storage_providers tables
- [ ] Add dvc_backend, dvc_config to projects (required)
- [ ] Make results_repository_id required on projects (default to auto-create)
- [ ] Add git_commit_sha to tasks (required)
- [ ] Create api_requests table + endpoint
- [ ] Write dvc_push_and_commit op (the big one)
- [ ] Setup Gitea (Helm chart) or skip and use GitHub
- [ ] E2E test: PR trigger → S3 + git
- [ ] E2E test: API trigger → S3 + git
- [ ] Deploy and monitor

---

## Future Architecture: Trigger Abstraction

**Post-MVP refactor (when adding more trigger types):**

Instead of scattered trigger sensors, use a `Trigger` interface pattern:

```python
from abc import ABC, abstractmethod

class Trigger(ABC):
    @abstractmethod
    def get_pending_items(self):
        """Fetch unprocessed items from source"""
        pass
    
    @abstractmethod
    def make_run_request(self, item):
        """Transform item into Dagster RunRequest with tags"""
        pass

class PullRequestTrigger(Trigger):
    def __init__(self, backend_api, github_api):
        self.backend_api = backend_api
        self.github_api = github_api
    
    def get_pending_items(self):
        return self.backend_api.get_pull_requests(status=UNKNOWN)
    
    def make_run_request(self, pr):
        # Extract spec from GitHub, validate, create RunRequest
        # Set tags: trigger=github, pr_number=..., etc.
        pass

class ApiRequestTrigger(Trigger):
    def __init__(self, backend_api):
        self.backend_api = backend_api
    
    def get_pending_items(self):
        return self.backend_api.get_api_requests(status=PENDING)
    
    def make_run_request(self, req):
        # Extract spec from payload, validate, create RunRequest
        # Set tags: trigger=api, request_id=..., etc.
        pass

class SQSTrigger(Trigger):
    """Future: trigger tasks from SQS queue"""
    def get_pending_items(self):
        return self.sqs.receive_messages()
    
    def make_run_request(self, msg):
        # Extract spec from message, validate, create RunRequest
        pass

# Unified sensor (one code path for all triggers)
class UnifiedTriggerSensor(BaseSensor):
    def __call__(self):
        triggers = [
            PullRequestTrigger(self.backend_api, self.github_api),
            ApiRequestTrigger(self.backend_api),
            # SQSTrigger(self.sqs),  # Add when needed
        ]
        
        for trigger in triggers:
            for item in trigger.get_pending_items():
                try:
                    run_request = trigger.make_run_request(item)
                    yield run_request
                except Exception as e:
                    self.log.error(f"Error processing {trigger.__class__.__name__}: {e}")
```

**Benefits:**
- One sensor code path (no if/else branching)
- Each trigger owns its logic (encapsulation)
- Easy to add SQS, webhooks, Kafka later (just implement Trigger interface)
- Testable (mock each trigger independently)

**MVP approach:** Ship with PullRequestTrigger + ApiRequestTrigger as concrete classes in sensor. Refactor to Trigger abstraction when adding SQS.

---

## Future Enhancements (Post-MVP)

### Multiple results destinations per project

**Not in MVP.** Current design: one results repo per project (git+DVC, mandatory).

**Why not now:**
- One code path is simpler, fewer bugs, faster to ship
- Multi-destination adds branching logic, retry complexity, state tracking per destination
- Clients can use git as audit trail; if they need S3-only, use fallback Option A (DVC-only)

**Post-MVP scope (if needed):**
- Add `delivery_destinations` table (type: 'git' | 's3' | 'azure')
- Each task delivery creates N rows (one per destination)
- Retry logic per destination (git failed, S3 succeeded = partial success)
- Task status: SUCCESS only if all destinations succeed, or PARTIAL_SUCCESS if some fail
- Estimated effort: 3-4 days (retries + state management)

**For now:** Ship single destination. Clients can ask post-launch if they need it.

---

## Scope Lock

This plan is intentionally **single-path and simple:**
- One results repo per project (required)
- One Dagster op (dvc_push_and_commit)
- No branching for different delivery types
- No multi-destination retry logic

**Complexity deferred:** Multi-destination, per-trigger overrides, conditional delivery — all post-MVP. Ship this, iterate after launch.

---

## Design Considerations

**Git+DVC is mandatory in MVP, but here are the trade-offs:**

**Concern 1: `.dvc/cache/` readability in S3**
- S3 has hash-based paths (`.dvc/cache/ab/cdef.../`) which are not human-readable
- **Resolution:** Clients don't browse S3 directly. They query the database for `task.s3_path`, or clone git and read `metadata.json`. The S3 structure is implementation detail.
- **Post-MVP escape:** If clients need direct S3 browsing, add a `delivery_type` project field and support DVC-only (human-readable paths) alongside git+DVC. Cost: 2-3 hours per new type.

**Concern 2: Complexity of optional backends**
- Multi-destination delivery (git+DVC, DVC-only, custom S3 paths) adds branching logic
- **Resolution:** Single path in MVP. Ship. Iterate. Multi-destination is deferred because one code path = fewer bugs, easier testing, faster shipping for a 2-person team.
- **Post-MVP escape:** Add `delivery_type` and conditional push operators. Already structured for this (see Future Enhancements).

**Concern 3: Git+DVC feels over-engineered for some use cases**
- Some clients may want "just push to S3, no git"
- **Resolution:** Git+DVC provides audit trail, compliance-friendly immutability, and versioning. Med tech needs this. Clients without this requirement can extract tarball backups (Gitea backup to S3).
- **Post-MVP escape:** Make results_repository_id optional. If null, skip git. Add `dvc_push_only` op. Cost: 2-3 hours.

**Decision:** Ship MVP with git+DVC mandatory. Flexibility is cheap post-launch. Simplicity now beats optionality.

---

## Operational Note: Gitea Backup to S3

**Optional:** Periodically sync Gitea repo to S3 for disaster recovery.

Cron job (daily):
```bash
cd /var/lib/gitea/git/repositories/federated-node/results-repo.git
tar -czf /tmp/gitea-backup-$(date +%Y-%m-%d).tar.gz .
aws s3 cp /tmp/gitea-backup-*.tar.gz s3://bucket/gitea-backups/
# Retain last 30 days
aws s3 rm s3://bucket/gitea-backups/ --recursive --exclude "*" --include "gitea-backup-*" --exclude "gitea-backup-$(date -d '30 days ago' +%Y-%m-%d)*"
```

**Result in S3:**
```
gitea-backups/
  gitea-backup-2026-09-24.tar.gz
  gitea-backup-2026-09-25.tar.gz
  gitea-backup-2026-09-26.tar.gz
```

**Client benefit:** If Gitea goes down, they can download tar from S3 and restore locally.

---

**Next Steps:** Migrations + webserver can run in parallel with Dagster op work. Start with database schema, then split frontend/backend implementation.
