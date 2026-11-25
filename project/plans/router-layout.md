# Plan: router layout (refactor/5, #763)

Status: complete. URLs do not change.

| Today | Change |
|---|---|
| `main.py`: `/`, `/ready_check`, `/health_check` | to `healthcheck_api.py`, open router `probes_router` |
| `main.py`: `/login`, `/refresh_token` | to new `auth_api.py` |
| `users_api.py`: `reset-password` (open router) | to `auth_api.py` |
| `main.py` | deleted |
| `healthcheck_api.py`: check functions (`prepare_*_health`) | to `app/health/` (`datasets.py`, `secrets.py`, `providers.py`, `repositories.py`) |
| `healthcheck_api.py`: `_run_all` (parallel threads) | to `app/health/run.py` |
| per-resource health routes (global and project) | into each resource's router, calling `app/health/*` |
| `/global/healthcheck`, `/projects/{id}/healthcheck` | stay in `healthcheck_api.py` (signed-in router), built from `app/health/*` |
| every router | grouped by URL scope: `app/globals/` (datasets, secrets, providers, repositories, users) and `app/projects/` (projects, tasks, results, repositories); `_api.py` names kept |
| `OPEN_ROUTERS` | `healthcheck_api.probes_router`, `auth_api.router` |

Rules: routers hold endpoints only; logic lives outside them. Keep it a move: no behaviour change, so the diff reads as renames.
