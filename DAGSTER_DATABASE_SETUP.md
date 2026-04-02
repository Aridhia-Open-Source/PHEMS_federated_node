# Dagster with Existing Database - Setup and Validation Guide

This guide walks through configuring Dagster to use your existing PHEMS Federated Node PostgreSQL database instead of deploying its own PostgreSQL instance.

## Table of Contents
1. [Architecture Overview](#architecture-overview)
2. [Prerequisites](#prerequisites)
3. [Step-by-Step Configuration](#step-by-step-configuration)
4. [Deployment](#deployment)
5. [Validation](#validation)
6. [Troubleshooting](#troubleshooting)

---

## Architecture Overview

### Current Setup
- PHEMS Federated Node has its own PostgreSQL database
- Database credentials stored in `backend-secrets` Secret
- Database configuration in `values.yaml` under `db` section

### Target Setup
- Dagster will share the same PostgreSQL instance
- Dagster will use a **separate database** within the same PostgreSQL server for isolation
- No separate PostgreSQL pod will be deployed for Dagster
- Shared credentials and connection configuration

### Why a Separate Database?
- **Isolation**: Dagster tables won't interfere with Federated Node tables
- **Security**: Each application has its own schema
- **Maintenance**: Easier to backup/restore/migrate independently
- **Performance**: Better query performance tracking per application

---

## Prerequisites

### 1. Identify Your Database Configuration

First, determine your current database setup:

```bash
# Get the namespace (usually 'default' or from your deployment)
export NAMESPACE="<your-namespace>"

# Check if database is already deployed
kubectl get pods -n $NAMESPACE | grep -E 'postgres|mariadb|mysql'

# Check existing secrets
kubectl get secrets -n $NAMESPACE | grep -E 'backend-secrets|db-'
```

### 2. Gather Database Connection Details

You need:
- **Host**: Database hostname (e.g., `postgres-service`, `db-service`, or external hostname)
- **Port**: Usually `5432` for PostgreSQL
- **Username**: Database user (from `values.yaml` or secret)
- **Password**: Database password (from secret)
- **Existing Database**: The current database name (default: `fndb` from values.yaml)

### 3. Check Database Permissions

Ensure the database user has permission to create databases:

```bash
# Port forward to database
kubectl port-forward -n $NAMESPACE svc/<db-service-name> 5432:5432 &

# Connect and check
psql -h localhost -U <username> -d <existing-db> -c "\l"
psql -h localhost -U <username> -d <existing-db> -c "SELECT has_database_privilege('<username>', 'CREATE');"
```

---

## Step-by-Step Configuration

### Step 1: Create Dagster Database

You have two options:

#### Option A: Create Manually (Recommended for Production)

```bash
# Connect to your PostgreSQL instance
kubectl exec -it -n $NAMESPACE <postgres-pod-name> -- psql -U <username>

# Or if using an external database
psql -h <db-host> -U <username> -d <existing-db>

# Create the Dagster database
CREATE DATABASE dagster_db;

# Grant privileges
GRANT ALL PRIVILEGES ON DATABASE dagster_db TO <username>;

# Verify
\l dagster_db
\q
```

#### Option B: Let Dagster Create It (Development Only)

If your DB user has `CREATEDB` privilege, Dagster can create the database automatically on first run.

### Step 2: Update Federated Node Values

Edit `k8s/federated-node/values.yaml`:

```yaml
db:
  enforceSSL: false
  name: fndb
  port: 5432
  host: postgres-service  # ADD THIS - your PostgreSQL service name
  user: test              # ADD THIS - your database username
  # If using an existing secret for password:
  secret:
    name: backend-secrets
    key: PGPASSWORD
  # OR set password directly (not recommended for production):
  # password: your_password_here

### Dagster Configuration
dagster:
  enabled: true

  # Disable the PostgreSQL subchart - we'll use the existing database
  postgresql:
    enabled: false
    service:
      port: 5432  # Keep this for connection template

  # Configure connection to existing database
  postgresqlHost: "{{ .Values.db.host }}"
  postgresqlPort: 5432
  postgresqlUsername: "{{ .Values.db.user }}"
  postgresqlDatabase: "dagster_db"  # NEW database for Dagster
  
  # Use existing secret or generate new one
  generatePostgresqlPasswordSecret: false  # CHANGED from true
  postgresqlSecretName: "{{ .Values.db.secret.name }}"  # Use existing secret
  postgresqlPassword: "{{ .Values.db.password }}"  # Or reference directly

  runLauncher:
    type: K8sRunLauncher
    config:
      k8sRunLauncher:
        imagePullPolicy: "Always"
        image:
          repository: localhost:5001/dagster-fn
          tag: "v15"
          pullPolicy: "Always"

        envConfigMaps:
          - name: dagster-env-config

        # Existing volumes configuration...
        volumes:
          - name: artifacts-pvc
            persistentVolumeClaim:
              claimName: artifacts-pvc
        volumeMounts:
          - name: artifacts-pvc
            mountPath: /mnt/dagster/artifacts
```

### Step 3: Create Dagster Environment ConfigMap Template

Create `k8s/federated-node/templates/dagster-env-configmap.yaml`:

```yaml
{{- if .Values.dagster.enabled }}
apiVersion: v1
kind: ConfigMap
metadata:
  name: dagster-env-config
  namespace: {{ .Release.Namespace }}
data:
  # Database connection for Dagster
  DAGSTER_POSTGRES_HOST: {{ .Values.db.host | quote }}
  DAGSTER_POSTGRES_PORT: {{ .Values.db.port | quote }}
  DAGSTER_POSTGRES_USER: {{ .Values.db.user | quote }}
  DAGSTER_POSTGRES_DB: "dagster_db"
  
  # Optional: Add any other environment variables your Dagster jobs need
  # GITHUB_TOKEN: provided via secret
  # RESULTS_PATH: {{ .Values.federatedNode.volumes.results_path | quote }}
{{- end }}
```

### Step 4: Update Dagster Secret Reference (if needed)

If you're using a separate secret, ensure it's referenced correctly. The default `backend-secrets` should work, but verify:

```bash
# Check the secret exists and has the right key
kubectl get secret -n $NAMESPACE backend-secrets -o yaml
```

If using the existing `backend-secrets`, you might need to add a reference in the Dagster values or create a new secret that Dagster expects.

### Step 5: Configure Database Connection in dagster.yaml

Your Dagster instance should automatically pick up the database configuration from the Helm chart, but if you have a custom `dagster/dagster.yaml`, ensure it's configured:

```yaml
# dagster/dagster.yaml
storage:
  postgres:
    postgres_db:
      hostname:
        env: DAGSTER_POSTGRES_HOST
      port:
        env: DAGSTER_POSTGRES_PORT
      username:
        env: DAGSTER_POSTGRES_USER
      password:
        env: DAGSTER_POSTGRES_PASSWORD
      db_name:
        env: DAGSTER_POSTGRES_DB
      params:
        connect_timeout: 10
```

---

## Deployment

### Step 1: Validate Your Configuration

```bash
# Dry-run to check for errors
helm upgrade --install federated-node ./k8s/federated-node \
  --namespace $NAMESPACE \
  --dry-run --debug \
  --values ./k8s/federated-node/values.yaml
```

### Step 2: Deploy

```bash
# Deploy the changes
helm upgrade --install federated-node ./k8s/federated-node \
  --namespace $NAMESPACE \
  --values ./k8s/federated-node/values.yaml \
  --timeout 10m

# Watch the rollout
kubectl get pods -n $NAMESPACE -w
```

### Step 3: Check Deployment Status

```bash
# Check all pods are running
kubectl get pods -n $NAMESPACE

# Expected pods:
# - federated-node-dagster-daemon-xxx
# - federated-node-dagster-webserver-xxx
# - federated-node-dagster-fn-xxx (user code deployment)
# - NO postgres pod for Dagster (it's disabled)
```

---

## Validation

### 1. Check Pod Status

```bash
# All pods should be Running
kubectl get pods -n $NAMESPACE | grep dagster

# Check for any errors
kubectl get pods -n $NAMESPACE | grep -v Running | grep -v Completed
```

### 2. Check Database Connection

```bash
# Check Dagster webserver logs
kubectl logs -n $NAMESPACE deployment/federated-node-dagster-webserver --tail=50

# Look for successful database connection messages
# Should see: "Successfully connected to PostgreSQL"
# Should NOT see: "Could not connect to database" or connection errors
```

### 3. Verify Database Tables Created

```bash
# Connect to database
kubectl exec -it -n $NAMESPACE <postgres-pod> -- psql -U <username> -d dagster_db

# Check Dagster tables exist
\dt

# Expected tables:
# - runs
# - run_tags
# - jobs
# - asset_keys
# - schedules
# - event_logs
# ... and more

# Exit
\q
```

### 4. Access Dagster UI

```bash
# Port forward to access UI
kubectl port-forward -n $NAMESPACE svc/federated-node-dagster-webserver 8080:80

# Open browser to: http://localhost:8080
```

**In the UI, check:**
- ✅ Homepage loads without errors
- ✅ "Status" page shows daemon is running
- ✅ "Runs" page is accessible (even if empty)
- ✅ "Assets" page loads
- ✅ Your code location appears in the workspace

### 5. Test a Simple Run

In the Dagster UI:
1. Navigate to your job/asset
2. Click "Materialize" or "Launch Run"
3. Watch the run execute
4. Check logs are visible

Or via CLI:

```bash
# Get into the user code pod
kubectl exec -it -n $NAMESPACE deployment/federated-node-dagster-fn -- bash

# List jobs
dagster job list

# Execute a job (if you have one defined)
dagster job execute -m app.definitions -j <job-name>
```

### 6. Check Database Activity

```bash
# Monitor database connections
kubectl exec -it -n $NAMESPACE <postgres-pod> -- psql -U <username> -d dagster_db -c "SELECT datname, count(*) FROM pg_stat_activity GROUP BY datname;"

# Should show active connections to both 'fndb' and 'dagster_db'
```

### 7. Verify Isolation

Ensure Dagster and Federated Node databases are separate:

```bash
# Check fndb tables (Federated Node)
kubectl exec -it -n $NAMESPACE <postgres-pod> -- psql -U <username> -d fndb -c "\dt"

# Check dagster_db tables (Dagster)
kubectl exec -it -n $NAMESPACE <postgres-pod> -- psql -U <username> -d dagster_db -c "\dt"

# They should have completely different tables
```

---

## Troubleshooting

### Issue: Pods CrashLoopBackOff

**Check logs:**
```bash
kubectl logs -n $NAMESPACE <pod-name> --previous
```

**Common causes:**
- Database not reachable: Check `postgresqlHost` value
- Wrong credentials: Verify secret exists and has correct key
- Database doesn't exist: Create `dagster_db` manually
- Insufficient permissions: Grant CREATEDB or CREATE privileges

### Issue: "Could not connect to database"

**Verify connectivity:**
```bash
# From a Dagster pod
kubectl exec -it -n $NAMESPACE deployment/federated-node-dagster-webserver -- bash

# Test connection
apt-get update && apt-get install -y postgresql-client
psql -h $DAGSTER_POSTGRES_HOST -U $DAGSTER_POSTGRES_USER -d $DAGSTER_POSTGRES_DB

# If it fails, check:
# 1. Service name is correct
# 2. Database exists
# 3. Credentials are correct
```

### Issue: Password not found

**Check secret:**
```bash
# Verify secret exists
kubectl get secret -n $NAMESPACE backend-secrets

# Check contents
kubectl get secret -n $NAMESPACE backend-secrets -o jsonpath='{.data.PGPASSWORD}' | base64 -d

# If using different secret name, update values.yaml
```

### Issue: Dagster tables not created

**Run migration manually:**
```bash
kubectl exec -it -n $NAMESPACE deployment/federated-node-dagster-webserver -- dagster instance migrate
```

### Issue: Permission denied creating database

**Grant permissions:**
```bash
# As superuser
kubectl exec -it -n $NAMESPACE <postgres-pod> -- psql -U postgres

ALTER USER <username> CREATEDB;

# Or grant permissions on specific database
GRANT ALL PRIVILEGES ON DATABASE dagster_db TO <username>;
```

### Issue: Mixing old and new PostgreSQL pod

**Ensure cleanup:**
```bash
# Check for old Dagster PostgreSQL StatefulSet
kubectl get statefulsets -n $NAMESPACE | grep postgresql

# Delete if exists
kubectl delete statefulset -n $NAMESPACE <dagster-postgresql-statefulset>

# Check for PVCs
kubectl get pvc -n $NAMESPACE | grep postgresql

# Delete old Dagster PVC if needed (BE CAREFUL - data loss)
# kubectl delete pvc -n $NAMESPACE <dagster-postgresql-pvc>
```

---

## Production Considerations

### 1. Database Backup

Ensure your backup strategy covers both databases:

```bash
# Backup both databases
pg_dump -h <host> -U <user> fndb > fndb_backup.sql
pg_dump -h <host> -U <user> dagster_db > dagster_db_backup.sql
```

### 2. Resource Limits

Set appropriate resource limits in `values.yaml`:

```yaml
dagster:
  dagsterWebserver:
    resources:
      limits:
        cpu: 500m
        memory: 512Mi
      requests:
        cpu: 250m
        memory: 256Mi
  
  dagsterDaemon:
    resources:
      limits:
        cpu: 500m
        memory: 512Mi
      requests:
        cpu: 250m
        memory: 256Mi
```

### 3. Connection Pooling

For production, configure connection pooling:

```yaml
dagster:
  additionalInstanceConfig:
    storage:
      postgres:
        postgres_db:
          pool_size: 10
          max_overflow: 20
```

### 4. SSL Enforcement

If your database requires SSL:

```yaml
db:
  enforceSSL: true

dagster:
  postgresqlParams:
    sslmode: require
```

### 5. Monitoring

Set up monitoring for:
- Database connection count
- Query performance
- Disk space usage
- Dagster daemon health

---

## Rollback Plan

If you need to rollback to separate PostgreSQL:

```bash
# 1. Backup Dagster data
kubectl exec -it -n $NAMESPACE <postgres-pod> -- pg_dump -U <user> dagster_db > dagster_backup.sql

# 2. Revert values.yaml changes
# Set postgresql.enabled: true
# Remove external database configuration

# 3. Upgrade Helm release
helm upgrade federated-node ./k8s/federated-node \
  --namespace $NAMESPACE \
  --values ./k8s/federated-node/values.yaml

# 4. Restore data if needed
kubectl exec -i -n $NAMESPACE <new-dagster-postgres-pod> -- psql -U <user> dagster_db < dagster_backup.sql
```

---

## Summary Checklist

**Configuration:**
- [ ] Database host, user, and credentials identified
- [ ] `dagster_db` database created
- [ ] `values.yaml` updated with database configuration
- [ ] `postgresql.enabled: false` set
- [ ] Database connection environment variables configured
- [ ] Secrets properly referenced

**Deployment:**
- [ ] Dry-run validation passed
- [ ] Helm upgrade successful
- [ ] All pods running (no PostgreSQL pod for Dagster)
- [ ] No CrashLoopBackOff errors

**Validation:**
- [ ] Dagster tables created in `dagster_db`
- [ ] Dagster UI accessible
- [ ] Test run executed successfully
- [ ] Logs showing successful database connections
- [ ] Both `fndb` and `dagster_db` have separate tables

**Production Ready:**
- [ ] Resource limits configured
- [ ] Backup strategy includes both databases
- [ ] Monitoring set up
- [ ] SSL configured (if required)
- [ ] Rollback plan documented

---

## Additional Resources

- [Dagster Helm Chart Documentation](https://docs.dagster.io/deployment/guides/kubernetes/deploying-with-helm)
- [Dagster Instance Configuration](https://docs.dagster.io/deployment/dagster-instance)
- [PostgreSQL Connection Settings](https://www.postgresql.org/docs/current/libpq-connect.html)
- [Kubernetes Secrets](https://kubernetes.io/docs/concepts/configuration/secret/)

---

**Questions or Issues?**

Check logs first:
```bash
# Webserver
kubectl logs -n $NAMESPACE deployment/federated-node-dagster-webserver

# Daemon
kubectl logs -n $NAMESPACE deployment/federated-node-dagster-daemon

# User code
kubectl logs -n $NAMESPACE deployment/federated-node-dagster-fn
```
