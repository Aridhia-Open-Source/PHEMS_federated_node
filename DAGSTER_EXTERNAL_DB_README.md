# Dagster External Database Setup

## Overview

This configuration allows Dagster to use your existing PHEMS Federated Node PostgreSQL database instead of deploying its own separate PostgreSQL instance. This results in simpler infrastructure, reduced resource usage, and easier management.

## Benefits

- 🚀 **Resource Efficiency**: ~25% reduction in database resources
- 🔧 **Simplified Operations**: Single PostgreSQL instance to manage
- 💾 **Unified Backups**: One backup process for all data
- 📊 **Better Monitoring**: Single point for database monitoring
- 💰 **Cost Savings**: Fewer pods and resources required

## Quick Start

1. **Read the documentation:**
   ```bash
   cat DAGSTER_DOCS_INDEX.md
   ```

2. **Create Dagster database:**
   ```bash
   kubectl exec -it <postgres-pod> -- psql -U <username>
   CREATE DATABASE dagster_db;
   GRANT ALL PRIVILEGES ON DATABASE dagster_db TO <username>;
   ```

3. **Update configuration:**
   - See `k8s/federated-node/dagster-external-db-example.yaml` for reference
   - Update `k8s/federated-node/values.yaml` with database settings
   - Create `k8s/federated-node/templates/dagster-env-configmap.yaml`

4. **Deploy:**
   ```bash
   helm upgrade --install federated-node ./k8s/federated-node \
     --namespace <namespace> \
     --values ./k8s/federated-node/values.yaml
   ```

5. **Validate:**
   ```bash
   ./scripts/validate_dagster_db.sh
   ```

## Documentation

| Document | Purpose | Best For |
|----------|---------|----------|
| **[DAGSTER_DOCS_INDEX.md](./DAGSTER_DOCS_INDEX.md)** | Documentation overview and navigation | Start here |
| **[DAGSTER_DATABASE_SETUP.md](./DAGSTER_DATABASE_SETUP.md)** | Complete setup guide with detailed explanations | Initial setup, troubleshooting |
| **[DAGSTER_SETUP_CHECKLIST.md](./DAGSTER_SETUP_CHECKLIST.md)** | Interactive deployment checklist | During deployment, validation |
| **[DAGSTER_QUICK_REFERENCE.md](./DAGSTER_QUICK_REFERENCE.md)** | Daily operations commands | Day-to-day management |
| **[DAGSTER_ARCHITECTURE_DIAGRAMS.md](./DAGSTER_ARCHITECTURE_DIAGRAMS.md)** | Visual architecture diagrams | Understanding the setup |
| **[dagster-external-db-example.yaml](./k8s/federated-node/dagster-external-db-example.yaml)** | Configuration example | Reference during setup |

## Key Configuration Changes

### 1. Database Connection (values.yaml)

```yaml
db:
  host: postgres-service  # ADD: Your PostgreSQL service name
  user: test             # ADD: Database username
  secret:
    name: backend-secrets
    key: PGPASSWORD
```

### 2. Disable Dagster PostgreSQL Subchart

```yaml
dagster:
  postgresql:
    enabled: false  # CHANGE from true to false
```

### 3. Configure External Database Connection

```yaml
dagster:
  postgresqlHost: postgres-service
  postgresqlDatabase: dagster_db  # NEW database for Dagster
  generatePostgresqlPasswordSecret: false  # CHANGE from true
```

### 4. Create ConfigMap Template

Create `k8s/federated-node/templates/dagster-env-configmap.yaml` - see example in documentation.

## Validation

Run the automated validation script:

```bash
NAMESPACE=<your-namespace> ./scripts/validate_dagster_db.sh
```

Expected result: `✓ 6/6 checks passed`

## Architecture

```
┌─────────────────────────────────────┐
│      Shared PostgreSQL Pod          │
│                                     │
│  ┌──────────┐    ┌──────────────┐  │
│  │   fndb   │    │  dagster_db  │  │
│  │ (FN data)│    │ (Dagster)    │  │
│  └─────▲────┘    └─────▲────────┘  │
└────────┼───────────────┼────────────┘
         │               │
    ┌────┴────┐    ┌────┴─────┐
    │ Backend │    │ Dagster  │
    │   Pod   │    │   Pods   │
    └─────────┘    └──────────┘
```

See [DAGSTER_ARCHITECTURE_DIAGRAMS.md](./DAGSTER_ARCHITECTURE_DIAGRAMS.md) for detailed diagrams.

## Common Issues

| Issue | Solution |
|-------|----------|
| Pods CrashLoopBackOff | Check database connectivity and credentials |
| Database not found | Create `dagster_db` manually |
| Connection refused | Verify `postgresqlHost` service name |
| Permission denied | Grant CREATE privileges to database user |

See [troubleshooting guide](./DAGSTER_DATABASE_SETUP.md#troubleshooting) for detailed solutions.

## Requirements

- PostgreSQL 12+ (same instance used by Federated Node)
- Kubernetes 1.19+
- Helm 3.0+
- Database user with CREATE DATABASE privilege (or pre-created `dagster_db`)

## Support

1. Check documentation in `DAGSTER_DOCS_INDEX.md`
2. Run validation script: `./scripts/validate_dagster_db.sh`
3. Review logs: `kubectl logs <pod-name>`
4. Consult troubleshooting guide

## Migration from Separate PostgreSQL

If you're currently running Dagster with its own PostgreSQL instance:

1. Backup Dagster data:
   ```bash
   kubectl exec <dagster-postgres-pod> -- pg_dump -U test test > dagster_backup.sql
   ```

2. Follow setup guide to configure external database

3. Restore data to new database:
   ```bash
   kubectl exec <shared-postgres-pod> -- psql -U test dagster_db < dagster_backup.sql
   ```

4. Verify and delete old PostgreSQL StatefulSet

See [complete migration guide](./DAGSTER_DATABASE_SETUP.md#rollback-plan) for details.

## Quick Commands

```bash
# Health check
./scripts/validate_dagster_db.sh

# Access UI
kubectl port-forward svc/<release>-dagster-webserver 8080:80

# View logs
kubectl logs deployment/<release>-dagster-webserver --tail=50 -f

# Check database
kubectl exec <postgres-pod> -- psql -U test -d dagster_db -c '\dt'

# Restart components
kubectl rollout restart deployment/<release>-dagster-webserver
```

See [DAGSTER_QUICK_REFERENCE.md](./DAGSTER_QUICK_REFERENCE.md) for more commands.

## Contributing

When updating this configuration:

1. Update relevant documentation
2. Test changes in development environment
3. Run validation script
4. Update this README if needed
5. Document any new patterns or issues

## License

Same as PHEMS Federated Node project.

## Additional Resources

- [Dagster Documentation](https://docs.dagster.io/)
- [Dagster Helm Chart](https://github.com/dagster-io/dagster/tree/master/helm/dagster)
- [PostgreSQL Documentation](https://www.postgresql.org/docs/)

---

**Last Updated:** April 2026  
**Version:** 1.0  
**Maintained By:** PHEMS Team
