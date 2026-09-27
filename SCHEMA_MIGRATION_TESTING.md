# Schema Migration Testing Guide

## Overview

The webserver database schema has been migrated to support the new results-delivery architecture:
- ✅ Models moved from `models_v2/` to `models/` (canonical location)
- ✅ New tables: `results_repositories`, `results_backends`, `api_requests`
- ✅ Updated tables: `projects` (+ results_repository_id), `tasks` (+ 4 new fields)
- ✅ Legacy tables removed: `delivery_targets`, `task_deliveries`
- ✅ Baseline migration created: `webserver/migrations/versions/001_baseline.py`
- ✅ API endpoints implemented: GET /tasks/health (integration test), GET/POST /tasks, GET /tasks/{id}

## Deployment & Testing Steps

### Step 1: Start Kind Cluster
```bash
make cluster up
```
This will:
- Create a Kind cluster named `fn` (default, configurable via `CLUSTER_NAME`)
- Start Docker registries (localhost:5001, 5002, 5003)
- Set up local PVs at `$HOME/.fn/data` (configurable via `FN_DATA_DIR`)

### Step 2: Deploy Helm Release
```bash
make deploy
```
This will:
- Reconcile PersistentVolumes
- Deploy the Federated Node Helm chart
- Run Alembic migrations (applies `001_baseline.py`)
- Start all services: PostgreSQL, webserver, Dagster, etc.

**Check deployment status:**
```bash
kubectl get pods -n fn
kubectl get pvc -n fn
```

### Step 3: Verify Schema Migration
Once the webserver pod is running, check the integration test endpoint:

```bash
# Port-forward to the webserver (if not already done)
kubectl port-forward -n fn svc/federatednode-webserver 5000:5000 &

# Test the health endpoint (no auth required)
curl http://localhost:5000/tasks/health
```

**Expected response:**
```json
{
  "status": "healthy",
  "database": "connected",
  "tables": 15,
  "new_tables": ["results_repositories", "results_backends", "api_requests"],
  "legacy_tables_found": [],
  "schema_version": "baseline",
  "message": "DB schema migrated successfully"
}
```

### Step 4: Run Schema Integration Tests
In the cluster or locally with DB access:

```bash
cd webserver

# Run the schema integration test suite
python -m pytest tests/test_schema_integration.py -v

# Or run all tests
python -m pytest tests/ -v -k schema
```

**Test coverage:**
- ✓ New tables exist (results_repositories, results_backends, api_requests)
- ✓ Legacy tables removed (delivery_targets, task_deliveries)
- ✓ Task model has new fields (api_request_id, git_commit_sha, results_path, trigger_payload)
- ✓ Project model has results_repository_id FK
- ✓ All models import correctly
- ✓ Model relationships wired correctly
- ✓ BackendType enum defined (git, s3, azure, gcp)
- ✓ Timestamps standardized (created_at, updated_at)

### Step 5: Live Development with Tilt
For local code changes with live reload:

```bash
# Prerequisites: cluster already deployed, services running
make tilt-up
```

This will:
- Watch webserver code for changes
- Rebuild and restart on code updates
- Access dashboard at: http://localhost:10350

**Testing endpoints with Tilt running:**
```bash
# GET service info (requires auth - will get 401 without token)
curl -H "Authorization: Bearer <token>" http://localhost:5000/tasks/service-info

# Test health (no auth required)
curl http://localhost:5000/tasks/health

# List tasks (requires auth, returns empty list initially)
curl -H "Authorization: Bearer <token>" http://localhost:5000/tasks
```

### Step 6: Cleanup
```bash
# Stop Tilt (if running)
make tilt-down

# Stop cluster and services
make cluster down

# Remove everything including registries
make cluster down --remove-registries
```

---

## What to Verify After Migration

### Database Schema
- [ ] Run: `kubectl exec -it fn-postgres-0 -n fn -- psql -U postgres -d federated_node -c "\dt"`
- [ ] Verify 15 tables exist (13 existing + 3 new)
- [ ] Verify delivery_targets, task_deliveries NOT in list

### New Models Loaded
- [ ] Run: `python -c "from app.models import *; print('✓ All models load')"` in webserver container
- [ ] Or: Run pytest suite: `python -m pytest tests/test_schema_integration.py::TestSchemaMigration -v`

### API Endpoints Working
- [ ] GET /tasks/health returns {"status": "healthy"}
- [ ] GET /tasks/service-info returns service info (requires auth)
- [ ] GET /tasks returns paginated list (requires auth)
- [ ] POST /tasks creates a new task (requires auth)
- [ ] GET /tasks/{id} returns task details (requires auth)

### Results Delivery Integration
- [ ] Project can be created with `results_repository_id` (nullable)
- [ ] ResultsBackend can be created with `type` and `config` validation
- [ ] Task can be created with `api_request_id`, `git_commit_sha`, `results_path`, `trigger_payload`
- [ ] Transfer op can access `task.trigger_payload` and `project.results_backend.type`

---

## Migration Rollback (if needed)

The migration was created as a baseline (no down_revision), so:

```bash
# To rollback to before-migration state
alembic downgrade base

# This will drop all tables (destructive)
# After rollback, only the _alembic_version table remains
```

**Note:** Since this is a fresh baseline, there's no prior schema to roll back to. The downgrade is mostly for documentation. In production, keep backups before applying migrations.

---

## Troubleshooting

### Pod fails to start after migration
```bash
# Check logs
kubectl logs -n fn deployment/federatednode-webserver

# Common issues:
# 1. Migration syntax error - check 001_baseline.py
# 2. Model import error - check app/models/__init__.py
# 3. DB connection error - verify PostgreSQL pod is running
```

### Schema mismatch between code and DB
```bash
# Full schema reset (destructive - only for dev)
kubectl exec -it fn-postgres-0 -n fn -- psql -U postgres -d federated_node -c "DROP SCHEMA public CASCADE; CREATE SCHEMA public;"

# Then redeploy to re-run migration
make deploy
```

### Tilt not picking up code changes
```bash
# Restart Tilt
make tilt-down
make tilt-up

# Or manually rebuild webserver image
docker build -t localhost:5001/webserver-fn:dev webserver/
kubectl rollout restart deployment/federatednode-webserver -n fn
```

---

## Next Steps (Phase 2)

Once schema migration is verified:

1. **Sensor Wiring** (Dagster changes) — Re-point run_status_sensors to Task.status
2. **Endpoint Implementation** — Complete POST /tasks/cancel, GET /tasks/results, etc.
3. **Results Delivery** — Integrate transfer_op with new TaskResult model
4. **Approval Workflow** — Implement /tasks/{id}/results/approve|block endpoints

See `COMMON_API_TASK_SPEC.md` for detailed Phase 2+ planning.
