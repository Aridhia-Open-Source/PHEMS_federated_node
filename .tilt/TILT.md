# Tilt Development Guide

Tilt is a local development environment that enables instant reloads for your Dagster code, daemon, and webserver backend without manual rebuilds or restarts.

## Architecture Overview

```
┌─────────────────────────────────────────────────────────┐
│ Your Development Machine                                │
├─────────────────────────────────────────────────────────┤
│                                                         │
│  ┌──────────────┐     ┌───────────────────────────┐   │
│  │   Your Code  │────▶│   Tilt File Watcher       │   │
│  │              │     │  - Detects changes        │   │
│  └──────────────┘     │  - Rebuilds images        │   │
│                       │  - Deploys to K8s         │   │
│                       │  - Provides dashboard     │   │
│                       └───────────────────────────┘   │
│                              ↓                         │
│  ┌────────────────────────────────────────────────┐   │
│  │   Docker Registries (localhost:5001-5003)      │   │
│  └────────────────────────────────────────────────┘   │
│                              ↓                         │
│  ┌────────────────────────────────────────────────┐   │
│  │   Kind Kubernetes Cluster (in Docker)          │   │
│  │  - Webserver Pod (Flask)                       │   │
│  │  - Dagster Daemon Pod                          │   │
│  │  - Dagster User Code Pod                       │   │
│  │  - Dagster Webserver Pod                       │   │
│  │  - Database Pod                                │   │
│  │  - Other services (Keycloak, etc.)             │   │
│  └────────────────────────────────────────────────┘   │
│                                                         │
└─────────────────────────────────────────────────────────┘
```

## Getting Started

### Prerequisites

- **Tilt**: https://docs.tilt.dev/install.html
- **Docker**: Running on your machine
- **Kind cluster**: Created by `make cluster up`
- **kubectl**: Configured to access the Kind cluster

### Installation

```bash
# Install Tilt
curl -fsSL https://raw.githubusercontent.com/tilt-dev/tilt/master/scripts/install.sh | bash

# Verify
tilt version
```

### First-Time Setup

#### 1. Start the Cluster

```bash
make cluster up
```

This creates:
- Kind Kubernetes cluster named "fn"
- Three Docker registries (localhost:5001, 5002, 5003)
- Network connections between registries and cluster

#### 2. Deploy Helm (One-Time)

```bash
make deploy
```

This:
- Creates the `fn` namespace
- Sets up secrets for databases and authentication
- Deploys the full Helm release (all services, databases, etc.)

#### 3. Start Tilt

```bash
tilt up
```

Tilt will:
- Load the Tiltfile
- Build Docker images for webserver and Dagster
- Push images to localhost:5001
- Open the dashboard at http://localhost:10350

#### 4. Verify Deployment


```bash
# set the default namespace
kubectl config set-context --current --namespace=fn
```

```bash
# get running pods
kubectl get pods
```

Wait for all pods to be Running. Then access:
- **Webserver**: http://localhost:5000
- **Dagster UI**: http://localhost:3000
- **Tilt UI**: http://localhost:10350/

## How Tilt Works

### File Watching

Tilt watches specific file patterns and reacts based on what changed:

#### Python Code (Instant Reload)

```
webserver/app/routes.py changes
    ↓
Tilt detects change
    ↓
Syncs file into running container
    ↓
Flask auto-reloads
    ↓
Instant feedback (~1 second)
```

Paths: `webserver/app/**/*.py`, `dagster/app/**/*.py`

#### Dependencies (Smart Rebuild)

```
webserver/requirements.txt changes
    ↓
Tilt detects change
    ↓
Rebuilds Docker image with new dependencies
    ↓
Pushes to localhost:5001
    ↓
K8s restarts pod with new image
    ↓
Complete cycle (~30-60 seconds)
```

Paths: `requirements.txt`, `setup.py`, `pyproject.toml`, `alembic.ini`

### Image Building

Tilt uses the `docker_build_with_restart` extension to:

1. **Build**: Runs `docker build` locally
2. **Push**: Sends image to localhost:5001 (kind-registry)
3. **K8s Pulls**: Cluster sees imagePullPolicy: Always and fetches new image
4. **Restart**: Pod restarts with new image

All images are tagged with your configured `DOCKER_TAG` from `.dev.env`.

## Services Managed

| Service | Image | Port | Watch Paths | Notes |
|---------|-------|------|-------------|-------|
| Webserver | `localhost:5001/webserver-fn` | 5000 | `webserver/app/` | Flask app, instant reload |
| Dagster User Code | `localhost:5001/dagster-fn` | - | `dagster/app/` | User code, instant reload |
| Dagster Daemon | `localhost:5001/dagster-fn` | - | `dagster/app/` | Pulled from user code |
| Dagster UI | `localhost:5001/dagster-fn` | 3000 | `dagster/app/` | Pulled from user code |

All services are deployed via Helm under namespace `fn` (configurable via `.dev.env`).

## Development Workflow

### Editing Webserver Code

```bash
# Edit a route
nano webserver/app/routes.py

# Tilt detects change (< 1 second)
# File synced into container
# Flask reloads automatically
# Visit http://localhost:5000 to see changes
```

### Editing Dagster Code

```bash
# Edit a job definition
nano dagster/app/definitions/jobs.py

# Tilt detects change (< 1 second)
# File synced into container
# Dagster reloads user code automatically
# View changes in Dagster UI at http://localhost:3000
```

### Adding Dependencies

```bash
# Add to requirements
echo "new-package==1.0.0" >> webserver/requirements.txt

# Tilt detects change (< 1 second)
# Rebuilds Docker image (~20-30 seconds)
# Pod restarts with new dependencies
# Service is back up and running
```

## Common Tasks

### View Logs

**Tilt Dashboard** (recommended):
```bash
tilt open
# Shows all services with streaming logs
```

**Command Line**:
```bash
# Webserver logs
kubectl logs -f deployment/backend -n fn

# Dagster daemon logs
kubectl logs -f deployment/fn-dev-dagster-daemon -n fn

# Dagster user code pod logs
kubectl logs -f deployment/fn-dev-dagster-user-deployments-dagster-fn -n fn
```

### Force Rebuild a Service

```bash
# Rebuild and redeploy webserver
tilt trigger backend

# Rebuild and redeploy Dagster
tilt trigger fn-dev-dagster-user-deployments-dagster-fn
```

### Restart a Pod

```bash
kubectl rollout restart deployment/backend -n fn
kubectl rollout restart deployment/fn-dev-dagster-daemon -n fn
```

### Check Resource Status

```bash
# All resources in the namespace
kubectl get all -n fn

# Just deployments
kubectl get deployments -n fn

# Just pods with details
kubectl get pods -n fn -o wide

# Events (useful for debugging)
kubectl get events -n fn --sort-by='.metadata.creationTimestamp'
```

## Troubleshooting

### Helm Deploy Fails

```bash
# Check what went wrong
kubectl get all -n fn
kubectl get secrets -n fn
kubectl get events -n fn

# View detailed error
kubectl describe pod <pod-name> -n fn
```

### Images Not Updating

**Symptom**: Code changes don't appear in running containers

**Check**: Registry connectivity
```bash
docker ps | grep registry
docker exec $(docker ps -q -f ancestor=kindest/node) curl -s http://kind-registry:5000/v2/_catalog
```

**Fix**: Trigger a rebuild:
```bash
tilt trigger <resource-name>
```

### Pod Stuck in CrashLoopBackOff

```bash
# Check what's wrong
kubectl describe pod <pod-name> -n fn

# View logs
kubectl logs <pod-name> -n fn
```

### Can't Access Services at localhost:5000

**Check port forwards are active**:
```bash
tilt logs | grep "Port forward"
```

**Manual workaround**:
```bash
kubectl port-forward service/backend 5000:5000 -n fn
```

### Complete Reset

```bash
# Stop Tilt
tilt down

# Delete the cluster
make cluster down

# Start fresh
make cluster up
make deploy
tilt up
```

## Advanced Configuration

### Changing Watch Paths

Edit `Tiltfile` and update the `only=` and `live_update=` sections.

### Adding More Services

To monitor additional services (pypipes, github_transfer, etc.):

1. Add a `docker_build()` or `docker_build_with_restart()` block
2. Add a corresponding `k8s_resource()` block
3. Specify ports and labels

## Further Reading

- [Tilt Official Docs](https://docs.tilt.dev/)
- [Tilt Extensions](https://docs.tilt.dev/extensions.html)
- [K8s Resource API](https://docs.tilt.dev/api.html#k8s_resource)
