# Dagster External Database - Quick Setup Checklist

Use this checklist when configuring Dagster to use your existing PostgreSQL database.

## Pre-Deployment Checklist

### 1. Identify Your Setup
- [ ] I know my PostgreSQL service name: `_________________`
- [ ] I know my database username: `_________________`
- [ ] I know where the password is stored: `_________________`
- [ ] I know my existing database name: `_________________`

### 2. Create Dagster Database
- [ ] Connected to PostgreSQL
- [ ] Created `dagster_db` database: 
  ```sql
  CREATE DATABASE dagster_db;
  GRANT ALL PRIVILEGES ON DATABASE dagster_db TO <username>;
  ```
- [ ] Verified database exists: `\l dagster_db`

### 3. Update Configuration Files

#### values.yaml - Database Section
- [ ] Added `db.host: <postgres-service-name>`
- [ ] Added `db.user: <username>`
- [ ] Configured `db.secret` or `db.password`

#### values.yaml - Dagster Section  
- [ ] Set `dagster.postgresql.enabled: false`
- [ ] Set `dagster.postgresqlHost`
- [ ] Set `dagster.postgresqlUsername`
- [ ] Set `dagster.postgresqlDatabase: dagster_db`
- [ ] Set `dagster.generatePostgresqlPasswordSecret: false`
- [ ] Configured secret reference

#### Helm Templates
- [ ] Created `templates/dagster-env-configmap.yaml`
- [ ] Verified ConfigMap references database variables
- [ ] Added `envConfigMaps` to runLauncher
- [ ] Added `envSecrets` to runLauncher (if using secrets)
- [ ] Added same config to user-deployments

### 4. Validate Configuration
- [ ] Ran `helm template` or `helm --dry-run` to check syntax
- [ ] Reviewed generated manifests for correctness
- [ ] Verified no PostgreSQL StatefulSet in output

## Deployment Checklist

### 1. Pre-Deployment Backup
- [ ] Backed up existing database (if applicable)
- [ ] Documented current Helm values
- [ ] Saved rollback commands

### 2. Deploy
- [ ] Ran Helm upgrade command
- [ ] Command completed without errors
- [ ] Noted deployment timestamp: `_________________`

### 3. Initial Verification
- [ ] All pods reached Running state (within 5 min)
- [ ] No CrashLoopBackOff errors
- [ ] No PostgreSQL pod created for Dagster
- [ ] Webserver pod logs show successful startup
- [ ] Daemon pod logs show successful startup

## Post-Deployment Validation Checklist

### 1. Run Validation Script
- [ ] Executed `./scripts/validate_dagster_db.sh`
- [ ] All checks passed: `____/6`
- [ ] Reviewed any warnings or errors

### 2. Manual Checks

#### Database
- [ ] Connected to `dagster_db`
- [ ] Dagster tables created (runs, event_logs, jobs, etc.)
- [ ] Verified separation: `fndb` has FN tables, `dagster_db` has Dagster tables
- [ ] Checked database connections: `SELECT * FROM pg_stat_activity;`

#### Kubernetes Resources
- [ ] ConfigMap `dagster-env-config` exists
- [ ] Secret `backend-secrets` exists and has PGPASSWORD
- [ ] No StatefulSet for Dagster PostgreSQL
- [ ] Services exist: dagster-webserver, dagster-daemon

#### Logs Review
- [ ] Webserver logs: No connection errors
- [ ] Daemon logs: No connection errors
- [ ] User deployment logs: No connection errors
- [ ] Checked for any WARNING or ERROR messages

### 3. Functional Testing

#### Access UI
- [ ] Port-forwarded to webserver: `kubectl port-forward svc/<release>-dagster-webserver 8080:80`
- [ ] Opened browser to `http://localhost:8080`
- [ ] UI loaded without errors
- [ ] Status page shows daemon running
- [ ] Workspace shows code location

#### Test Execution
- [ ] Created or opened a job/asset
- [ ] Launched a test run
- [ ] Run completed successfully
- [ ] Logs visible in UI
- [ ] Run appears in database: 
  ```sql
  SELECT run_id, status, create_timestamp FROM runs ORDER BY create_timestamp DESC LIMIT 5;
  ```

### 4. Performance & Monitoring
- [ ] Checked resource usage (CPU/Memory)
- [ ] Database connection count is reasonable
- [ ] No connection pool exhaustion
- [ ] Response times acceptable

## Production Readiness Checklist

### 1. Security
- [ ] Database password stored in Kubernetes Secret (not values.yaml)
- [ ] SSL/TLS configured for database connection (if required)
- [ ] RBAC configured appropriately
- [ ] Network policies in place (if required)

### 2. High Availability
- [ ] Database has backup strategy
- [ ] Backup includes both `fndb` and `dagster_db`
- [ ] Tested backup restore procedure
- [ ] Documented RTO/RPO

### 3. Resource Limits
- [ ] Set resource requests for webserver
- [ ] Set resource limits for webserver
- [ ] Set resource requests for daemon
- [ ] Set resource limits for daemon
- [ ] Set resource requests for user deployments
- [ ] Set resource limits for user deployments

### 4. Monitoring & Alerting
- [ ] Database monitoring configured
- [ ] Pod health monitoring configured
- [ ] Alerting for pod failures
- [ ] Alerting for database connection issues
- [ ] Alerting for disk space (database)
- [ ] Log aggregation configured

### 5. Documentation
- [ ] Updated deployment documentation
- [ ] Documented database connection details
- [ ] Created runbook for common issues
- [ ] Documented rollback procedure
- [ ] Updated team wiki/knowledge base

## Rollback Checklist

### If Something Goes Wrong

#### Immediate Actions
- [ ] Captured pod logs before deletion
- [ ] Captured database state
- [ ] Noted exact error messages

#### Rollback Steps
- [ ] Reverted values.yaml changes
- [ ] Ran Helm upgrade with previous config
- [ ] Verified pods recovered
- [ ] Tested basic functionality
- [ ] Documented what went wrong

## Common Issues Reference

| Symptom | Likely Cause | Quick Fix |
|---------|--------------|-----------|
| CrashLoopBackOff | DB not reachable | Check `postgresqlHost` value |
| "database does not exist" | Database not created | Create `dagster_db` manually |
| "password authentication failed" | Wrong secret/password | Verify secret exists and has correct key |
| "permission denied" | User lacks privileges | Grant CREATE/CREATEDB to user |
| Duplicate PostgreSQL pod | Subchart not disabled | Set `postgresql.enabled: false` |
| Connection timeout | Network issue | Check service name and port |

## Success Criteria

All of the following must be true:
- ✅ Dagster pods running without restarts
- ✅ No Dagster PostgreSQL pod exists
- ✅ Dagster UI accessible and functional
- ✅ Test job executes successfully
- ✅ Dagster tables exist in `dagster_db`
- ✅ Separate from Federated Node tables in `fndb`
- ✅ Database connections stable
- ✅ No errors in pod logs
- ✅ Resource usage within limits

## Sign-off

**Configured by:** _________________ **Date:** _________

**Validated by:** _________________ **Date:** _________

**Approved for Production:** _______ **Date:** _________

## Notes

```
[Add any deployment-specific notes, observations, or issues here]








```

---

**Related Documentation:**
- Full Setup Guide: `DAGSTER_DATABASE_SETUP.md`
- Example Configuration: `k8s/federated-node/dagster-external-db-example.yaml`
- Validation Script: `scripts/validate_dagster_db.sh`
