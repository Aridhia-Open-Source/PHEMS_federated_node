# UC1: MVP-Code Onboarding Plan

## Quick Facts
- MVP-Code = R/OMOP-CDM cardiac pipeline (CodeToRun.R entrypoint), needs `CONNECTION_STRING`, `CDM_SCHEMA`, `WRITE_SCHEMA` env vars
- `CONNECTION_STRING` format: `server=HOST;database=NAME;port=PORT;uid=USER;pwd=PASSWORD` (plaintext creds inside)
- Creds only available as mounted k8s Secret files `/var/secrets/db/{PGUSER,PGPASSWORD}`, never as env vars
- Need separate Postgres "dataset_db" Deployment (NOT reusing shared `db-internal`) with OMOP-CDM schema + synthetic data
- Pipeline path: PR spec.json → k8s_pipes_op → R container reads secrets + env → outputs CSVs to `/app/results`

## Steps (In Order)

### 1. Build MVP-Code image
- Edit `scripts/build_all_images.sh`: add `"MVP-Code"` to `DOCKER_DIRS` array
- Run: `./scripts/build_all_images.sh v1` → pushes to `localhost:5001/MVP-Code-fn:v1`
- Verify image exists: `docker images | grep MVP-Code`

### 2. Create dataset_db k8s infra (separate from shared db-internal)
New/modified Helm templates (all gated by `.Values.datasetDb.create: true`):
- `k8s/federated-node/templates/db-datasets-deployment.yaml` — Postgres pod named `db-datasets` (NOT `db-internal`), own PVC `db-datasets-volclaim`, superuser secret `db-datasets-superuser`
- `k8s/federated-node/templates/db-datasets-service.yaml` — Service `db-datasets`, port 5432
- `k8s/federated-node/templates/db-datasets-pv.yaml` — PV `{{ .Release.Name }}-db-datasets-pv`, PVC `db-datasets-volclaim`, StorageClass `{{ .Release.Name }}-db-datasets-storage`
- `k8s/federated-node/templates/db-datasets-init.yaml` — Job `db-datasets-init`, wait-for-db → CREATE DATABASE uc1_omop, CREATE USER uc1_omop_user, GRANT

Values changes:
- `values.yaml`: add `datasetDb: {create: false, port: 5432, superuser: postgres, secret: {name: db-datasets-superuser, key: password}}`
- `dev.values.yaml`: override to `datasetDb: {create: true, host: db-datasets.fn.svc, port: 5432, secret: {name: db-datasets-superuser, key: password}, db: {name: uc1_omop, user: uc1_omop_user, secret: {name: db-datasets-app, key: password}}}`

Secret creation (update `scripts/deploy.sh` after existing secret blocks):
```bash
kubectl create secret generic db-datasets-superuser \
  --from-literal=password="$DATASET_DB_SUPERUSER_PASSWORD" \
  --dry-run=client -o yaml -n "$NAMESPACE" | kubectl apply -f - -n "$NAMESPACE"

kubectl create secret generic db-datasets-app \
  --from-literal=password="$DATASET_DB_APP_PASSWORD" \
  --dry-run=client -o yaml -n "$NAMESPACE" | kubectl apply -f - -n "$NAMESPACE"
```

Add env vars to `.dev.env.example` / `.dev.env`:
```
DATASET_DB_SUPERUSER_PASSWORD=<random password>
DATASET_DB_APP_PASSWORD=<random password>
```

### 3. MVP-Code Dockerfile + entrypoint wrapper
New file: `MVP-Code/entrypoint.sh`
```bash
#!/bin/bash
set -euo pipefail

PGUSER=$(cat /var/secrets/db/PGUSER)
PGPASSWORD=$(cat /var/secrets/db/PGPASSWORD)
DATASET_HOST="${DATASET_HOST:-localhost}"
DATASET_PORT="${DATASET_PORT:-5432}"
DATASET_NAME="${DATASET_NAME:-uc1_omop}"

export CONNECTION_STRING="server=${DATASET_HOST};database=${DATASET_NAME};port=${DATASET_PORT};uid=${PGUSER};pwd=${PGPASSWORD};"
export CDM_SCHEMA="${CDM_SCHEMA:-public}"
export WRITE_SCHEMA="${WRITE_SCHEMA:-write_schema}"

exec Rscript CodeToRun.R
```

Update `MVP-Code/Dockerfile`:
```dockerfile
FROM ghcr.io/aridhia-open-source/r-base:0.0.1
WORKDIR /app
COPY OMOP_data_wrangle/renv.lock ./
RUN R -e "install.packages('renv')" && R -e "renv::restore()"
COPY OMOP_data_wrangle ./
COPY entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh
ENTRYPOINT ["/app/entrypoint.sh"]
```

### 4. Fix pipes.py + pr_trigger.py to inject connection env vars
**`dagster/app/definitions/pipes.py`**:
- Add `dataset_schema`, `dataset_schema_write` to `k8s_pipes_op` config_schema (both `is_required=False`)
- Store on `K8sPipe.__init__`: `self.dataset_schema = self.config.get('dataset_schema')`
- In `_setup_env()`: add `DATASET_HOST`, `DATASET_PORT`, `DATASET_NAME`, `CDM_SCHEMA`, `WRITE_SCHEMA` to env dict (read from config or defaults)

**`dagster/app/definitions/sensors/github/pr_trigger.py`**:
- In `_make_run_request()`: fetch `dataset.schema` and `dataset.schema_write` from the dataset object
- Pass them in op config alongside existing `dataset_name/host/port/type`

### 5. Create synthetic OMOP-CDM data
New standalone script: `scripts/seed_omop_dataset.py`
- Connects to `db-datasets.fn.svc:5432` (or `localhost:5432` if port-forwarded) as `uc1_omop_user`
- Creates OMOP CDM v5.4 standard tables (minimal set): `person`, `observation_period`, `visit_occurrence`, `visit_detail`, `procedure_occurrence`, `condition_occurrence`, `death`, `concept`, `concept_ancestor`, `domain`, `vocabulary`
- Populates minimal vocabulary subset: only concept_ids actually referenced in MVP-Code's R scripts (cardiac procedures, complications, visit types) + their metadata (concept_name, domain_id, vocabulary_id, concept_class_id, standard_concept, concept_code, valid_start_date, valid_end_date)
- Generates synthetic patients: ~100 patients, ages 0-17, gender_concept_id 8507 or 8532, obs_period covering 2019-05-01+, ~5-10 visits per patient (mix of visit_types 9201/9202/9203 + visit_detail 32037=ICU), ~2-5 procedures per patient (mix of cardiac procedure concept_ids), ~1-3 conditions per patient (cardiac complications), ~5-10 deaths
- Seed strategy: Python script using pandas + sqlalchemy, inserts via ORM (no raw DDL hardcoding)

### 6. Register dataset via dbseed/seed_backend.py
- Update `dbseed/.env`:
  ```
  DATASET_HOST=db-datasets.fn.svc
  DATASET_PORT=5432
  DATASET_NAME=uc1_omop
  DATASET_USERNAME=uc1_omop_user
  DATASET_PASSWORD=<same as DATASET_DB_APP_PASSWORD>
  DATASET_SCHEMA=public
  DATASET_TYPE=postgres
  REPO_WATCH_DIR=specs  # NEW: dedicated watch dir for MVP-Code specs
  REPO_INITIAL_CURSOR=2019-05-01T00:00:00
  ```
- Run: `cd dbseed && python3 seed_backend.py` (will delete existing repos/datasets, create new ones)

### 7. Create PR spec.json and trigger
- Create PR in trigger repo (`phems-sandbox` or wherever repo points) adding `specs/mvp-uc1-spec.json`:
  ```json
  {
    "spec": {
      "docker_image": "localhost:5001/MVP-Code-fn:v1",
      "env": {}
    }
  }
  ```
- Merge PR
- Sensor polls → detects READY PR → fires k8s_pipes_op → R container reads secrets + env → runs cardiac analysis → outputs CSVs to `/mnt/dagster/artifacts/{run_id}/results/`

### 8. Verification
- Check Dagster UI: run appears, status progresses QUEUED → STARTED → SUCCESS
- Check pod logs: R script outputs, no connection errors, CSV file written
- Check GitHub: github_transfer_job delivers results back to PR as comment/commit

## Decision Points (Ask User)
1. **Trigger repo**: continue using `phems-sandbox` or new repo? (→ affects REPO_URI in seed.py)
2. **Synthetic data volume**: 100 patients ok, or want more?
3. **Env var naming**: use `DATASET_HOST` / `DATASET_PORT` / `DATASET_NAME` or different?
