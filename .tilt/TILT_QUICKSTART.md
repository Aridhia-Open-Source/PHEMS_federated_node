# Tilt Quick Start Reference

## Setup (One Time)

```bash
# 1. Install Tilt
curl -fsSL https://raw.githubusercontent.com/tilt-dev/tilt/master/scripts/install.sh | bash

# 2. Start cluster + registries
make cluster up

# 3. Deploy Helm (one time)
make deploy

# 4. Start Tilt
tilt up
```

## During Development

### Watch for changes automatically

Once everything is deployed, Tilt automatically watches and reloads:
- `nexus/api/app/` → nexus-api code changes (instant reload)
- `nexus/api/requirements.txt`, `setup.py`, `alembic.ini` → Full rebuild
- `dagster/app/` → User code changes (the process restarts, then `dagster-reload` makes sure the Dagster code location is loaded again; if it logs an error, look at the code server pod log)
- `dagster/fncli/`, tests and docs → no rebuild
- `dagster/requirements.txt`, `setup.py` → Full rebuild

### Access services
- **nexus-api docs**: http://localhost:5000/docs
- **Dagster UI**: http://localhost:3000
- **Tilt Dashboard**: http://localhost:10350

The `dagster-reload` resource prints this list in the Tilt log once the Dagster code location has loaded, and again after each reload. To add a URL, put `DEV_URLS.append(('Name', 'http://localhost:PORT'))` next to the port-forward in the `Tiltfile`, above the last section.

### View logs
```bash
# Tilt dashboard (easiest - shows all services)
tilt open

# Or from command line
kubectl logs -f deployment/nexus-api -n fn
kubectl logs -f deployment/fn-dev-dagster-daemon -n fn
kubectl logs -f deployment/fn-dev-dagster-user-deployments-dagster-fn -n fn
```

### Force rebuild a service
```bash
tilt trigger nexus-api
tilt trigger fn-dev-dagster-user-deployments-dagster-fn
```

## Common Commands

| Task | Command |
|------|---------|
| Start cluster (one time) | `make cluster up` |
| Deploy Helm (one time) | `make deploy` |
| Show who owns the dev cluster | `make deploy-owner` |
| Start Tilt | `tilt up` or `make tilt-up` |
| Stop Tilt | `tilt down` or `make tilt-down` |
| View dashboard | `tilt open` or `make tilt-open` |
| View logs | `tilt logs` or `make tilt-logs` |
| Rebuild specific service | `tilt trigger <resource-name>` |
| Restart specific pod | `kubectl rollout restart deployment/<name> -n fn` |
| Check resource status | `kubectl get all -n fn` |

## Dev cluster ownership

The single dev cluster is owned by one worktree at a time. `make deploy` and `make upgrade` claim it (recorded in the `fn-dev-owner` ConfigMap in `default`) and `make teardown` releases it. A deploy from another worktree fails while it is owned; tear down from the owner, or rerun with `FORCE_OWNER=1` to take it over. `DEPLOY_BY` overrides the recorded user (default `$USER`). `make deploy-owner` shows the current owner.

## Troubleshooting

### Resources not deploying?
Make sure you've run `make deploy` before starting Tilt:
```bash
make deploy
kubectl get all -n fn
```

### Changes not showing up?
1. Check if file is in the watched paths (see TILT.md)
2. Check Tilt dashboard for errors
3. For dependency changes, Tilt rebuilds the image (takes longer)

### Pod stuck in CrashLoopBackOff?
```bash
kubectl describe pod <pod-name> -n fn
kubectl logs <pod-name> -n fn
```

### Can't access services at localhost:5000/3000?
Check port forwards are active:
```bash
kubectl get svc -n fn
netstat -tlnp | grep 5000  # Should show tilt process
```

### Need to reset everything?
```bash
tilt down
make cluster down
make cluster up
make deploy
tilt up
```

## File Change Examples

### Example 1: Update nexus-api code
```bash
# Edit nexus/api/app/routes.py
vi nexus/api/app/routes.py

# Tilt detects change, syncs file, FastAPI auto-reloads
# Instantly see change at http://localhost:5000
```

### Example 2: Add Python dependency to nexus-api
```bash
# Add to nexus/api/requirements.txt
echo "new-package==1.0.0" >> nexus/api/requirements.txt

# Tilt detects change, rebuilds image, restarts pod
# Takes ~30 seconds depending on package size
```

### Example 3: Update Dagster user code
```bash
# Edit dagster/app/definitions/jobs.py
vi dagster/app/definitions/jobs.py

# Tilt detects change, syncs file, Dagster reloads user code
# See change in Dagster UI
```

## Important Paths

- **nexus-api app**: `nexus/api/app/` → `/nexus/api/app/` in container
- **nexus-api migrations**: `nexus/api/migrations/` → Rebuilds image if changed
- **Dagster app**: `dagster/app/` → `/opt/dagster/home/app/` in container
- **Both registries**: `localhost:5001` (push and pull)
- **Kubectl namespace**: `fn` (set in .dev.env)

## Next Steps

See `.tilt/TILT.md` for detailed documentation, or check the [Tilt docs](https://docs.tilt.dev/).
