# Gitea Deployment Guide for PHEMS Federated Node

## Overview

Gitea is a self-hosted Git service that serves as the results repository backend for the PHEMS federated node. This guide documents how to deploy and access Gitea locally using the Helm chart.

## Architecture

Gitea is deployed as a Kubernetes pod within the federated node Helm chart. The deployment includes:

- **Container Image**: `gitea/gitea:1.27.0`
- **Database**: SQLite (in-container, no external dependencies)
- **Storage**: EmptyDir volumes (suitable for development)
- **Access**: ClusterIP service on port 3000 (HTTP) and port 22 (SSH)

## Deployment

### Prerequisites

- Kubernetes cluster running (kind cluster with `kind-fn`)
- Helm 3.x installed
- `kubectl` configured to access the cluster

### Current Status

Gitea is currently deployed and accessible in the Kubernetes cluster running locally. The deployment was added to the federated-node Helm chart via:

1. **Custom Deployment Template**: `/k8s/federated-node/templates/gitea-deployment.yaml`
   - Creates a ConfigMap with Gitea app.ini configuration
   - Deploys Gitea pod with SQLite database
   - Exposes service on port 3000

2. **Configuration**: Located in `k8s/federated-node/dev.values.yaml`
   - Gitea admin account: username `admin`, password `admin`
   - Open registration enabled (no authentication required)
   - SQLite database at `/data/gitea.db`

### Deploy Gitea

To deploy Gitea as part of the federated node:

```bash
cd k8s/federated-node

# Ensure Helm dependencies are up to date
helm dependency update

# Deploy with Gitea enabled
helm upgrade fn-dev . -n fn -f dev.values.yaml --set gitea.enabled=true --timeout 5m
```

### Accessing Gitea

#### Within the Cluster

Gitea is accessible at: `http://gitea.fn.svc:3000/`

From within other pods in the cluster, you can reach Gitea using:
- URL: `http://gitea:3000/`
- SSH: `ssh://git@gitea:22/`

#### From Local Machine (Port-Forward)

To access Gitea from your local machine:

```bash
# Forward local port 3000 to Gitea service
kubectl port-forward -n fn svc/gitea 3000:3000

# Access at http://localhost:3000
```

#### Initial Login

- **Username**: `admin`
- **Password**: `admin`
- **Email**: `admin@example.com`

## Configuration

### Gitea Admin Account

The admin account is created during first initialization with environment-based configuration:

- Username: `admin`
- Password: `admin`
- Email: `admin@example.com`

### Database Configuration

Currently using SQLite for simplicity in development:
- Type: SQLite3
- Location: `/data/gitea.db` (in container)
- No external database required

### Server Configuration

- Domain: `gitea.fn.svc` (in-cluster)
- Root URL: `http://gitea.fn.svc:3000/`
- HTTP Port: 3000
- SSH Port: 22

### Security Settings

For development purposes:
- Registration: Enabled
- External registration only: Disabled
- Sign-in required: Disabled
- User visibility: Public
- Keep email private: Disabled

## Common Tasks

### Create a Repository

1. Log in with admin account at `http://gitea.fn.svc:3000/`
2. Click the `+` icon and select "New Repository"
3. Set repository name and description
4. Click "Create Repository"

### Push Code to Gitea

Within a Kubernetes pod (e.g., Dagster):

```bash
# Clone an existing repository
git clone http://gitea:3000/admin/my-repo.git
cd my-repo

# Add changes and push
git add .
git commit -m "Initial commit"
git push origin main

# For SSH (requires SSH key setup)
git clone ssh://git@gitea:22/admin/my-repo.git
```

### Create API Token

1. Log in to Gitea at `http://gitea.fn.svc:3000/`
2. Go to Settings > Applications
3. Click "New Access Token"
4. Select desired scopes and create
5. Copy and save the token

### Git Operations with Authentication

```bash
# Using HTTP with personal access token
git clone http://admin:TOKEN@gitea:3000/admin/my-repo.git

# Or set in remote URL
git remote set-url origin http://admin:TOKEN@gitea:3000/admin/my-repo.git
```

## Troubleshooting

### Gitea Pod Not Starting

Check pod status:
```bash
kubectl get pods -n fn | grep gitea
kubectl describe pod -n fn <gitea-pod-name>
kubectl logs -n fn <gitea-pod-name>
```

### Cannot Connect to Gitea

1. Verify pod is running: `kubectl get pods -n fn | grep gitea`
2. Check service: `kubectl get svc -n fn gitea`
3. Test connectivity: `kubectl port-forward -n fn svc/gitea 3000:3000`
4. Verify DNS: `kubectl exec -it <pod-name> -n fn -- nslookup gitea.fn.svc`

### Gitea Shows Database Error

The SQLite database might be corrupted. To reset:

1. Delete the Gitea pod: `kubectl delete pod -n fn <gitea-pod-name>`
2. Wait for it to be recreated
3. Log in again with credentials

**Note**: This will lose all Gitea data (repositories, users). Only do this for development.

### Configuration Changes Not Applied

Update the ConfigMap and restart the pod:

```bash
# Edit k8s/federated-node/templates/gitea-deployment.yaml
# Then redeploy:
helm upgrade fn-dev . -n fn -f dev.values.yaml --set gitea.enabled=true
```

## Storage Considerations

### Current Setup (Development)

- **Storage Type**: EmptyDir (temporary, pod-scoped)
- **Data Persistence**: Lost when pod is deleted
- **Suitable for**: Development, testing

### Production Setup (Future)

For production, consider:

```yaml
persistence:
  enabled: true
  storageClass: local-path  # or your preferred storage class
  size: 50Gi  # adjust as needed
  mountPath: /data
```

Update in `k8s/federated-node/values.yaml` and redeploy.

## Integration with PHEMS Components

### Dagster Integration

Gitea can serve as a results repository backend for Dagster job results. The `transfer_op` in Dagster can:

1. Push job results to a Gitea repository
2. Create commits with result metadata
3. Use git commit SHA for audit trails

### Results Repository Configuration

The federated node webserver uses Gitea to store:
- Experiment results
- Audit trails (git commit history)
- Metadata about task executions

See `DVC_GITEA_RESULTS_PLAN.md` for architecture details.

## Monitoring and Logging

### View Gitea Logs

```bash
kubectl logs -n fn gitea-<pod-id>  # Last 100 lines
kubectl logs -n fn gitea-<pod-id> -f  # Follow logs
kubectl logs -n fn gitea-<pod-id> --tail=500  # Last 500 lines
```

### Check Gitea Health

```bash
# Port-forward and test
kubectl port-forward -n fn svc/gitea 3000:3000 &
curl http://localhost:3000/
kill %1
```

### Metrics (if needed)

Gitea doesn't expose Prometheus metrics by default. For monitoring in production:

1. Enable metrics in app.ini: `METRICS = true`
2. Access at: `http://gitea:3000/metrics`

## Security Notes

### Development Only

This configuration is for development use only. For production:

1. **Change default admin password**
2. **Disable open registration** (set `DISABLE_REGISTRATION: true`)
3. **Configure HTTPS/TLS**
4. **Use persistent storage** with proper backups
5. **Set up regular backups** of the Gitea database and repositories
6. **Enable OAuth2/LDAP** for authentication
7. **Review and limit API access** with scoped tokens

### SSH Key Management

For Dagster and other components to access Gitea via SSH:

1. Generate SSH keypair in component pod
2. Add public key to Gitea user account
3. Configure SSH access in component configuration

See Gitea documentation for SSH setup.

## Related Documentation

- [DVC_GITEA_RESULTS_PLAN.md](./DVC_GITEA_RESULTS_PLAN.md) - Results delivery architecture
- [DVC_GITEA_DATABASE_PLAN.md](./DVC_GITEA_DATABASE_PLAN.md) - Database schema for results backend
- [DVC_GITEA_AGENTS_PLAN.md](./DVC_GITEA_AGENTS_PLAN.md) - Agent architecture for results delivery

## References

- [Gitea Documentation](https://docs.gitea.com/)
- [Gitea Helm Chart](https://gitea.com/gitea/helm-chart)
- [Gitea Configuration Reference](https://docs.gitea.com/en-us/administration/configuration-cheat-sheet)
