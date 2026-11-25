# Plan: shared clients (fednode/2, #696)

Status: existing PR (shared nexus client); rework not started.
- Rename `nexus/fednode` (`fednode`) to the `fednode` package, flattened (no doubled folder). pyproject name `fednode`.
- Move in: `http.py` (merge `fednode/http.py` with nexus-api `clients/outbound.py`), `clients/nexus` (api + models),
  `clients/keycloak` (login from nexus-api keycloak.py, kc-init common.py; admin API; signing keys),
  `clients/dagster` (nexus-api clients/dagster.py + fncli sensors.py), `clients/kubernetes` (KubernetesClient with explicit
  in_cluster|kubeconfig, loaded once via lru_cache on first use; MountedSecret replacing the four secret readers; valid_name
  from kubernetes_names.py), `clients/git` (GitProvider, GitHubClient, GiteaClient from Dagster + fncli; GitUri).
- Switch nexus-api, Dagster, the operator, kc-init and build/alpine/migrate-docker-secret.py to them. Callers catch
  ClientError/ClientTimeout, never requests exceptions.
- Install as a path dependency in every image (Dockerfiles, pyproject, pip-compile, CI, Tilt, bake).
- No settings here (they land in "unified settings"). If too big: rename as pure moves first, then the switch-over.
