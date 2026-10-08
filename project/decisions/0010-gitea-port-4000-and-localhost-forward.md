# 0010. Gitea on port 4000 in-cluster, localhost forward, fncli host translation

- Status: Accepted

## Context

Gitea is deployed with the chart as the development (and optionally real) git host. Dagster pods reach it by service DNS; developers and `fncli` run on the host. The URL stored on a repository must work from inside the cluster, and port 3000 collides with the Dagster UI forward.

## Decision

- The Gitea service listens on **4000** (`gitea.service.http.port`, default 4000, `ROOT_URL http://gitea.<ns>.svc:4000`). The default Gitea `api_uri` in Dagster config is `http://gitea.fn.svc:4000/api/v1`.
- Repositories are registered with in-cluster URLs (`gitea.fn.svc:4000/...`) so the sensors and delivery pod, which clone with `<api_uri scheme>://<uri>.git`, work unchanged.
- Tilt forwards `svc/gitea` to `localhost:4000` (same port) and the Dagster UI to `localhost:3000`.
- `fncli` reaches Gitea at `GITEA_URL=http://localhost:4000`. `to_host_url` rewrites any host ending in `fn.svc` to `localhost`, same port, and leaves other URLs alone.

## Consequences

- One stored URL works for pods and, through translation, for host tooling.
- Needs the Tilt port-forward running for host-side commands.
- Gitea's container port is 3000 internally; only the service port is 4000.

## Alternatives considered

- **Port 3000 (Gitea default)**: collides with the Dagster UI forward.
- **Store localhost URLs on repositories**: breaks the pods.
- **Ingress/host names**: more setup than a dev loop needs.
