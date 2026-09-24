# DVC + Gitea Results Delivery Plan (MVP)

## TL;DR (30 seconds)

**Primary model:** Every task's results go to S3/Azure via DVC, then commit metadata to git (Gitea or client's GitHub).

**One code path (always):** `dvc add → dvc push → git commit → git push`

**Git handling:**
- Default: auto-created repo in Gitea (federated-node owned)
- Advanced: client provides their own GitHub repo
- No option to skip (git is required for audit trail)

**Implementation summary:** Rip out delivery_targets/task_deliveries/storage_providers. Add dvc_backend + dvc_config to projects. Make results_repository_id required (default to auto-created). Single dvc_push_and_commit op in Dagster. Done.

---

## Architecture (Single Path)

### The flow (always the same):

```
Experiment runs (Dagster job)
  ↓
Results produced (results.csv, model.pkl, logs.txt)
  ↓
dvc add results.*
  (creates .dvc files locally)
  ↓
dvc push → S3/Azure
  (uploads to s3://bucket/data/<hash>)
  ↓
[MANDATORY] Git commit:
  - Clone results repo (Gitea or GitHub)
  - Create metadata.json with full context
  - Commit results.*.dvc + metadata.json
  - Push to git
  ↓
[ALWAYS] Update database:
  - tasks.s3_path = "s3://bucket/data/<hash>"
  - tasks.data_hash = "<hash>"
  - tasks.git_commit_sha = "<sha>"
  - tasks.status = "success"
  ↓
Done. Audit trail in git, data in S3, metadata in both.
```

### Why this works:

- **One code path:** No branching (if/else for git). Simpler, less error-prone.
- **Audit trail guaranteed:** Every result has a git commit (immutable, tamper-proof).
- **Compliance friendly:** "Show me git log, prove data was stored." Done.
- **No extra infra for simple case:** Gitea is optional; GitHub works fine.
- **Metadata bundled:** metadata.json lives in git alongside .dvc pointer.

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
  + dvc_backend (STRING: 's3' | 'azure', required)
  + dvc_config (JSON, required):
    {
      "bucket": "my-bucket",
      "region": "us-east-1",
      "auth_method": "env_vars" | "credentials",
      "access_key_id": "...",
      "secret_access_key": "..."
    }
  + results_repository_id (FK → results_repositories, NOT NULL)
    → Default: auto-created repo in Gitea
    → Override: client provides GitHub repo

results_repositories (NEW):
  id (PK)
  uri (unique, git repo URL)
  owned_by_federated_node (BOOLEAN)  # true = Gitea, false = client GitHub
  created_at, updated_at

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

### 4. **Dagster DVC + Git operation** (~8-10 hours)

Single op: `dvc_push_and_commit` (always runs, no branching)

```python
@dg.op
def dvc_push_and_commit(context, task, results_dir, project, metadata):
  """
  Push results to S3 via DVC.
  Commit metadata to git (Gitea or client GitHub).
  No branching — git is always involved.
  """

  # 1. Initialize DVC
  os.chdir(results_dir)
  run_cmd("dvc init --no-scm")

  # 2. Add results to DVC
  run_cmd("dvc add .")

  # 3. Push to S3/Azure
  # Set auth from project.dvc_config
  set_env_vars(project.dvc_config)
  run_cmd("dvc push")

  # 4. Extract metadata from .dvc files
  data_hash = extract_hash_from_dvc_files(results_dir)
  s3_path = f"s3://{project.dvc_config['bucket']}/task-{task.id}/{data_hash}"

  # 5. Clone results repo (Gitea or GitHub)
  results_repo = results_repositories.get(project.results_repository_id)
  clone_dir = f"/tmp/results-{task.id}"
  git_clone(results_repo.uri, clone_dir, ssh_key)

  # 6. Create metadata.json
  metadata_json = {
    "task_id": task.id,
    "trigger_source": task.trigger_source,
    "trigger_payload": task.trigger_payload,
    "status": "success",
    "attempt": task.attempt,
    "s3_path": s3_path,
    "data_hash": data_hash,
    "timestamp": now_iso(),
  }

  with open(f"{clone_dir}/metadata.json", "w") as f:
    json.dump(metadata_json, f, indent=2)

  # 7. Commit everything
  os.chdir(clone_dir)
  run_cmd("git add .")
  commit_msg = f"Task {task.id}: {task.trigger_source} trigger\n\n{data_hash[:8]}"
  run_cmd(f"git commit -m '{commit_msg}'")
  run_cmd("git push origin main")

  # 8. Get commit SHA
  git_commit_sha = run_cmd("git rev-parse HEAD").strip()

  # 9. Return result
  return {
    "s3_path": s3_path,
    "data_hash": data_hash,
    "git_commit_sha": git_commit_sha,
  }
```

**Key details:**
- [ ] DVC auth: inject from project.dvc_config as env vars
- [ ] Git auth: SSH keys mounted in pod from Kubernetes secret
- [ ] Error handling: fail if ANY step fails. Dagster retries entire job.
- [ ] Idempotency: dvc push is no-op if hash exists in S3
- [ ] Retries: git push retry logic (transient network failures)
- [ ] Cleanup: remove clone_dir when done

**Important: DVC remote is provider-agnostic**
- `.dvc` files store only the data hash, not the storage provider
- `.dvc/config` does NOT need to be in the git repo (keep it in .gitignore or skip entirely)
- Configure DVC remote at runtime:
  ```python
  # Inject credentials from project.dvc_config as env vars
  os.environ['AWS_ACCESS_KEY_ID'] = project.dvc_config['access_key_id']
  os.environ['AWS_SECRET_ACCESS_KEY'] = project.dvc_config['secret_access_key']

  # Add remote dynamically (no .dvc/config needed)
  run_cmd(f"dvc remote add -d myremote s3://{project.dvc_config['bucket']}")

  # dvc push uses env vars + runtime remote config
  run_cmd("dvc push")
  ```
- This way, `.dvc` files are truly provider-agnostic and portable. Storage location is determined by runtime config, not hardcoded in the repo.

**File structure: Human-readable git + human-readable S3**

Git results repo (audit trail, human-readable):
```
results-repo/
  task-001/
    results.csv.dvc        (pointer file, DVC metadata)
    model.pkl.dvc          (pointer file)
    metadata.json          (task context)
  task-002/
    results.csv.dvc
    model.pkl.dvc
    metadata.json
```

S3 bucket (human-readable, client-browsable):
```
s3://bucket/
  task-001/
    results.csv            (actual file, pushed by DVC)
    model.pkl
  task-002/
    results.csv
    model.pkl
```

**Why this structure:**
- Git has clean audit trail (browse task folders, see attempts, check what changed)
- S3 is human-readable for clients who browse directly (no `.dvc/cache/` complexity)
- DVC handles all backend logic (versioning, integrity, pushing)
- `metadata.json` lives in git for full context (task_id, trigger_source, timestamp, s3_path, data_hash)
- Compliance: "Show me task-001's results" → git log shows commit, git show shows .dvc files + metadata
- Client browsing S3 → sees `task-001/results.csv`, downloads directly

**Implementation in op:**
```python
# In dvc_push_and_commit, organize by task:
task_id = task.id
attempt = task.attempt
task_dir = f"task-{task_id:03d}"

os.makedirs(task_dir, exist_ok=True)

# Copy/move results into task dir
for file in results_files:
  shutil.copy(file, f"{task_dir}/{file}")

# cd into task dir
os.chdir(task_dir)

# Configure DVC remote to store in this task's S3 path
run_cmd(f"dvc remote add -d myremote s3://{project.dvc_config['bucket']}/{task_dir}")

# Add results to DVC (creates .dvc files)
run_cmd("dvc add .")

# Push to S3 (DVC pushes to s3://bucket/task-{task_id}/)
run_cmd("dvc push")

# Extract s3 paths from .dvc files
data_hash = extract_hash_from_dvc_files()
s3_paths = extract_s3_paths_from_dvc_files()  # e.g., s3://bucket/task-001/results.csv

# Create metadata.json
metadata_json = {
  "task_id": task_id,
  "attempt": attempt,
  "s3_path": f"s3://{project.dvc_config['bucket']}/{task_dir}",
  "data_hash": data_hash,
  "files": s3_paths,
  "timestamp": now_iso(),
}
with open("metadata.json", "w") as f:
  json.dump(metadata_json, f, indent=2)

# Commit all to git
os.chdir("..")
run_cmd("git add .")
run_cmd(f"git commit -m 'Task {task_id}: attempt {attempt}'")
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
