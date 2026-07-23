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
- `webserver/app/` → Webserver code changes (instant reload)
- `webserver/requirements.txt`, `setup.py`, `alembic.ini` → Full rebuild
- `dagster/app/` → User code changes (instant reload)
- `dagster/requirements.txt`, `setup.py` → Full rebuild

### Access services
- **Webserver**: http://localhost:5000
- **Dagster UI**: http://localhost:3000
- **Tilt Dashboard**: http://localhost:10350

### View logs
```bash
# Tilt dashboard (easiest - shows all services)
tilt open

# Or from command line
kubectl logs -f deployment/backend -n fn
kubectl logs -f deployment/fn-dev-dagster-daemon -n fn
kubectl logs -f deployment/fn-dev-dagster-user-deployments-dagster-fn -n fn
```

### Force rebuild a service
```bash
tilt trigger backend
tilt trigger fn-dev-dagster-user-deployments-dagster-fn
```

## Common Commands

| Task | Command |
|------|---------|
| Start cluster (one time) | `make cluster up` |
| Deploy Helm (one time) | `make deploy` |
| Start Tilt | `tilt up` or `make tilt-up` |
| Stop Tilt | `tilt down` or `make tilt-down` |
| View dashboard | `tilt open` or `make tilt-open` |
| View logs | `tilt logs` or `make tilt-logs` |
| Rebuild specific service | `tilt trigger <resource-name>` |
| Restart specific pod | `kubectl rollout restart deployment/<name> -n fn` |
| Check resource status | `kubectl get all -n fn` |

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

### Example 1: Update webserver code
```bash
# Edit webserver/app/routes.py
vi webserver/app/routes.py

# Tilt detects change, syncs file, Flask auto-reloads
# Instantly see change at http://localhost:5000
```

### Example 2: Add Python dependency to webserver
```bash
# Add to webserver/requirements.txt
echo "new-package==1.0.0" >> webserver/requirements.txt

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

- **Webserver app**: `webserver/app/` → `/webserver/app/` in container
- **Webserver migrations**: `webserver/migrations/` → Rebuilds image if changed
- **Dagster app**: `dagster/app/` → `/opt/dagster/home/app/` in container
- **Both registries**: `localhost:5001` (push and pull)
- **Kubectl namespace**: `fn` (set in .dev.env)

## Next Steps

See `.tilt/TILT.md` for detailed documentation, or check the [Tilt docs](https://docs.tilt.dev/).
