# UC1 Cardiac Benchmarking - Setup & Testing Guide

This guide walks through setting up and testing the UC1 (Use Case 1) cardiac benchmarking pipeline using the PHEMS federated node's GitHub PR-triggered Dagster pipeline.

## Architecture Overview

```
GitHub PR (with spec.json)
    ↓
Dagster pull_request_trigger_sensor
    ↓
k8s_pipes_op (reads dataset secret + config)
    ↓
uc1 Docker image + entrypoint (builds CONNECTION_STRING)
    ↓
Rscript CodeToRun.R (UC1 cardiac analysis)
    ↓
Results → /mnt/dagster/artifacts/{run_id}/results/
    ↓
github_transfer_job (posts results back to PR)
```

## Prerequisites

- Kubernetes cluster running (via Tilt or k3d)
- kubectl configured and pointing to the cluster
- Docker with access to local registry `localhost:5001`
- Python 3.8+ with psycopg2: `pip install psycopg2-binary`
- Access to the target GitHub repository

## Workflow Overview

```
STEP 1: K8s/Helm Deployment (./scripts/deploy.sh)
  ├─ Creates db-datasets Postgres instance
  ├─ Creates k8s secrets (db-datasets-superuser, db-datasets-uc1)
  ├─ Deploys db-datasets-init Job (creates uc1_omop database + user)
  └─ Status: Empty database, ready for seeding

STEP 2: Seed OMOP Data (./scripts/setup_uc1.sh) ← Local/Post-Deployment
  ├─ Reads PGPASSWORD from environment
  ├─ Creates OMOP CDM schema (person, visits, procedures, etc.)
  ├─ Seeds synthetic data (100 patients, visits, conditions)
  └─ Status: Database ready for analysis

STEP 3: Register with Backend API (cd dbseed && python3 seed_backend.py) ← Local/Post-Deployment
  ├─ Requires kubectl access to load dagster system creds
  ├─ Creates Dataset record in webserver DB
  ├─ Creates Repository record linked to Dataset
  └─ Status: Ready for PR-triggered runs

STEP 4: Trigger via GitHub PR
  ├─ Create PR with specs/uc1-spec.json
  ├─ Merge to trigger k8s_pipes_job
  └─ Monitor in Dagster UI
```

## Step 1: Deploy db-datasets Infrastructure

The db-datasets is a separate, dedicated Postgres instance that will host the UC1 OMOP database (and potentially other use-case databases in the future).

**Note:** This step creates an empty database. Seeding happens in Step 2 (post-deployment).

### 1a. Ensure .dev.env is configured

Copy `.dev.env.example` to `.dev.env` and fill in passwords:

```bash
cp .dev.env.example .dev.env
# Edit .dev.env and set:
# DATASET_DB_SUPERUSER_PASSWORD=<strong-password>
# DATASET_DB_UC1_PASSWORD=<strong-password>
```

### 1b. Deploy the full federated node stack (includes db-datasets)

```bash
./scripts/deploy.sh
```

This creates the k8s infrastructure only. The database is empty at this point. This will:
- Create k8s namespace `fn`
- Create all required secrets (including db-datasets-superuser and db-datasets-uc1)
- Deploy Helm chart with db-datasets Deployment, Service, PVC, and init Job
- Wait for db-datasets Pod to be ready

Verify db-datasets is running:

```bash
kubectl get pods -n fn | grep db-datasets
kubectl logs -n fn -f deployment/db-datasets  # Watch startup
```

## Step 2: Build UC1 Docker Image

```bash
./scripts/build_all_images.sh v1
```

Or build just UC1:

```bash
./scripts/build_image.sh uc1 v1
```

This builds from `uc1/Dockerfile` and pushes to `localhost:5001/uc1-fn:v1`.

Verify:

```bash
docker images | grep uc1-fn
```

## Step 3: Prepare Environment Variables

The UC1 setup requires the same database password in two places. Copy the password value:

**From .dev.env:**
```bash
DATASET_DB_UC1_PASSWORD=<your-password>
```

**To dbseed/.env:**
```bash
DATASET_PASSWORD=<your-password>  # Must be the SAME value as DATASET_DB_UC1_PASSWORD
```

Both must match for the seed.py registration to work with the database created by deploy.sh.

## Step 4: Create OMOP Schema and Seed Data

Run the seeding script locally (creates schema and seeds synthetic data only):

```bash
# From repo root, use the SAME password you just put in dbseed/.env
DATASET_PASSWORD="<DATASET_DB_UC1_PASSWORD>" ./scripts/setup_uc1.sh
```

This script:
- Creates OMOP CDM tables in the uc1_omop database
- Generates 100 synthetic patients with visits, procedures, conditions
- **Does NOT** interact with the backend API

Alternatively, manually:

### Option A: Using the setup script (recommended)

```bash
DATASET_PASSWORD="<your-uc1-password>" \
  REPO_URI="github.com/Aridhia-Open-Source/phems-sandbox" \
  REPO_WATCH_DIR="specs" \
  NUM_PATIENTS=100 \
  ./scripts/setup_uc1.sh
```

### Option B: Manual steps

1. **Create schema:**

```bash
PGPASSWORD="<DATASET_DB_UC1_PASSWORD>" psql \
  -h db-datasets.fn.svc \
  -p 5432 \
  -U uc1_omop_user \
  -d uc1_omop \
  -f dbseed/seed_uc1_schema.sql
```

2. **Seed data:**

```bash
python3 dbseed/seed_uc1_data.py \
  --host db-datasets.fn.svc \
  --port 5432 \
  --user uc1_omop_user \
  --password "<DATASET_DB_UC1_PASSWORD>" \
  --dbname uc1_omop \
  --num-patients 100
```

3. **Register Dataset and Repository via Backend API (Post-Deployment)**

After the OMOP database is seeded, register it with the backend API:

Set up `dbseed/.env`:

```bash
cat > dbseed/.env << EOF
BACKEND_API_URI=http://localhost:5000
REPO_URI=github.com/Aridhia-Open-Source/phems-sandbox
REPO_WATCH_DIR=specs
REPO_BRANCH=main
REPO_INITIAL_CURSOR=2019-05-01T00:00:00
DATASET_NAME=uc1_omop
DATASET_HOST=db-datasets.fn.svc
DATASET_PORT=5432
DATASET_USERNAME=uc1_omop_user
DATASET_PASSWORD=<DATASET_DB_UC1_PASSWORD>
DATASET_SCHEMA=public
DATASET_TYPE=postgres
REQUEST_USER_ID=system@phems.local
REQUEST_PROJECT_NAME=UC1-Cardiac-Benchmarking
REQUEST_TITLE=UC1 Cardiac Benchmarking
REQUEST_DESCRIPTION=Synthetic OMOP data for UC1 testing
REQUEST_START_DATE=2019-05-01T00:00:00
REQUEST_END_DATE=2030-12-31T00:00:00
EOF
```

Then run seed script:

```bash
cd dbseed && python3 seed_backend.py
```

## Step 4: Trigger UC1 via GitHub PR

### 4a. Create a PR in your trigger repository

1. Fork or clone: `github.com/Aridhia-Open-Source/phems-sandbox` (or whatever `REPO_URI` is configured)
2. Create a new branch: `git checkout -b test/uc1-trigger`
3. Create `specs/uc1-spec.json`:

```json
{
  "spec": {
    "docker_image": "localhost:5001/uc1-fn:v1",
    "env": {}
  }
}
```

4. Commit and push:

```bash
git add specs/uc1-spec.json
git commit -m "Trigger UC1 cardiac analysis"
git push origin test/uc1-trigger
```

5. Create a Pull Request on GitHub
6. **Merge the PR** — this triggers the pipeline

### 4b. Monitor in Dagster UI

1. Access Dagster: `http://localhost:3000` (or configured URI)
2. Navigate to Runs
3. Look for a new run with:
   - `trigger: github` tag
   - `pr_number: <your-pr-number>` tag
   - Job: `k8s_pipes_job`

4. Watch the run progress:
   - QUEUED → STARTED → SUCCESS/FAILURE
   - Status updates post back to GitHub as comments

### 4c. Retrieve Results

Once the run completes (SUCCESS status), results are in:

```
Artifacts → {run_id} → results/
```

Expected output files:
- `results_uc1_omop_{date}.csv` — summarized cardiac benchmarking results
- `pypipes.log` — container logs (if using test image)

## Troubleshooting

### Dataset-db Pod not starting

```bash
kubectl logs -n fn deployment/db-datasets
kubectl describe pod -n fn -l app=dataset-postgres
```

Check that secrets exist:

```bash
kubectl get secrets -n fn | grep db-datasets
```

### Seed script fails: "Connection refused"

- Verify db-datasets Service is running: `kubectl get svc -n fn db-datasets`
- For local testing, port-forward the database:

```bash
kubectl port-forward -n fn svc/db-datasets 5432:5432 &
# Then use --host localhost in seed scripts
```

### UC1 image fails to build

```bash
docker build uc1/ -t localhost:5001/uc1-fn:v1
docker push localhost:5001/uc1-fn:v1
```

Check Dockerfile and entrypoint:

```bash
ls -la uc1/
cat uc1/Dockerfile
cat uc1/entrypoint.sh
```

### Run fails with "secret not found"

Verify the k8s secret exists in the task namespace:

```bash
kubectl get secret -n fn db-datasets-uc1 -o yaml
```

Secret should have `password` key (base64-encoded).

### Run fails with "CONNECTION_STRING build error"

Check pod logs:

```bash
kubectl logs -n fn <pod-name> -c main
```

The entrypoint.sh script should be readable from `/app/entrypoint.sh` in the container.

## Testing Variations

### Change number of synthetic patients

```bash
DATASET_PASSWORD="..." NUM_PATIENTS=200 ./scripts/setup_uc1.sh
```

Then re-trigger via PR.

### Add custom environment variables

Edit the spec.json in your PR:

```json
{
  "spec": {
    "docker_image": "localhost:5001/uc1-fn:v1",
    "env": {
      "MY_VAR": "value"
    }
  }
}
```

These are passed to the container as env vars (accessible via `Sys.getenv()` in R).

### Test against a real dataset

After confirming the pipeline works with synthetic data, you can:

1. Update the Dataset record in the backend to point to a real OMOP database
2. Or create a second dataset entry for production data and a second Repository entry (with different dataset_id)

## Next Steps

Once UC1 is working end-to-end:

1. **Validate outputs** — compare cardiac benchmarking results against known expected values
2. **Optimize performance** — adjust R package versions, memory limits, execution timeout
3. **Add UC2, UC3, etc.** — follow the same pattern (separate dataset, separate Dockerfile, separate spec.json)
4. **Integrate with CI/CD** — automate spec.json generation from upstream project changes
5. **Monitor in production** — set up alerting for failed runs, log aggregation, result delivery tracking

## Key Files

| File | Purpose |
|------|---------|
| `uc1/Dockerfile` | R image with OMOP packages |
| `uc1/entrypoint.sh` | Builds CONNECTION_STRING from secrets + env |
| `uc1/OMOP_data_wrangle/CodeToRun.R` | Main analysis script |
| `k8s/federated-node/templates/db-datasets-*.yaml` | K8s manifests for db-datasets |
| `dbseed/seed_uc1_schema.sql` | OMOP schema DDL |
| `dbseed/seed_uc1_data.py` | Synthetic data generator |
| `dbseed/seed_uc1.sh` | One-command setup orchestrator |
| `UC1_SPEC_TEMPLATE.json` | Template for PR spec.json |

## Support

For issues or questions:

1. Check Dagster run logs: Artifacts → {run_id} → {container}.log
2. Check pod logs: `kubectl logs -n fn <pod-name>`
3. Check db-datasets connectivity: `psql -h db-datasets.fn.svc ...`
4. Review dagster/app/definitions/pipes.py for secret/config injection logic
5. Review dagster/app/definitions/sensors/github/pr_trigger.py for PR → RunRequest mapping
