# Architecture Overview

This page explains how the Federated Node (FN) 2.x is put together: what each component does, how a task gets from a pull request to a result, which pods land in which namespace, and the decisions you need to make yourself before going to production.

If you just want to install it, start at [Prerequisites](./Prerequisites) and [Deploy: Core](./Deploy-Core). Come back here when you need to explain the system to a security reviewer, or when you are deciding where to put the database and how to lock down the network.


## The idea in one paragraph

The FN inverts the usual data sharing model. Instead of copying patient data out to a researcher, the researcher sends their analysis code to you, packaged as a Docker image, and asks for it with a pull request. The FN runs that image inside your cluster, against your data, in an isolated pod that lives only as long as the task. The only thing that leaves is the result files, and only as a pull request that a person at your institution merges. Everything else stays behind your firewall.


## The components

Everything below is deployed by a single Helm chart. Some parts are subcharts you can turn on or off.

| Component | Namespace | What it does |
|---|---|---|
| **nexus-api** | release namespace | The FN API (FastAPI, port 5000). It is the record and the rules: projects, datasets, repositories, tasks and results live in its database, and it decides whether a task may run. It also mints short-lived git tokens for the repositories. |
| **Dagster** (webserver, daemon, code server) | release namespace | Runs the sensors that poll git, and the jobs that start task pods and deliver results. It asks nexus-api what to do and does it. The Dagster UI has no login. |
| **Keycloak** | `keycloak` | Logins and the admin role. Reached at `https://<host>/keycloak`. |
| **PostgreSQL** | release namespace | Only if you let the chart run one (development). In production you bring your own server. |
| **Traefik** | release namespace | Optional subchart. Reverse proxy and ingress for nexus-api and Keycloak, using Gateway API routes. |
| **cert-manager** | `fn-certmanager` | Optional subchart. Renews TLS certificates. |
| **Gitea** | release namespace | Optional (`gitea.enabled`). A git host for development only. |
| **Task pods** | `tasks` | One per task, created by Dagster. They run the researcher's image. |
| **Secrets** | `fn-secrets` | Holds project secrets: dataset logins and git tokens. Only nexus-api and Dagster can read it. The release namespace holds none. |
| **Quarantine** | `fn-quarantine` | Holds the value of a secret that has been switched off. |

Task pods get their own namespace on purpose: it holds nothing but task pods, so the network rules and permissions there can be strict.


## How a task runs

1. **Ingest.** A Dagster sensor polls each trigger repository for merged pull requests. nexus-api stores each pull request once, however many projects watch the repository.
2. **Evaluate.** For each project that watches that repository and branch, a pull request that **adds one `.json` file** under the project's watch directory becomes a task. A pull request that adds no such file is ignored. One that adds several, or whose spec is not valid, is marked `REJECTED` with the reason.
3. **Launch.** Another sensor picks up each pending task. nexus-api checks that everything the task needs is still allowed, then Dagster starts the pod with the dataset's credentials.
4. **Run.** The pod runs the image. It writes its output to a folder that is all it can see of the shared results volume.
5. **Deliver.** When the run succeeds, Dagster zips the output, pushes it with a copy of the spec and a `run.json` to a branch of the results repository, and opens a pull request.
6. **Review.** Someone at the institution reads the pull request. Merging it records the result as merged.

Every Dagster sensor starts **stopped**, and nothing runs until an admin starts them ([Operations](./Operations#start-the-sensors)). A failed task delivers nothing.

The detailed flow chart is in the repo: [flows.md](https://github.com/Aridhia-Open-Source/PHEMS_federated_node/blob/beta/docs/architecture/flows.md). The decision records are indexed in the repo's [docs/README.md](https://github.com/Aridhia-Open-Source/PHEMS_federated_node/blob/beta/docs/README.md).


## Global resources and projects

An admin creates the things a node needs once, and then assigns them to projects.

| Global (made once) | What it is |
|---|---|
| **Secret** | A credential: a git App key, a Gitea OAuth app, or a dataset's database login. Stored in Kubernetes. The API never returns the values. |
| **Git provider** | A git host: GitHub or Gitea, with its web and API addresses. |
| **Trigger repository** | The repository whose merged pull requests become tasks. |
| **Results repository** | The repository results are pushed to. |
| **Dataset** | A database the tasks read from and may write results to. |

A **project** is the unit of work. It is assigned one or more datasets and trigger repositories, and one results repository, and each assignment holds what is per project: the directory to watch, the branch, where results go. Two projects can watch the same repository, and each gets its own task for a matching pull request.

Every resource has an **enabled** flag, which an admin of the resource can flip, and an admin-only **revoked** flag that takes effect at once. [Operations](./Operations#switch-things-on-and-off) says what each switch does.


## How the pieces connect

A researcher never talks to the FN to start a task: they talk to git. The FN's own calls go out, not in.

- **Dagster to git.** The sensors and run pods call your git host (`api.github.com` for GitHub) to read merged pull requests and to push and open results.
- **Dagster to nexus-api.** Every decision goes through nexus-api. Dagster logs in as a system user.
- **nexus-api to Keycloak.** nexus-api checks logins and tokens against Keycloak.
- **Task pods to the dataset.** A task pod can reach DNS and the dataset database, and nothing else. It does not talk to nexus-api, Dagster, git or the Kubernetes API.

Admins and researchers who use the API reach it over HTTPS through Traefik. The Dagster UI is never exposed: reach it with a port-forward.


## Task isolation

A task runs an image that you did not write, next to your data. Four limits keep it to what it was given. The design is [ADR 0022](https://github.com/Aridhia-Open-Source/PHEMS_federated_node/blob/beta/project/decisions/0022-task-isolation.md).

| Limit | What it means |
|---|---|
| **Storage** | The pod mounts only its own run's folder on the shared volume, not the volume. Delivery skips symbolic links. |
| **Secrets** | The pod gets one dataset's login in a Secret made for that task, and deleted when it ends. It has no Kubernetes token, and no git credentials. |
| **Namespace** | All tasks run in the `tasks` namespace, apart from nexus-api, Dagster and Keycloak. |
| **Network** | A NetworkPolicy denies all traffic in and out of the namespace, except DNS and the dataset databases you list in `taskNetworkPolicy.datasetEgress`. |

Two things to know:

- The network rule only works if your cluster's network plugin enforces NetworkPolicy (Calico, Cilium, or your cloud's add-on). On one that ignores it, the rule does nothing.
- `datasetEgress` is empty by default. A task whose dataset database is not listed there will time out when it connects. [Deploy: Core](./Deploy-Core#let-tasks-reach-their-dataset) shows the value.

None of this limits what a task does with the dataset it was given. What leaves the node is the zip in the results pull request, and a person reads it first.


## Access

Logins are Keycloak users, with the realm roles `Users`, `Administrator`, `Super Administrator` and `System` ([Using the API](./Using-The-API#users)). Creating the global resources, and revoking things, needs an admin role. In the beta, access control for a normal login is coarse: there are no permissions per dataset for each user. Researchers do not need a login for the common case: they work in git.


## Decisions you need to make

**Where does the database live?** In production, point the chart at your own PostgreSQL server. The FN needs its own databases on it, not your research data. The chart can create them if you give it an admin login, or you can create the roles yourself.

**Which git host?** GitHub, with a GitHub App you create, or a Gitea you run. Each repository's secret holds app credentials (a GitHub App key, or a Gitea OAuth app), and nexus-api mints a short-lived token from them when Dagster asks. For GitHub the token lasts an hour and covers one repository.

**Where do results go?** The results repository is where result zips are committed, and the default limit is 10 MiB per zip. The zip is pushed to a branch of that repository before anyone has reviewed it, so decide who can read the repository, and remember that anything merged is in git history for good.

**Who reviews?** The merge button on the results pull request is the control. Decide who at the institution has it.

**What is the network around the node?** Outbound HTTPS to `ghcr.io` (images), to your git host, and to wherever the analytics images live. No inbound access is needed for tasks.

**Shared storage.** Task results and Dagster's artifacts need `ReadWriteMany` storage: Azure Files, AWS EFS, NFS, or a local path on a single node. The choice is made at install time and is awkward to change later, because it means recreating the volumes. The per-run folders are not removed after delivery, so size it for every run you keep. [Deploy: Core](./Deploy-Core#shared-storage) has the details.

**Is the database connection encrypted?** Set `db.enforceSSL: true`, with `dagster.postgresql.postgresqlParams.sslmode: require`. It is off by default. Turn it on unless the database is on the same host. Managed services such as Azure require it.

**What do you back up?** nexus-api's database and Keycloak's, which are separate databases on the same server. Restoring only nexus-api's gives you a node that knows its datasets and projects but has lost every login.

**Which account does a dataset use?** A dedicated, read-only database account scoped to exactly the schema you intend to expose, not an application or admin account. Task pods connect to the research database directly, so if it is outside the cluster that path must be open: databases in the private ranges are allowed by default, and any other needs a `taskNetworkPolicy.datasetEgress` rule ([Datasets](./Datasets)).

**Who can reach the node?** In production, one public or VPN-reachable HTTPS endpoint fronted by Traefik. nexus-api and the Keycloak login are both behind it. Outbound, the cluster needs `ghcr.io`, your git host and your analytics image registries. If it has no internet egress, mirror those images into an internal registry. The results pull request is a deliberate data egress path, and a person reviews it.

**How are secrets protected?** The Keycloak admin password is in the `kc-secrets` secret in the `keycloak` namespace, and anyone holding it can act as any user. Store it somewhere sensible, and rotate it (`keycloak.credentialGeneration`, or `keycloak.credentialRotation.enabled`). Kubernetes secrets are base64 encoded, not encrypted, unless you have enabled encryption at rest on etcd or use an external secrets provider. Check which is true for your cluster.

**How will you upgrade?** nexus-api applies its database migrations itself, in an init container, on every deploy. A Helm rollback does not roll the schema back, so take a database snapshot before upgrading. You install the Gateway API and Traefik CRDs, so you also upgrade them ([Prerequisites](./Prerequisites#install-the-gateway-api-and-traefik-crds)).


## Where next

- [Prerequisites](./Prerequisites) and [Deploy: Core](./Deploy-Core) to install it.
- [Analytics container development](./Analytics-Container-Development) for what the pods are given.
