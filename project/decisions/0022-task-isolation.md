# 0022. Task isolation: storage, secrets, namespace and network

Status: accepted, partly built. The tasks namespace, the quarantine namespace and a task pod without a Kubernetes token are in the chart. Per-run artifact folders, per-task Secrets, narrower access rules and the NetworkPolicy are decided and not built. They are tracked in #536, to be done before the first beta deployment.

## Context

A task runs a partner-supplied image next to the node's data and secrets. It is given a dataset's credentials, a volume that other runs also write to and, by default in Kubernetes, a pod network that reaches the whole cluster. Four limits keep a task to what it was given: its storage, its secrets, its namespace and its network. Each part below says what is built on this branch and what is decided but not built.

## Decision

### 1. Storage: a task sees only its own run's folder

Each run has a folder on the artifacts volume, `<mount>/<run id>`. A task pod mounts only that folder. The delivery run mounts only that run's folder, read-only. The volume does not allow symbolic links, and delivery skips links when it zips.

**Built today**
- The run pod creates `<mount>/<run id>` and the task is told the path in `ARTIFACT_PATH` (`dagster/app/definitions/pipes.py`).
- The volume is ReadWriteMany. `dagster-artifacts-pv.yaml` emits a PersistentVolume and claim in the node's namespace (run pods) and another in the tasks namespace (task pods) over the same storage, because a claim cannot cross namespaces.
- Delivery refuses a zip over `fnDagster.results.maxZipBytes`.

**To build**
- A task pod mounts the whole volume, read-write, so it can read and overwrite other runs' folders. It should mount its own folder only.
- Every Dagster run gets the whole volume from the `runLauncher` volume mount in `values.yaml`, and dagster-k8s adds a run tag's mounts to the launcher's rather than replacing them. A per-run read-only delivery mount isolates nothing until the root mount is removed from the launcher.
- The launcher hardcodes `artifacts-pvc` and `/mnt/dagster/artifacts`, while task pods use `fnDagster.artifactsPvcName` and `fnDagster.artifactMountPath`. They become one setting, or delivery reads an empty folder if one changes.
- One storage backend's default mount options enable symbolic links (`mfsymlinks` in `dagsterArtifactsMountOptions`). They are removed, and `nosymfollow` is added where the backend honours it. `zip_dir` in `delivery/git_push.py` and the `is_dir` check in `delivery/results.py` do not skip links; delivery skips them and checks that the output path stays inside the clone.
- Artifact folders are never removed. They are removed after a successful delivery and kept until then, because a delivery retry needs them.

### 2. Secrets: a task gets one dataset's credentials and nothing else

**Built today**
- A Secret's value lives only in the store: a Kubernetes Secret named by the row's `key`, in the row's `namespace`. For the `K8S` provider that is the node's namespace, for dataset credentials and git tokens alike ([0007](0007-secrets-and-secret-providers.md)).
- Disabling a Secret moves its value to the quarantine namespace (`global.namespaces.quarantine`, default `fn-quarantine`). Only the backend's service account has a Role there, so Dagster cannot read a disabled Secret ([revoke-and-enabled.md](../../docs/architecture/revoke-and-enabled.md#secrets)).
- A task pod can read Secrets from no namespace. Its spec sets `automountServiceAccountToken: false` and names no service account, and the tasks namespace's default service account has no Role.
- A task is given the dataset's connection string (host, port, database, user and password) as `CONNECTION_STRING`, plus `ARTIFACT_PATH`, the schema names and the environment of its spec. The pipes op reads the credentials in the run pod, under the Dagster service account's namespaced `get` on Secrets. A task is not given git tokens, Keycloak credentials or a reference to any Secret. Registry pull secrets sit in the tasks namespace and only the kubelet uses them.

**To build**
- Project secrets move to a namespace of their own, not the node's namespace.
- Per task, Dagster creates a short-lived Secret named for the task in the tasks namespace, holding only that dataset's credentials. The pod reads it with `secretKeyRef` (`CONNECTION_STRING` uses `$(DB_PASSWORD)`, so task images do not change) and the Secret is deleted when the task completes. Today the password is a literal value in the pod spec, visible to anyone who can `get pods` in the tasks namespace.
- Dagster reads the secrets namespace and creates and deletes Secrets in the tasks namespace only. Today its Role can `get` every Secret in the node's namespace, including the database and Keycloak ones (`dagster-user-roles.yaml`, no restriction by Secret name).
- The backend and the credential rotation job use ClusterRoles on Secrets in every namespace (`backend-roles.yaml`, `keycloak-rotation-rbac.yaml`). They become namespaced Roles. Until then quarantine keeps Dagster out only because Dagster's Role is namespaced; the backend's ClusterRole reaches it too.

### 3. Namespace: all tasks run in one tasks namespace

Every task run launched through Dagster pipes runs in one dedicated tasks namespace, separate from the node's namespace. For now it is a single namespace for all tasks.

**Built today**
- The chart creates the namespace (`task-namespace.yaml`). Its name is `global.namespaces.tasks`, default `tasks`; neither `values.yaml` nor the dev values override it. The chart passes it to Dagster as `DAGSTER_TASK_NAMESPACE` and to the backend as `TASK_NAMESPACE` (registry pull secrets), and pipes runs the pod there.
- The namespace holds one Role, `<release>-dagster-task-pod-role`: create, get, list, watch and delete on pods, get and list on `pods/log`, get, list and watch on events. It is bound to the code server's and the run launcher's service accounts. Pipes passes its context in the environment and reads messages from pod logs through the Kubernetes API, so Dagster needs no network path to the pod.
- Task pods run as the namespace's default service account with no token and no Role.

**What the namespace and its pods must not be able to do**
- Reach the node's namespace, its Secrets or its Kubernetes objects.
- Call the Kubernetes API beyond what pipes needs: the pod and log verbs above, used by Dagster's service accounts, never by the pod.
- Read Secrets in any other namespace.

**To build**
- `pipes.py` falls back to the node's namespace when `DAGSTER_TASK_NAMESPACE` is unset. The chart always sets it, so the fallback only hides a missing setting. A missing setting should fail.
- The per-task Secret needs create and delete on Secrets in the Role above, and nothing wider.
- Pod settings, also in #536: the task spec's CPU and memory requests and limits (dropped today), a container security context (no privilege escalation, capabilities dropped, non-root, seccomp), `activeDeadlineSeconds`, and a wait timeout so a hung task does not stay RUNNING for about 24 hours.

### 4. Network: a task pod reaches the database and nothing else

A task pod has no network access to the internet and, ideally, nothing beyond the database and any other GlobalResource it needs. Ingress to task pods is denied. The mechanism is a Kubernetes NetworkPolicy in the tasks namespace: deny all egress and ingress by default, then allow DNS and egress to the dataset database only. The Dagster sensors and ops run in the node's namespace and keep their egress to Gitea and GitHub, because they ingest pull requests and push results; the policy applies to the tasks namespace and not to them.

The policy breaks nothing a task needs. Results leave through the artifacts volume, not the network. Image pulls are made by the kubelet. Dagster reaches the pod through the Kubernetes API, as above.

**Built today:** nothing. The chart has no NetworkPolicy and the dev cluster has none. Kubernetes then allows all traffic to and from a task pod, so it can reach the backend, Keycloak, Postgres, Gitea, the Kubernetes API and the cloud metadata endpoint.

**To build:** the policy above, as a chart template for the tasks namespace, with a test that shows a refused connection.

## What each part protects against

- Storage: one task reading, overwriting or deleting another run's output, and delivery following a link out of the run's folder.
- Secrets: a task or Dagster reading credentials it was not given, a password sitting in a pod spec, and a disabled Secret still being read.
- Namespace: a task reaching the node's workloads and Secrets, and a Role in one place covering both.
- Network: dataset content or credentials leaving over the internet, and a task calling node services or the Kubernetes API.

None of the four limits what a task does with the dataset its credentials open. Output reaches people only through the reviewed results pull request ([0013](0013-results-delivered-as-branch-and-pull-request.md)).

## Consequences

- Until #536 is built, only the missing token, the tasks namespace and quarantine hold. A task can still read other runs' folders and reach the cluster network.
- One tasks namespace means all tasks share its Role, its policy and its Secrets. Without a token a task cannot read them, but a project cannot be given a different policy, quota or Role from another.
- A NetworkPolicy does nothing unless the cluster's CNI enforces it. The dev cluster runs kindnet (`kindest/kindnetd`), whose ClusterRole lists and watches `networkpolicies`, so it appears to process them; no test in the repo exercises that. Production needs a CNI that enforces NetworkPolicy, and the deployment guide does not yet say so.
- A policy matches pods, namespaces and address ranges, never DNS names. A dataset is created at runtime with any host and port, so "egress to the dataset database" needs one of the options under Open questions.
- Deleting the per-task Secret on completion makes cleanup part of the task's lifecycle.

## Alternatives considered

- **A namespace per project or per task:** separates Secrets, Roles and policy by project or task. Each namespace needs its own PersistentVolume and claim over the artifacts volume, its own Role bindings and policy, and creating and removing as projects or tasks come and go. A later step if one namespace proves too wide.
- **Tasks in the node's namespace with NetworkPolicy only:** no namespace boundary. The node's Secrets, database credentials and Roles sit where tasks run, and one missing or wrong policy exposes all of them.

## Open questions

- Whether to scope further than one namespace, per project or per task.
- How the dataset database enters the policy: a static policy for the in-cluster dataset database (pod selector `app: dataset-postgres` in the node's namespace); a configured list of address ranges for external databases; or a NetworkPolicy created per task beside the pod, which needs create and delete on `networkpolicies` in Dagster's tasks-namespace Role. None is chosen.
- Which CNI each production target uses, and a dev test that a denied connection is refused.
- Whether a task ever needs another GlobalResource. None does today, so the first policy allows the dataset database only.
- The name of the secrets namespace, and how existing Secrets whose row names the node's namespace move to it.
- What removes a per-task Secret when the run pod dies before it cleans up.
- Whether the tasks namespace carries a Pod Security Standards label.

## Related

- [0006](0006-global-resources-and-project-resources.md) Global resources and project resources
- [0007](0007-secrets-and-secret-providers.md) Generic Secret model and SecretProvider; per-repository tokens
- [0008](0008-enabled-revoked-and-soft-delete.md) Enabled, revoked and soft delete
- [0009](0009-task-pinned-to-its-configuration.md) A task is pinned to its configuration
- [0013](0013-results-delivered-as-branch-and-pull-request.md) Results delivered as a pushed branch plus a results pull request
- [0014](0014-dagster-pipeline-ops-sensors-and-retries.md) The Dagster pipeline: ingest as an op, twelve sensors, one interval, retries
