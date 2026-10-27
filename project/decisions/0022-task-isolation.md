# 0022. Task isolation: storage, secrets, namespace and network

Status: accepted, built. The tasks namespace, the quarantine namespace, the secrets namespace, a task pod without a Kubernetes token, per-task Secrets, narrower access rules, per-run artifact folders, the task pod's limits and the task NetworkPolicy are in the chart (#536).

## Context

A task runs a partner-supplied image next to the node's data and secrets. It is given a dataset's credentials, a volume that other runs also write to and, by default in Kubernetes, a pod network that reaches the whole cluster. Four limits keep a task to what it was given: its storage, its secrets, its namespace and its network. Each part below says what is built on this branch and what is decided but not built.

## Decision

### 1. Storage: a task sees only its own run's folder

Each run has a folder on the artifacts volume, `<mount>/<run id>`. A task pod mounts only that folder. The delivery run mounts only that run's folder, read-only. The volume does not allow symbolic links, and delivery skips links when it zips.

**Built today**
- The run pod creates `<mount>/<run id>` and the task is told the path in `ARTIFACT_PATH` (`dagster/app/definitions/pipes.py`).
- The volume is ReadWriteMany. `dagster-artifacts-pv.yaml` emits a PersistentVolume and claim in the node's namespace (run pods) and another in the tasks namespace (task pods) over the same storage, because a claim cannot cross namespaces.
- Delivery refuses a zip over `fnDagster.results.maxZipBytes`.
- A task pod mounts only its own folder (`subPath: <run id>`), read-write.
- The `runLauncher` in `values.yaml` mounts no volume, because dagster-k8s adds a run tag's mounts to the launcher's rather than replacing them. The sensors tag the runs that need the artifacts volume (`artifacts_volume_tags` in `sensors/base.py`): a task's run pod gets the whole volume read-write, to create the run's folder, and a delivery run gets only its task run's folder, read-only. Both read the claim and mount path from `fnDagster.artifactsPvcName` and `artifactMountPath`, as the task pod does.
- `mfsymlinks` is not set in `dagsterArtifactsMountOptions`. `zip_dir` skips symbolic links, delivery refuses an artifacts folder that is a link, and it checks that the output path stays inside the clone.

**To build**
- `nosymfollow` on the volume, where the backend honours it. Not checked against a cluster.
- Artifact folders are never removed. They are to be removed after a successful delivery and kept until then, because a delivery retry needs them. The delivery run mounts its folder read-only, so removal needs a separate read-write step.

### 2. Secrets: a task gets one dataset's credentials and nothing else

**Built**
- A Secret's value lives only in the store: a Kubernetes Secret named by the row's `key`, in the row's `namespace`. For the `K8S` provider that is the secrets namespace (`global.namespaces.secrets`, default `fn-secrets`), for dataset credentials and git tokens alike ([0007](0007-secrets-and-secret-providers.md)). The chart creates it and passes it to the backend as `SECRETS_NAMESPACE`. The release namespace holds none of them.
- Disabling a Secret moves its value to the quarantine namespace (`global.namespaces.quarantine`, default `fn-quarantine`). Only the backend's service accounts have a Role there, so Dagster cannot read a disabled Secret ([revoke-and-enabled.md](../../docs/architecture/revoke-and-enabled.md#secrets)).
- A task pod can read Secrets from no namespace. Its spec sets `automountServiceAccountToken: false` and names no service account, and the tasks namespace's default service account has no Role.
- Per task, the pipes op reads the dataset's credentials in the run pod and creates a Secret named `task-<task_id>` in the tasks namespace, holding only its `USERNAME` and `PASSWORD`. The pod reads them with `secretKeyRef` as `DB_USERNAME` and `DB_PASSWORD`, and `CONNECTION_STRING` refers to them with `$(DB_USERNAME)` and `$(DB_PASSWORD)`, so task images do not change and the password is no longer a literal in the pod spec. The Secret is deleted when the run ends, whether the task succeeded or not. One left behind by a run that died is replaced by the next run of that task. A task is not given git tokens, Keycloak credentials or a reference to any other Secret. Registry pull secrets sit in the tasks namespace and only the kubelet uses them.
- Access rules, all namespaced Roles, none a ClusterRole:
  - Dagster's service accounts (code server and run launcher) `get` Secrets in the secrets namespace only, and `create` and `delete` them in the tasks namespace. They cannot read the release namespace's database and Keycloak Secrets.
  - The backend creates, reads, patches and deletes Secrets in the secrets, quarantine and tasks namespaces (registry pull secrets, whose names are dynamic, so no `resourceNames`). Nothing lists Secrets.
  - The credential rotation job only `patch`es `kc-secrets` and `dagster-keycloak-creds`, in the namespaces that hold them.

**To build**
- A way to remove a per-task Secret when the run pod dies before it cleans up, other than the next run of the task replacing it. PipesK8sClient gives no hook to set an owner reference on its pod.

### 3. Namespace: all tasks run in one tasks namespace

Every task run launched through Dagster pipes runs in one dedicated tasks namespace, separate from the node's namespace. For now it is a single namespace for all tasks.

**Built today**
- The chart creates the namespace (`task-namespace.yaml`). Its name is `global.namespaces.tasks`, default `tasks`; neither `values.yaml` nor the dev values override it. The chart passes it to Dagster as `DAGSTER_TASK_NAMESPACE` and to the backend as `TASK_NAMESPACE` (registry pull secrets), and pipes runs the pod there.
- The namespace holds one Role, `<release>-dagster-task-pod-role`: create, get, list, watch and delete on pods, get and list on `pods/log`, get, list and watch on events. It is bound to the code server's and the run launcher's service accounts. Pipes passes its context in the environment and reads messages from pod logs through the Kubernetes API, so Dagster needs no network path to the pod.
- Task pods run as the namespace's default service account with no token and no Role.
- Pod settings: the task spec's CPU and memory requests and limits are the container's `resources`. The container security context allows no privilege escalation, drops all capabilities, uses the runtime's seccomp profile and requires a non-root uid. The pod runs as `fnDagster.artifacts.securityContext` (uid and gid 1001 by default), so an image with no `USER` still starts.
- A hung task: the pod gets `activeDeadlineSeconds` from `fnDagster.taskPod.activeDeadlineSeconds` (6 hours), which is what ends it, because the Pipes client follows the pod's logs until the container exits. The client's wait timeout is that plus the pod's 300 s grace period, and `dagster.dagsterDaemon.runMonitoring.maxRuntimeSeconds` (7 hours) backstops a run pod that hangs. Helm cannot template it, so it has to stay above the deadline by hand.

**What the namespace and its pods must not be able to do**
- Reach the node's namespace, its Secrets or its Kubernetes objects.
- Call the Kubernetes API beyond what pipes needs: the pod and log verbs above, used by Dagster's service accounts, never by the pod.
- Read Secrets in any other namespace.

**To build**
- `pipes.py` falls back to the node's namespace when `DAGSTER_TASK_NAMESPACE` is unset. The chart always sets it, so the fallback only hides a missing setting. A missing setting should fail.
- Built: the Role above also has create and delete on Secrets, for the per-task Secret, and nothing wider.

### 4. Network: a task pod reaches the database and nothing else

A task pod has no network access to the internet and, ideally, nothing beyond the database and any other GlobalResource it needs. Ingress to task pods is denied. The mechanism is a Kubernetes NetworkPolicy in the tasks namespace: deny all egress and ingress by default, then allow DNS and egress to the dataset database only. The Dagster sensors and ops run in the node's namespace and keep their egress to Gitea and GitHub, because they ingest pull requests and push results; the policy applies to the tasks namespace and not to them.

The policy breaks nothing a task needs. Results leave through the artifacts volume, not the network. Image pulls are made by the kubelet. Dagster reaches the pod through the Kubernetes API, as above.

**Built today:** `task-network-policy.yaml` creates one NetworkPolicy in the tasks namespace. It selects every pod there (`podSelector: {}`), denies all ingress, and allows egress only to cluster DNS (UDP and TCP 53) and to the rules in `taskNetworkPolicy.datasetEgress`. Each rule is a NetworkPolicy egress rule, so a database is named by address (`ipBlock`) or by namespace and pod label. The list is empty by default: a task that needs a database then times out on connect until an operator adds it. The dev example values allow the experiments database (`db-datasets` in the `experiments` namespace, label `app: experiments-postgres`, port 5432).

The policy selects the whole namespace because task pods carry only Dagster's common labels, and a label selector that missed them would leave them open. That is only right while the namespace holds nothing but task pods, so the chart fails to render if `global.namespaces.tasks` is the release namespace or the Keycloak namespace, and a rule without `to` or without `ports` (which would allow every destination or every port) fails too. Chart tests cover what renders and what it selects.

**To build:** a dev test that a denied connection from a task pod is refused. The chart tests render the policy and do not exercise a CNI.

## What each part protects against

- Storage: one task reading, overwriting or deleting another run's output, and delivery following a link out of the run's folder.
- Secrets: a task or Dagster reading credentials it was not given, a password sitting in a pod spec, and a disabled Secret still being read.
- Namespace: a task reaching the node's workloads and Secrets, and a Role in one place covering both.
- Network: dataset content or credentials leaving over the internet, and a task calling node services or the Kubernetes API.

None of the four limits what a task does with the dataset its credentials open. Output reaches people only through the reviewed results pull request ([0013](0013-results-delivered-as-branch-and-pull-request.md)).

## Consequences

- Until #536 is built, only the missing token, the tasks namespace, quarantine and the network policy hold. A task can still read other runs' folders.
- One tasks namespace means all tasks share its Role, its policy and its Secrets. Without a token a task cannot read them, but a project cannot be given a different policy, quota or Role from another.
- A NetworkPolicy does nothing unless the cluster's CNI enforces it. The dev cluster runs kindnet (`kindest/kindnetd`), which enforces NetworkPolicy from kind v0.24 (via kube-network-policies); no test in the repo exercises that. Production needs a CNI that enforces NetworkPolicy, which the deployment guide now lists as a prerequisite.
- A policy matches pods, namespaces and address ranges, never DNS names. A dataset is created at runtime with any host and port, so an operator lists each database's address or pod in `taskNetworkPolicy.datasetEgress`; a dataset registered through the API is not reachable until they do.
- Deleting the per-task Secret on completion makes cleanup part of the task's lifecycle.

## Alternatives considered

- **A namespace per project or per task:** separates Secrets, Roles and policy by project or task. Each namespace needs its own PersistentVolume and claim over the artifacts volume, its own Role bindings and policy, and creating and removing as projects or tasks come and go. A later step if one namespace proves too wide.
- **Tasks in the node's namespace with NetworkPolicy only:** no namespace boundary. The node's Secrets, database credentials and Roles sit where tasks run, and one missing or wrong policy exposes all of them.

## Open questions

- Whether to scope further than one namespace, per project or per task.
- Whether the dataset database should enter the policy per task instead of through the configured list: a NetworkPolicy created per task beside the pod, which needs create and delete on `networkpolicies` in Dagster's tasks-namespace Role, so a new dataset needs no chart change.
- Which CNI each production target uses, and a dev test that a denied connection is refused. On the dev cluster, kindnet drops denied traffic to other pods, Services and the internet, but not traffic to node addresses (the kube API at the node's IP, the kubelet, etcd), which it never sees; each production CNI needs that checked too.
- Whether a task ever needs another GlobalResource. None does today, so the first policy allows the dataset database only.
- How existing Secrets whose row names the node's namespace move to the secrets namespace. Nothing moves them: their rows keep the old namespace and become unreadable, and a disabled one cannot be enabled, rotated or deleted until it is written again. Writing a Secret again (`PATCH /global/secrets/<label>` with all its values) stores it in the secrets namespace and updates the row.
- What removes a per-task Secret when the run pod dies before it cleans up, until that task runs again.
- Whether the tasks namespace carries a Pod Security Standards label.

## Related

- [0006](0006-global-resources-and-project-resources.md) Global resources and project resources
- [0007](0007-secrets-and-secret-providers.md) Generic Secret model and SecretProvider; per-repository tokens
- [0008](0008-enabled-revoked-and-soft-delete.md) Enabled, revoked and soft delete
- [0009](0009-task-pinned-to-its-configuration.md) A task is pinned to its configuration
- [0013](0013-results-delivered-as-branch-and-pull-request.md) Results delivered as a pushed branch plus a results pull request
- [0014](0014-dagster-pipeline-ops-sensors-and-retries.md) The Dagster pipeline: ingest as an op, twelve sensors, one interval, retries
