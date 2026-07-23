# Tilt Implementation Summary

## What Is This?

A complete local development environment for the federated_node project that replaces manual image building and `kubectl rollout restart` with **instant autoreloads** and a **unified dashboard**.

## The Old Way (Manual)

```bash
# Edit code
vi dagster/app/definitions/jobs.py

# Manually rebuild
./scripts/build_image.sh dagster v40

# Manually restart
kubectl rollout restart deployment/fn-dev-dagster-user-deployments-dagster-fn -n fn

# Wait for pod to restart (~2 minutes)

# Test changes
```

## The New Way (Tilt)

```bash
# Edit code
vi dagster/app/definitions/jobs.py

# Tilt detects change
# File syncs into container
# Dagster reloads instantly
# Test changes (~1 second)
```

## Quick Setup

```bash
# 1. Start cluster + registries
make cluster up

# 2. Deploy Helm (one time)
make deploy

# 3. Start Tilt
tilt up

# Done! Now edit code and see changes instantly
```

## What Gets Deployed

Tilt manages:

| Component | Image | Behavior |
|-----------|-------|----------|
| **Webserver** | `localhost:5001/webserver-fn:v40` | Flask on port 5000; instant reload for `.py` changes |
| **Dagster User Code** | `localhost:5001/dagster-fn:v40` | Instant reload for `.py` changes |
| **Dagster Daemon** | Same image | Uses user code from above |
| **Dagster UI** | Same image | Uses user code from above; port 3000 |
| **Database** | Postgres | Created by Helm; persistent via local PV |
| **Keycloak** | Configured via Helm | Authentication |
| **Other services** | Various | All configured by Helm release |

## How It Works

### File Changes

1. **Python code** (`webserver/app/` or `dagster/app/`)
   - Tilt syncs file directly into running container
   - App auto-reloads (Flask, Dagster)
   - Result: instant feedback (~1 sec)

2. **Dependencies** (`requirements.txt`, `setup.py`)
   - Tilt rebuilds Docker image
   - Pushes to localhost:5001
   - K8s pulls new image, restarts pod
   - Result: new dependencies available (~30-60 sec)

### Docker Registry Flow

```
Your machine (Docker build)
    ↓
localhost:5001 (kind-registry container)
    ↓
Kind cluster (K8s pulls from registry)
    ↓
Pods running with new images
```

The local registry caches images, so rebuilds are fast.

## Key Features

✅ **Instant Python reloads** — No rebuild needed
✅ **Smart dependency handling** — Detects when rebuild is needed
✅ **Unified dashboard** — See all services in one place
✅ **Streaming logs** — Real-time visibility into what's happening
✅ **Port forwarding** — Services accessible at localhost:5000 and 3000
✅ **Helm integration** — Full stack deployment via Tilt

## File Organization

```
federated_node/
├── Tiltfile                    # Main Tilt config (in root)
├── .tiltignore                 # File watch patterns (in root)
├── .tilt/
│   ├── TILT.md                 # Comprehensive guide
│   ├── TILT_QUICKSTART.md      # Quick reference
│   └── TILT_SETUP_SUMMARY.md   # This file
├── scripts/
│   ├── cluster.sh              # Start/stop Kind + registries
│   ├── deploy.sh          # Deploy Helm release (called by Tilt)
│   └── ...other scripts
└── ...code
```

## Makefile Integration

```bash
# Cluster management
make cluster up              # Start Kind + registries
make cluster down            # Stop Kind, keep registries
make cluster down --remove-registries  # Full cleanup

# Helm deployment (one time)
make deploy             # Deploy all K8s resources + Helm release

# Tilt development
make tilt-up                 # Start Tilt
make tilt-down               # Stop Tilt
make tilt-open               # Open dashboard
make tilt-logs               # View logs
```

## Access Points

Once everything is running:

| Service | URL | Purpose |
|---------|-----|---------|
| Webserver API | http://localhost:5000 | Flask REST API |
| Dagster UI | http://localhost:3000 | Orchestration UI |
| Tilt Dashboard | http://localhost:10350 | Monitoring all services |

## Performance Impact

| Task | Before | After | Improvement |
|------|--------|-------|-------------|
| Edit Python file, see change | 2-3 min | ~1 sec | **100-180x faster** |
| Add dependency, see available | 2-3 min | ~1 min | **2-3x faster** |
| Restart service | Manual | Auto | **Automatic** |
| View logs | Manual `kubectl logs` | Dashboard | **Much easier** |

## What Changed

### New Files Created

- `Tiltfile` — Tilt configuration
- `.tiltignore` — File watch patterns
- `scripts/cluster.sh` — Unified cluster management
- `scripts/deploy.sh` — Helm deployment (called by Tilt)
- `.tilt/TILT.md`, `.tilt/TILT_QUICKSTART.md`, `.tilt/TILT_SETUP_SUMMARY.md` — Documentation

### Makefile Additions

- `make cluster up/down` — Manage Kind cluster
- `make tilt-up/down` — Manage Tilt

### No Changes Needed To

- `webserver/` code — Works as-is
- `dagster/` code — Works as-is
- `k8s/` Helm charts — Works as-is
- `deploy.sh` — Still available for non-Tilt deployment

## Workflow Comparison

| Aspect | Manual | Tilt |
|--------|--------|------|
| **Edit code** | Manual edit | Edit (auto-watch) |
| **Rebuild** | Manual script | Automatic |
| **Restart service** | Manual kubectl | Automatic |
| **Code feedback** | 2-3 minutes | ~1 second |
| **View logs** | Manual kubectl logs | Dashboard |
| **Dependency changes** | Manual process | Smart fallback |

## When to Use What

**Use `deploy.sh`** when:
- Setting up a fresh cluster for CI/CD
- You want a minimal, one-shot deployment
- You're not actively developing

**Use `tilt up`** when:
- You're actively developing and testing code
- You want instant feedback on changes
- You want visibility into all services at once
- You're iterating on Dagster jobs, Flask routes, etc.

## Next Steps

1. Read `.tilt/TILT_QUICKSTART.md` for quick reference
2. Run `make cluster up` to start the cluster
3. Run `make deploy` to deploy (one time)
4. Run `tilt up` to start developing
5. Read `.tilt/TILT.md` for detailed documentation
6. Edit code and watch changes happen instantly!

## Troubleshooting

**Resources not deploying?**
Make sure Helm was deployed:
```bash
make deploy
kubectl get all -n fn
```

**Changes not showing?**
- Check Tilt dashboard for errors
- Ensure file is in watched paths (see TILT.md)
- For dependencies, rebuild is automatic but slower

**Need to reset?**
```bash
tilt down
make cluster down
make cluster up
make deploy
tilt up
```

## Questions?

See `.tilt/TILT.md` for comprehensive documentation.
