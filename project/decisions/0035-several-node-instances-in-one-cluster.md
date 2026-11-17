# 0035. Several node instances in one cluster, routed by hostname

Status: Proposed, 2026-11-17.

## Context

- **One cluster runs one node.** The chart, nexus-api and Dagster assume a single instance: Secret names, task namespaces, the database name and Keycloak users are fixed or come from one set of values.
- **Dev has one shared cluster.** One worktree owns it at a time (`scripts/deploy_owner.sh`). Agents and developers working on separate branches queue for it, or work without a running node.
- **Most day-to-day work is code in nexus-api or Dagster.** It does not need its own Keycloak, Postgres, Gitea or Traefik, only its own record and its own names.
- **Sites ask for more than one node.** Staging next to prod, one node per data custodian, or a new version beside the old one during an upgrade. Today each needs its own cluster.
- **Ports do not scale.** Port-forwards with an offset per worktree (5000, 5100, ...) are fragile under WSL and mean nothing in prod.

## Decision

### An instance name

- **Each node has an instance name,** one setting (`instance` in values, `FN_INSTANCE` in env). It defaults to today's names, so a single-node install is unchanged.
- **Every name the node creates comes from it:** Kubernetes Secrets, task namespaces and Jobs, the database name, Keycloak service users, and the Gitea org used in dev.
- **Instances share nothing they write.** Two instances in one cluster never write the same object.

### Layout in a cluster

- **One namespace per instance** holds its nexus-api, Dagster, nexus-ui and task namespace.
- **Shared across instances:** Traefik and its Gateway, the CRDs, the operator, and in dev the image registry.
- **Postgres and Keycloak are per instance by default.** A site may point instances at one server, with a database and a realm each; the chart takes external addresses for both.
- **The operator watches every namespace** and sends each custom resource to the nexus-api in its own namespace.
- **Network policies keep instances apart:** one instance's tasks cannot reach another's datasets or API.

### Routing by hostname

- **Each instance gets its own hostname** on the shared Gateway (`prod.fn.site`, `staging.fn.site`). Every app still serves from `/`, so no base-path settings are needed.
- **Locally, `*.localhost`** resolves to the machine in browsers and curl. One port-forward to Traefik and a hostname per instance (`agent1.localhost`) replace the port offsets.
- **Keycloak has a fixed public hostname per instance** (`KC_HOSTNAME`), so every token carries the same issuer however it was obtained. nexus-api checks the issuer against that hostname and fetches signing keys over the in-cluster address.
- **The Gateway admits routes from instance namespaces** by label; cross-namespace references use a ReferenceGrant.
- **TLS in prod** uses one wildcard certificate per domain (cert-manager, DNS challenge). Dev uses plain HTTP on `*.localhost`.

### Dev: code changes without a deploy

- **For nexus-api and Dagster code, an agent runs them as local processes** (`uvicorn`, `dagster dev`) with its own instance name, against the shared Keycloak, Postgres and Gitea in the cluster.
- **Kubernetes clients try in-cluster auth, then the kubeconfig,** so the same code runs in a pod or on the host.
- **Every address comes from env** (nexus-api, Keycloak, Gitea), defaulting to the in-cluster service names.
- **One command seeds an instance:** its database, Keycloak users and Gitea org. A mise task starts its processes.
- **Chart and operator changes still need a full deploy,** into the worktree's own namespace.

## Consequences

- **Agents and developers work in parallel** on one cluster, each with an instance of their own, at about 300 MB for local processes or 2-3 GB for a namespace with its own Keycloak and Postgres.
- **The cluster-owner check covers only shared pieces:** CRDs, the operator and Traefik. Everything else needs no owner.
- **Sites can run several nodes in one cluster,** and run a new version beside the old one before switching the hostname over.
- **The instance name touches many places.** Every hard-coded name in nexus-api, Dagster, fncli and the chart has to read it. This is the bulk of the work.
- **CRDs and the operator are cluster-wide.** All instances in a cluster run the same operator version, and a CRD change still needs one owner in dev.
- **Each instance needs its own git repositories,** or two Dagsters ingest the same pull request.
- **Two routes claiming one hostname fail quietly:** the older route wins. The chart rejects a hostname that another instance already uses where it can, and the deploy script checks it in dev.

## Alternatives considered

- **A kind cluster per worktree.** Full isolation and no shared CRDs, but 4-6 GB each; two or three is the limit under WSL. It does nothing for sites.
- **Port offsets per instance.** No Traefik changes, but fragile port-forwards in dev and no use in prod.
- **Routing by path** (`/prod/...`). One hostname, but every app needs a base path (FastAPI `root_path`, Dagster `--path-prefix`, `KC_HTTP_RELATIVE_PATH`, nexus-ui assets) and login redirects break easily.
- **Sharing Keycloak and Postgres by default.** Cheaper, but one instance's users, roles or migrations can affect another. Kept as a site option.

## Open questions

- **How names are derived:** a prefix (`<instance>-<name>`) or a suffix, and how long they can get within Kubernetes' 63-character limit.
- **Whether the chart supports two releases in one cluster today,** or needs cluster-scoped objects moved out first.
- **Where the shared pieces are installed:** a small separate chart for Traefik, the CRDs and the operator, or a flag on the main chart.
- **How the deploy-owner check changes** once only shared pieces need an owner.
