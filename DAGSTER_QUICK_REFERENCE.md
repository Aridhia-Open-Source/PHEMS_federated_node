# Dagster with External Database - Quick Reference

Quick commands and checks for daily operations with Dagster using an external database.

## Environment Setup

```bash
export NAMESPACE="default"  # or your namespace
export RELEASE="federated-node"
export DB_NAME="dagster_db"
```

## Quick Health Check

```bash
# One-liner health check
kubectl get pods -n $NAMESPACE | grep dagster && \
echo "✓ Pods running" || echo "✗ Pod issues"

# Run full validation
./scripts/validate_dagster_db.sh
```

## Common Commands

### Access Dagster UI

```bash
# Port forward to access UI
kubectl port-forward -n $NAMESPACE svc/${RELEASE}-dagster-webserver 8080:80

# Open browser to: http://localhost:8080
```

### Check Pod Status

```bash
# All Dagster pods
kubectl get pods -n $NAMESPACE | grep dagster

# With details
kubectl get pods -n $NAMESPACE -l app.kubernetes.io/instance=$RELEASE

# Watch for changes
watch kubectl get pods -n $NAMESPACE | grep dagster
```

### View Logs

```bash
# Webserver logs
kubectl logs -n $NAMESPACE deployment/${RELEASE}-dagster-webserver --tail=50 -f

# Daemon logs
kubectl logs -n $NAMESPACE deployment/${RELEASE}-dagster-daemon --tail=50 -f

# User deployment logs
kubectl logs -n $NAMESPACE deployment/${RELEASE}-dagster-fn --tail=50 -f

# Specific pod
kubectl logs -n $NAMESPACE <pod-name> --tail=100 -f

# Previous crashed container
kubectl logs -n $NAMESPACE <pod-name> --previous
```

### Database Operations

```bash
# Find database pod
DB_POD=$(kubectl get pods -n $NAMESPACE | grep postgres | awk '{print $1}' | head -1)
echo $DB_POD

# Connect to database
kubectl exec -it -n $NAMESPACE $DB_POD -- psql -U test -d dagster_db

# List databases
kubectl exec -n $NAMESPACE $DB_POD -- psql -U test -c '\l'

# List tables in dagster_db
kubectl exec -n $NAMESPACE $DB_POD -- psql -U test -d dagster_db -c '\dt'

# Check recent runs
kubectl exec -n $NAMESPACE $DB_POD -- psql -U test -d dagster_db -c \
  "SELECT run_id, status, create_timestamp FROM runs ORDER BY create_timestamp DESC LIMIT 10;"

# Check database connections
kubectl exec -n $NAMESPACE $DB_POD -- psql -U test -d dagster_db -c \
  "SELECT datname, count(*) FROM pg_stat_activity GROUP BY datname;"

# Database size
kubectl exec -n $NAMESPACE $DB_POD -- psql -U test -d dagster_db -c \
  "SELECT pg_size_pretty(pg_database_size('dagster_db'));"
```

### Configuration Checks

```bash
# View ConfigMap
kubectl get configmap -n $NAMESPACE dagster-env-config -o yaml

# View environment variables
kubectl exec -n $NAMESPACE deployment/${RELEASE}-dagster-webserver -- env | grep DAGSTER

# Check secret
kubectl get secret -n $NAMESPACE backend-secrets -o yaml

# Decode password (if needed)
kubectl get secret -n $NAMESPACE backend-secrets -o jsonpath='{.data.PGPASSWORD}' | base64 -d
```

### Restart Pods

```bash
# Restart webserver
kubectl rollout restart -n $NAMESPACE deployment/${RELEASE}-dagster-webserver

# Restart daemon
kubectl rollout restart -n $NAMESPACE deployment/${RELEASE}-dagster-daemon

# Restart user deployment
kubectl rollout restart -n $NAMESPACE deployment/${RELEASE}-dagster-fn

# Restart all Dagster components
kubectl rollout restart -n $NAMESPACE deployment -l app.kubernetes.io/instance=$RELEASE
```

### Scale Components

```bash
# Scale webserver
kubectl scale -n $NAMESPACE deployment/${RELEASE}-dagster-webserver --replicas=2

# Scale user deployment
kubectl scale -n $NAMESPACE deployment/${RELEASE}-dagster-fn --replicas=2

# Note: Don't scale daemon >1 (can cause duplicate schedule/sensor evaluations)
```

## Troubleshooting Quick Fixes

### Pods in CrashLoopBackOff

```bash
# Check logs
kubectl logs -n $NAMESPACE <pod-name> --previous

# Common causes:
# 1. Database not reachable - check postgresqlHost
# 2. Database doesn't exist - create dagster_db
# 3. Wrong credentials - verify secret

# Verify database connection from pod
kubectl exec -n $NAMESPACE deployment/${RELEASE}-dagster-webserver -- \
  bash -c 'apt-get update && apt-get install -y postgresql-client && \
  psql -h $DAGSTER_POSTGRES_HOST -U $DAGSTER_POSTGRES_USER -d $DAGSTER_POSTGRES_DB -c "SELECT 1"'
```

### Database Connection Issues

```bash
# Test from a pod
kubectl exec -n $NAMESPACE deployment/${RELEASE}-dagster-webserver -- \
  env | grep DAGSTER_POSTGRES

# Check if service exists
kubectl get svc -n $NAMESPACE | grep postgres

# Test DNS resolution
kubectl exec -n $NAMESPACE deployment/${RELEASE}-dagster-webserver -- \
  nslookup postgres-service

# Check if database is accepting connections
kubectl exec -n $NAMESPACE $DB_POD -- pg_isready
```

### Dagster Tables Missing

```bash
# Run migration
kubectl exec -n $NAMESPACE deployment/${RELEASE}-dagster-webserver -- \
  dagster instance migrate

# Verify tables created
kubectl exec -n $NAMESPACE $DB_POD -- psql -U test -d dagster_db -c '\dt'
```

### Configuration Not Applied

```bash
# Delete and recreate ConfigMap
kubectl delete configmap -n $NAMESPACE dagster-env-config
helm upgrade $RELEASE ./k8s/federated-node -n $NAMESPACE --reuse-values

# Force pod restart to pick up changes
kubectl delete pods -n $NAMESPACE -l app.kubernetes.io/instance=$RELEASE
```

## Maintenance Tasks

### Backup Database

```bash
# Backup dagster_db
kubectl exec -n $NAMESPACE $DB_POD -- \
  pg_dump -U test dagster_db > dagster_db_backup_$(date +%Y%m%d).sql

# Backup both databases
kubectl exec -n $NAMESPACE $DB_POD -- pg_dump -U test fndb > fndb_backup_$(date +%Y%m%d).sql
kubectl exec -n $NAMESPACE $DB_POD -- pg_dump -U test dagster_db > dagster_db_backup_$(date +%Y%m%d).sql
```

### Restore Database

```bash
# Restore dagster_db
kubectl exec -i -n $NAMESPACE $DB_POD -- \
  psql -U test dagster_db < dagster_db_backup.sql
```

### Clean Old Runs

```bash
# Check number of runs
kubectl exec -n $NAMESPACE $DB_POD -- psql -U test -d dagster_db -c \
  "SELECT status, count(*) FROM runs GROUP BY status;"

# Delete runs older than 30 days (be careful!)
kubectl exec -n $NAMESPACE $DB_POD -- psql -U test -d dagster_db -c \
  "DELETE FROM runs WHERE create_timestamp < NOW() - INTERVAL '30 days';"

# Or use Dagster's built-in cleanup (configure in values.yaml)
# retention:
#   enabled: true
#   sensor:
#     purgeAfterDays: 30
```

### Update Dagster Version

```bash
# Backup first!
kubectl exec -n $NAMESPACE $DB_POD -- \
  pg_dump -U test dagster_db > dagster_db_backup_pre_upgrade.sql

# Update Helm chart
helm repo update
helm search repo dagster

# Upgrade (replace X.Y.Z with version)
helm upgrade $RELEASE dagster/dagster -n $NAMESPACE \
  --version X.Y.Z \
  --reuse-values

# Run migrations
kubectl exec -n $NAMESPACE deployment/${RELEASE}-dagster-webserver -- \
  dagster instance migrate
```

## Monitoring

### Resource Usage

```bash
# CPU and Memory
kubectl top pods -n $NAMESPACE | grep dagster

# Detailed pod metrics
kubectl describe pod -n $NAMESPACE <pod-name> | grep -A 5 "Limits:"
```

### Event Log Size

```bash
# Check event log table size
kubectl exec -n $NAMESPACE $DB_POD -- psql -U test -d dagster_db -c \
  "SELECT pg_size_pretty(pg_total_relation_size('event_logs'));"

# Count events
kubectl exec -n $NAMESPACE $DB_POD -- psql -U test -d dagster_db -c \
  "SELECT COUNT(*) FROM event_logs;"
```

### Active Runs

```bash
# Check for stuck runs
kubectl exec -n $NAMESPACE $DB_POD -- psql -U test -d dagster_db -c \
  "SELECT run_id, status, create_timestamp, update_timestamp FROM runs WHERE status = 'STARTED' ORDER BY create_timestamp;"
```

## Emergency Procedures

### Complete Reset (Development Only!)

```bash
# WARNING: This will delete all Dagster data!

# 1. Delete Dagster components
helm uninstall $RELEASE -n $NAMESPACE

# 2. Drop and recreate database
kubectl exec -n $NAMESPACE $DB_POD -- psql -U test -c "DROP DATABASE dagster_db;"
kubectl exec -n $NAMESPACE $DB_POD -- psql -U test -c "CREATE DATABASE dagster_db;"

# 3. Reinstall
helm upgrade --install $RELEASE ./k8s/federated-node -n $NAMESPACE

# 4. Run migrations
kubectl exec -n $NAMESPACE deployment/${RELEASE}-dagster-webserver -- \
  dagster instance migrate
```

### Rollback Deployment

```bash
# List revisions
helm history $RELEASE -n $NAMESPACE

# Rollback to previous
helm rollback $RELEASE -n $NAMESPACE

# Rollback to specific revision
helm rollback $RELEASE <revision> -n $NAMESPACE
```

## Useful Queries

### Get Dagster Version

```bash
kubectl exec -n $NAMESPACE deployment/${RELEASE}-dagster-webserver -- \
  dagster --version
```

### List All Code Locations

```bash
kubectl exec -n $NAMESPACE deployment/${RELEASE}-dagster-webserver -- \
  dagster workspace list
```

### Check Daemon Status

```bash
kubectl exec -n $NAMESPACE deployment/${RELEASE}-dagster-daemon -- \
  dagster-daemon liveness-check
```

## Key File Locations

- Main setup guide: `DAGSTER_DATABASE_SETUP.md`
- Setup checklist: `DAGSTER_SETUP_CHECKLIST.md`
- Example config: `k8s/federated-node/dagster-external-db-example.yaml`
- Validation script: `scripts/validate_dagster_db.sh`
- ConfigMap template: `k8s/federated-node/templates/dagster-env-configmap.yaml`
- Values file: `k8s/federated-node/values.yaml`

## Support

For issues:
1. Run validation script: `./scripts/validate_dagster_db.sh`
2. Check logs: webserver, daemon, user deployment
3. Verify database connectivity
4. Review Helm values
5. Consult `DAGSTER_DATABASE_SETUP.md` troubleshooting section
