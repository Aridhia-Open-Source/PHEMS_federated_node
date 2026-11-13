# Kubernetes review: task pods and chart resources

Read-only review, time-boxed. "Confirmed" = read in the file at the lines given. "Inferred" = follows from those lines but not tested on a cluster.

## Findings, highest impact first

### 1. Task pods can reach nexus-api, Keycloak and nexus-ui through Traefik
- `k8s/federated-node/templates/task-network-policy.yaml:43-48` - the `privateEgress` rule has `to` but no `ports`, so every port on 10/8, 172.16/12 and 192.168/16 is open (defaults at `k8s/federated-node/values.yaml:168-171`).
- `k8s/federated-node/templates/internal-ingress-policy.yaml:16` ("Traefik itself is never selected") and `:62-68` - the node's services refuse the tasks namespace by namespace, but Traefik is in the release namespace and is not selected by any ingress policy.
- Consequence (inferred): a task pod connects to the Traefik pod or Service IP, and Traefik forwards to nexus-api / Keycloak / nexus-ui as a release-namespace source, which the ingress policies allow. The "tasks cannot reach the node's services" claim does not hold for anything routed by Traefik. A task holding dataset credentials can hit the Keycloak login and the API.
- Fix: add an ingress policy on Traefik that excludes the tasks namespace (same `NotIn` rule; external traffic arrives by address so add an `ipBlock` allow alongside), or drop pod/Service CIDRs from the task egress with `except`.

### 2. Default task egress is "any private address, any port", not default-deny
- `k8s/federated-node/templates/task-network-policy.yaml:43-48`, `k8s/federated-node/values.yaml:165-171`.
- Confirmed: allowed by default are every pod and Service IP in the cluster outside the few pods with an ingress policy, plus the whole site LAN in RFC1918.
- Consequence (inferred): reachable from a task pod are the Kubernetes API Service IP (no token, but anonymous endpoints and version are exposed), kubelets on node IPs (10250), any other workload in the cluster that has no policy of its own (Dagster daemon, run pods, kube-system, other tenants), and on-prem hosts on the hospital/site network. A task can exfiltrate dataset rows to any private-range host it can find. Cloud metadata (169.254.169.254) is not in the ranges, so it is blocked - that part is fine.
- Fix: default `privateEgress: []` and make operators list the dataset DB in `datasetEgress` (which already requires ports, `:38-40`); or require ports on `privateEgress` too.

### 3. Protection of nexus-api, nexus-ui and Keycloak is dropped when `traefik.enabled: false`; Gitea when its Service is not ClusterIP
- `k8s/federated-node/templates/internal-ingress-policy.yaml:27-32` (nexus-api, nexus-ui only added under `traefik.enabled`), `:46-48` (Keycloak), `:36-38` (Gitea).
- Consequence: with a bring-your-own ingress, task pods reach nexus-api and Keycloak pod IPs directly on any port, because of finding 2. Nothing fails or warns.
- Fix: always select these pods, and allow the external ingress by an operator-supplied `from` (namespace or CIDR) rather than removing the policy.

### 4. Dagster service accounts can `get` every project secret, which the code no longer needs
- `k8s/federated-node/templates/dagster-user-roles.yaml:15-39` - Role `secrets: get` in the secrets namespace, bound to the code server SA and the run launcher SA. The file's own comment at `:2-4` says Dagster no longer reads any and `K8sSecretProvider` is unused (`dagster/app/secrets.py:18` is the only reader).
- Consequence: run pods and the code server run as root with an automounted token (`k8s/federated-node/templates/dagster-code-server.yaml:7,79`). Anyone who gets code execution in a run pod reads dataset passwords and git tokens by name, bypassing nexus-api. This undoes the "credentials never pass through Dagster" design in `nexus/api/app/helpers/task_resources.py:5-6`.
- Fix: delete the first Role and RoleBinding (`:15-39`) and `dagster/app/secrets.py`.

### 5. `dagster-user-roles.yaml` renders with `dagster.enabled: false`
- `k8s/federated-node/templates/dagster-user-roles.yaml:1-14` - no `{{- if .Values.dagster.enabled }}` guard; every other Dagster template has one (`dagster-code-server.yaml:10`, `dagster-env-config.yaml:1`, `dagster-artifacts-pv.yaml:1`).
- Consequence: with Dagster off, two RoleBindings name service accounts that do not exist (`<release>-dagster`, the code server SA). Whoever can later create a ServiceAccount with that name in the release namespace inherits secret read in the secrets namespace and pod create/delete in the tasks namespace.
- Fix: wrap the file in the `dagster.enabled` guard.

### 6. No Pod Security Admission labels on any namespace the chart creates
- `k8s/federated-node/templates/task-namespace.yaml:1-4`, `secrets-namespace.yaml:4-7`, `quarantine-namespace.yaml:4-7`, `keycloak-namespace.yaml:2`. `git grep pod-security -- k8s/` returns nothing.
- Consequence: the task pod's hardening lives only in `dagster/app/config.py:99-104`. The Dagster SA may create any pod in the tasks namespace (`dagster-user-roles.yaml:53-55`), so a compromised run pod can launch a privileged, hostPath or hostNetwork pod there and take the node. The task pod spec already meets `restricted` (non-root, no escalation, drop ALL, RuntimeDefault seccomp), so enforcing it costs nothing.
- Fix: label the tasks namespace `pod-security.kubernetes.io/enforce: restricted`.

### 7. Run Secret with dataset credentials is only removed when the task reaches a final state through the API
- `nexus/api/app/tasks_api.py:206-208` is the only caller of `delete_run_resources` (`nexus/api/app/helpers/task_resources.py:68-76`). No owner reference, TTL or sweep on the Secret (`task_resources.py:46`).
- Consequence: if the PATCH never arrives (run pod killed, nexus-api down, Dagster run deleted), the plaintext username/password Secret stays in the tasks namespace indefinitely. Task pods cannot read it (no token), but anyone with namespace read can. Inferred: a retry with a new run id leaves the first run's Secret behind, since deletion is by `task.executor_run_id`.
- Fix: set the task pod as owner of the Secret/ConfigMap after pod creation, or have the reconcile sensor ask nexus-api to sweep Secrets whose `fn/run_id` has no live pod.

### 8. Task pod has a writable root filesystem and no ephemeral-storage limit
- `dagster/app/config.py:99-104` - no `readOnlyRootFilesystem`. `k8s/federated-node/templates/task-limit-range.yaml:13-22` - LimitRange covers cpu and memory only.
- Consequence: a task can fill the node's disk through its container layer and get other pods on that node evicted (kubelet disk pressure). CPU and memory are bounded, this is not.
- Fix: add `ephemeral-storage` default and max to the LimitRange. `readOnlyRootFilesystem` would need an `emptyDir` for `/tmp` with a `sizeLimit`.

### 9. Lower impact
- `dagster/app/definitions/pipes.py:49,88,227` reads `image_pull_secret` from op config, but `dagster/app/definitions/run_config.py:19-23,29-35` never sets it. Inferred: private-registry pull secrets are never attached to task pods, so private images fail with ImagePullBackOff until the deadline.
- `k8s/federated-node/templates/copy-secrets.yaml:9-11` copies the Azure storage account key into the tasks namespace (needed for the PVC mount). Not readable by the task pod, but it is readable and deletable by nexus-api, whose Role there has no `resourceNames` (`nexus-api-roles.yaml:17-19`).
- `dagster/app/definitions/pipes.py:189-193` chmods the run folder 0777 and `values.yaml:372-373` mounts Azure Files 0777; isolation between runs depends on `subPath` only (`pipes.py:251-252`), which is fine for task pods but every run pod sees all runs' results.
- `k8s/federated-node/templates/keycloak-roles.yaml:6-12` gives `k8s-keycloak-handler` pods and statefulsets read; not checked whether anything still uses it.

## Checked, fine
- Task pod: `automountServiceAccountToken: false` (`pipes.py:208`), `activeDeadlineSeconds` set from chart value (`pipes.py:213`, `dagster-env-config.yaml:17`), `imagePullPolicy: Always` (`pipes.py:210`), `restartPolicy: Never`.
- Container securityContext: no privilege escalation, drop ALL, RuntimeDefault seccomp, `runAsNonRoot` (`config.py:99-104`), with uid/gid 1001 from values (`values.yaml:381-383`).
- Compute is bounded twice: spec validation against `taskCompute.max` (`nexus/api/app/dtos/task_spec.py:44-59`) and the LimitRange max (`task-limit-range.yaml:20-22`).
- Dataset credentials reach the pod by `secretKeyRef`, not literal env (`pipes.py:239-245`); they never transit Dagster run config (`run_config.py:19-35`).
- Creating the run Secret is system-only and scope-checked, run id validated as a DNS label (`tasks_api.py:388-403`).
- No ClusterRole or ClusterRoleBinding in the chart's own templates; no wildcard verbs; no `pods/exec`; no `secrets: list` anywhere.
- nexus-api Roles are namespaced to secrets, quarantine and tasks only (`secrets-namespace.yaml:14-17`, `quarantine-namespace.yaml:14-17`, `nexus-api-roles.yaml:16-25`).
- Keycloak rotator is limited to `patch` on named Secrets (`keycloak-rotation-rbac.yaml:22-25`).
- Chart refuses to render if the tasks namespace is the release or Keycloak namespace (`task-network-policy.yaml:21-23`); `datasetEgress` rules without `to` or `ports` fail (`:38-40`).
- Task ingress is fully denied (`task-network-policy.yaml:31-34`, no ingress rules).
- Cloud metadata address and the public internet are outside the default egress.
- Task pod mounts only its own run folder of the artifacts volume (`pipes.py:247-254`).

## Not covered
- `nexus/api/app/helpers/kubernetes.py` and `task_config.py` beyond grep hits.
- `resources.py`, the rest of `values.yaml` run launcher block (`:432-450`) and the Dagster subchart's own RBAC (what `<release>-dagster` gets in the release namespace).
- Whether finished task pods are always deleted (relies on `PipesK8sClient`; no delete call of our own found in `dagster/app`).
- `db-secrets.yaml` (which namespaces get DB passwords), `keycloak-secrets.yaml`, `_helpers.tpl` `fn.copySecret`, `db-init-jobs.yaml`, Gitea templates, cert-manager roles beyond a skim.
- Subchart-rendered resources (Traefik, cert-manager, Dagster): no `helm template` was run.
