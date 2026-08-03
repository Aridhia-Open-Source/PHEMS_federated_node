# Database Schema Plan: PHEMS Federated Pipeline

## Context & Architecture

**Goal:** Build a data ingestion pipeline triggered by GitHub pull requests, with results committed back to a delivery repository.

**Flow:**
1. PR merges in **TriggerRepository** → Dagster sensor polls and saves PR
2. Sensor fires job → reads source Dataset, processes changes
3. Results committed to **DeliveryRepository** → we save that PR too
4. Both trigger and delivery PRs tracked in same table (they're events in either repo)

**Key Design Decisions:**
- **Multiple datasets per project** (ideal future) — but MVP simplifies to 1 dataset per project
- **Datasets are reusable** across projects — foreign key from Project to Dataset, not exclusive
- **TriggerRepositories are reusable** — multiple projects can watch the same repo
- **DeliveryRepositories are single-owner** — each project has its own or can be shared (TBD)
- **PullRequests are generic events** — can originate from either trigger or delivery repo; no dataset_id (it broadcasts)
- **Project is the grouping** — ties together trigger repo, dataset, and delivery repo

---

## MVP Approach: Repository as Project Surrogate (Today's Implementation)

**Simplified for today:**
- **Repository** (with unique URI) acts as the project surrogate
- **PullRequest** tracks PR events (repository_id, number, status)
- **Dataset** linked to Repository (1:1)
- **DeliveryRepository** hardcoded/global for MVP

**Why this works:**
- Repository URI is already unique (natural 1:1 with "project")
- No new Project table needed
- PullRequest tracks status per-repo (sensor populates, Dagster updates)
- Dataset is owned by Repository (no ambiguity)
- Minimal schema changes from current broken state

**Future migration to full Project model:**
- Rename Repository → TriggerRepository
- Create Project table (wraps trigger_repo + dataset + delivery_repo)
- Create ProjectTask table (replaces/augments PullRequest)
- No schema changes needed to PullRequest for this transition

**This approach:**
- ✅ Gets it working today (least code)
- ✅ Sets up clean refactor path later
- ✅ PullRequest stays simple (just PR metadata + status)
- ✅ Dataset ownership is clear (belongs to Repository)

---

## MVP Schema (Now)

### REPOSITORY
Represents a GitHub repository being watched or written to.

```sql
repositories:
  id (Integer, PK, auto)
  uri (String 4096, unique)           -- github.com/org/repo (normalized, no https://)
  watch_dir (String 4096)              -- directory to monitor for changes
  base_branch (String 256, default='main')
  dataset_id (Integer, FK → datasets.id)  -- the dataset this repo ingests into
  initial_cursor (DateTime)            -- "start pulling PRs from this time"
  created_at (DateTime, auto)
  updated_at (DateTime, auto)
```

**Why:**
- `uri` is unique because we only track one watch per GitHub repo
- `dataset_id` is direct FK (1:1) — no ambiguity, no defaults
- `initial_cursor` is immutable once PRs exist (prevents accidental replays)
- MVP: acts as project surrogate (unique Repository = unique Project)

---


---

### DATASET
The actual database(s) being read from and written to.

```sql
datasets:
  id (Integer, PK, auto)
  name (String 256, unique)
  host (String 256)
  port (Integer, default=5432)
  schema (String 256, nullable)
  schema_write (String 256, nullable)
  type (String 256, default='postgres')
  extra_connection_args (String 4096, nullable)
  created_at (DateTime, auto)
  updated_at (DateTime, auto)
```

**Why:**
- No FK back to Repository (keep it simple, reverse relationship via Repository.dataset_id)
- Minimal, single-purpose — just connection details
- MVP: 1:1 with Repository (repository.dataset_id points here)
- Future: can be reusable across projects (when Project table exists, M:N via join table)

---

### PULL_REQUEST
Tracks merged PRs from watched repositories.

```sql
pull_requests:
  repository_id (Integer, PK part 1, FK → repositories.id, ondelete=CASCADE)
  number (Integer, PK part 2)                 -- GitHub PR number (unique per repo)
  title (String 256)
  raised_by (String 256)
  merged_at (DateTime)
  saved_at (DateTime, auto)
  status (String 32, default='UNKNOWN')       -- UNKNOWN, STARTED, SUCCESS, FAILED
  merge_commit_sha (String 40)
  spec (JSON)                                 -- arbitrary PR metadata/payload
  
  Composite PK: (repository_id, number)
  Index: (repository_id, status)
```

**Why:**
- Composite PK `(repo_id, number)` guarantees one PR per repo
- `status` tracks processing state (UNKNOWN → STARTED → SUCCESS/FAILED)
- `spec` holds arbitrary PR metadata for Dagster job
- Repository is the project surrogate (unique URI = unique project)

**Sensor flow (MVP):**
```
1. Poll Repository for merged PRs
2. Save PR: INSERT pull_requests(repository_id, number, title, ..., status='UNKNOWN')
3. Dagster job queries: SELECT * FROM pull_requests WHERE status='UNKNOWN'
4. Job processes, updates: UPDATE pull_requests SET status='STARTED'/'SUCCESS'/'FAILED'
5. Later: rename to delivery_repo when creating Project table
```

---

## Why This Works for MVP→Future

| Concern | MVP | Future |
|---------|-----|--------|
| Project grouping | Repository URI (1:1) | Proper Project table wraps Repository |
| PR status tracking | Per-repo (repository_id, number) | Same — no changes to PullRequest |
| Dataset ownership | Repository → Dataset (1:1) | Project → Dataset (1:N via join table) |
| Repository reuse | Not yet (1:1 in MVP) | Easy refactor when Project table exists |
| Sensor logic | Simple: save PRs to repository | Same: save PRs, Dagster reads status |

**The clean part:** PullRequest schema doesn't change when you add Project later. Only the relationships change (Repository becomes part of Project). Zero data migration on pull_requests table.

---

## Migration Path: Repository → Project Model

**Today (MVP):**
- Repository = project surrogate (unique URI)
- PullRequest tracks PR events + status

**Later (When you need multi-repo project support):**

1. Rename `repositories` → `trigger_repositories`
2. Create `projects` table:
   ```sql
   projects:
     id, name, trigger_repository_id (FK), dataset_id (FK), delivery_repository_id (FK), status, owner, created_at, updated_at
   ```
3. Create `project_pull_requests` join table:
   ```sql
   project_pull_requests:
     project_id (FK), pull_request_id (FK), status, created_at, updated_at
   ```
4. No changes needed to core `pull_requests` schema

This is a clean refactor path because PullRequest stays simple throughout.

---

## Open Questions for Implementation

1. **PR.spec contents** — what metadata from GitHub API? (full changeset, diff links, etc.)
2. **Sensor polling frequency** — how often to check TriggerRepository for new PRs?
3. **Delivery repo reference** — hardcoded as constant, or config var, or DB lookup?
