# Helm chart review: k8s/federated-node

Read-only review. Nothing was rendered (no helm run), so every item is from reading the files.
Paths are relative to `k8s/federated-node/`.

## 1. values.yaml vs values.schema.json

- `values.schema.json:1-6` - the root object and every nested object lack `additionalProperties: false`
  (none of the 46 object nodes set it). A typo such as `nexus.api.replcas` or `taskNetworkPolicy.enabeld`
  passes validation. Fix: set `additionalProperties: false` on the chart's own blocks (not on
  `dagster`, `traefik`, `cert-manager`, `global`).
- `values.yaml:483-518` - the whole `gitea:` block has no schema entry (enabled, image, service,
  persistence, db, oauth2). Fix: add a `gitea` object to the schema.
- `values.yaml:89-91` (`alpine`), `:8` (`dagsterHome`), `:97-104` (`global.namespaces.*`),
  `:21-26` (`nexus.api.db.*`), `:14` (`nexus.api.image`), `:20` (`nexus.api.url`), `:32` (`nexus.ui.image`),
  `:35-41` (`nexus.ui.resources`), `:49-52` (`keycloak.db.user`, `keycloak.db.secret`),
  `:227-233` (`federatedNode.resources`), `:335-336` (`fnDagster.results.maxZipBytes`),
  `:362-367` (leaves under `fnDagster.codeServer.resources`), `:208-217` (leaves under `taskCompute`) -
  defined in values, absent from the schema, so a wrong type is not caught. Fix: add them.
- `values.schema.json:14-17` - `definitions.capacity` says "Other possible units are Mi, Ti, Ki" but the
  pattern `^\d+(M|G|K)i{0,1}$` rejects `Ti`. Fix: `^\d+(K|M|G|T)i?$`.
- `values.schema.json:913-915` vs `values.yaml:262` - `nodeId` has `minLength: 1` and the default is `""`,
  so the default values fail the schema; `nodeId` is not in the root `required` list (`:4-6` has only `db`),
  so removing the key entirely passes. Fix: add `nodeId` to root `required` and drop the `""` default
  (or keep it and say so in the comment).
- `values.schema.json:277` - `db.host` is required with no default in `values.yaml:116-145` (only mentioned
  in comments). Intended, but `values.yaml` never shows the key. Fix: add a commented `# host:` under `db:`.
- In schema, not in values.yaml (not even commented): `keycloak.initializer.image/tag`,
  `storage.azure.resourceGroup`, `storage.azure.skuName`, `global.postgresqlSecretName`,
  `traefik.gatewayClass.ingressClassResource.name`. Fix: add commented entries to values.yaml, or remove
  dead ones from the schema (`ingressClassResource` is read by no template).

## 2. Read but not defined / defined but not read

- `templates/db-secrets.yaml:69-70` - reads `.Values.gitea.admin.secret.name` / `.key` with no guard and no
  default; `values.yaml:483-518` has no `gitea.admin`. With `gitea.enabled: true` and default values this is a
  nil-pointer render error. Same unguarded chain in `templates/gitea-init-job.yaml:67,71-72,74`
  (the `| default` there does not help, the chain fails first). Fix: add
  `gitea.admin: {user, email, secret: {name: gitea-admin, key: password}}` to values.yaml and the schema.
- `templates/db-secrets.yaml:63,71` - reads `$pw.gitea` and `$pw.giteaAdmin` (from `db.passwords`);
  `values.yaml:146-149` and the schema list only superuser/nexus/keycloak/dagster. Fix: document both.
- `templates/keycloak-realm-controller.yaml:34`, `templates/keycloak-rotation-cronjob.yaml:63` - read
  `keycloak.initializer.image/tag`; not in `values.yaml:43-87` (only in the schema and the dev example).
  Fix: add to values.yaml.
- `templates/gitea-pvc.yaml:15` reads `storage.local.gitea`; `storage.local.artifacts` is also read by a template;
  `values.yaml:248-252` documents only `path` and `dbpath`, and the schema has only `dbpath`.
  `storage.local.path` in the comment is read by no template. Fix: update the comment block and schema.
- `templates/dagster-user-roles.yaml:14` - reads `dagster.serviceAccount.name`, not shown in values.yaml
  (subchart value, guarded, so harmless). Fix: one comment line under `dagster:`.
- Defined but never read: none found among the chart's own keys.

## 3. Template bugs

- `templates/gitea-deployment.yaml:47,105` and `templates/gitea-init-job.yaml` (wait-for-gitea wget) -
  port `4000` is hard-coded while the Service uses `gitea.service.http.port` (`templates/gitea-service.yaml:14`).
  Changing the value breaks ROOT_URL and the init job's wait. Fix: use the value in all three places.
- `templates/gitea-deployment.yaml:23,71` - image tag falls back to `.Chart.AppVersion` (2.0.0), which is the
  chart's version, not a Gitea tag. Fix: drop the fallback (values.yaml always sets a tag).
- `templates/gitea-deployment.yaml:52,84` - builds the DB host from `.Values.db.host | default ...` instead of
  the `dbHost` helper used for the wait container on line 21. Fix: use `include "dbHost"`.
- `templates/gitea-pvc.yaml:2,56` - with `create_db_deployment: false` the PVC falls back to storage class
  `local-path`, which only exists on k3s/kind-like clusters. Fix: leave `storageClassName` unset when the value
  is empty, and default the value to empty.
- `templates/middleware.yaml:8` - `helm.sh/hook-weight: "-1"` with no `helm.sh/hook`, so it does nothing.
  Fix: remove it.
- `templates/keycloak-statefulset.yaml:10` - `replicas | default 2` while `values.yaml:45` says 1; `replicas: 0`
  (scale down) renders 2. Same pattern in `templates/dagster-code-server.yaml:64` (`| default 1`).
  Fix: drop the defaults, values.yaml always sets them.
- `templates/db-service.yaml:10` + `templates/db-deployment.yaml:19` - Service `targetPort` is `db.port`, but the
  in-cluster Postgres always listens on 5432 (no `PGPORT`, no containerPort). Any `db.port` other than 5432
  with `create_db_deployment: true` breaks the Service. Fix: `targetPort: 5432`.
- `templates/keycloak-namespace.yaml:9-10`, `templates/certificates-namespace.yaml:10-11` - namespaces are
  `pre-install` hooks with no delete policy: Helm never removes them on uninstall and they are not created on
  an upgrade that changes `global.namespaces.keycloak`. `keycloak-service.yaml:12-14`,
  `keycloak-headless.yaml:12-14`, `keycloak-start-configmap.yaml:9-11` are hooks with `resource-policy: keep`
  and no `hook-delete-policy`; this relies on Helm's default `before-hook-creation`. Fix: state the delete
  policy explicitly and note the leftover namespaces in the teardown docs.
- `templates/db-pv.yaml:13-38` and `templates/gitea-pvc.yaml:13-38` - if `create_db_deployment: true` and no
  `storage.local/azure/aws/nfs` is set, the PV renders with no volume source (invalid object at apply time, no
  render-time message). Fix: a `fail` in `requirements-check.yaml`.
- Duplicate top-level keys: none in `values.yaml` or `dev.example.values.yml` (checked both by eye and with a
  YAML load of values.yaml; `tests/values/*.yaml` not checked).
- Deployment/Service selectors and ports for nexus-api, nexus-ui, postgres, gitea, keycloak match.

## 4. Operational gaps

- `templates/_helpers.tpl:123-125` - `rollMe` is `randAlphaNum 5`, used at
  `templates/nexus-api-deployment.yaml:18` and on the three HTTPRoutes. nexus-api restarts on every
  `helm upgrade` even with no change, and every `helm diff` / GitOps sync shows drift. Fix: replace with
  `checksum/config` of `nexus-api-configmap.yaml` and `keycloak-configmap.yaml` (as the Keycloak StatefulSet
  already does at `keycloak-statefulset.yaml:18`); drop it from the HTTPRoutes.
- `templates/db-deployment.yaml:8-21` - in-cluster Postgres is a Deployment with the default RollingUpdate
  strategy and no `replicas`: on any pod-template change the new pod starts on the same data directory while
  the old one still runs. Fix: `strategy: {type: Recreate}` (or a StatefulSet).
- `templates/db-deployment.yaml:44-54` - liveness `failureThreshold: 1`, `periodSeconds: 5`: one slow
  `pg_isready` kills Postgres. No resources. Fix: threshold 3+, add requests/limits.
- `templates/db-pv.yaml:11,51` - PV capacity is a literal `1Gi` and the PVC a literal `100Mi`;
  `storage.capacity` is ignored for the database. Access mode is ReadWriteMany for a single Postgres.
  Fix: use `storage.capacity` (or a `db` size value) and ReadWriteOnce.
- `templates/keycloak-statefulset.yaml:26-62` - no `resources`, no liveness or startup probe (readiness only,
  line 39). The checksum on line 18 covers `keycloak-configmap.yaml` but not `keycloak-start-configmap.yaml`
  (mounted at lines 56-61), so a quarkus.properties change does not restart Keycloak. Fix: add resources, a
  liveness probe on `/health/live`, and a second checksum.
- `templates/nexus-ui-deployment.yaml:15-17` - no checksum/rollme annotation; fine today (env only), noted.
- `templates/nexus-api-deployment.yaml:30-49` - `db-migrations` init container has no resources.
  `templates/keycloak-realm-controller.yaml`, `templates/keycloak-rotation-cronjob.yaml`,
  `templates/db-init-jobs.yaml`, `templates/gitea-init-job.yaml` - no `resources:` on any container
  (grep finds none). Fix: add small requests/limits.
- `templates/gitea-deployment.yaml:128-134` - resources are hard-coded, not a value. `:11` allows
  `replicaCount > 1` on a ReadWriteOnce PVC with RollingUpdate. `:40` writes `app.ini` (with the DB password)
  only when missing, so a rotated `gitea-db` password never reaches an existing volume. Fix: Recreate strategy,
  resources from values, pass the password through `GITEA__database__PASSWD`.
- `templates/nexus-api-deployment.yaml:9-11` - `autoscaling.enabled: true` only removes `replicas`; no HPA
  template exists in the chart. Fix: remove the value or add the HPA.

## 5. dev.example.values.yml vs values.yaml

- `dev.example.values.yml:82-84` - sets `keycloak.initializer.image/tag`, a key values.yaml does not define
  (see section 2). Works, but undiscoverable.
- `dev.example.values.yml:50-52` - sets `storage.local.artifacts`, not documented in `values.yaml:248-252`
  and not in the schema; values.yaml documents `storage.local.path`, which the example does not set and no
  template reads.
- `dev.example.values.yml` has no `gitea:` block although AGENTS.md lists a Gitea port-forward (4000) and
  Dagster is enabled at `:119`. Enabling Gitea from the example hits the `gitea.admin` nil error above.
  Fix: add a commented `gitea: {enabled: true, admin: ...}` block.
- `dev.example.values.yml:124` comment says "never set fnDagster.db" - consistent with
  `requirements-check.yaml:31`. No stale keys found in the example.
- Not compared: the gitignored `dev.values.yaml` (141 lines vs 135 in the example).

## 6. Templates with no helm-unittest suite

Found by searching `tests/*.yaml` and `tests/failures/*.yaml` for each template file name (a suite that
renders everything without naming the file would not count):

- `nexus-ui-deployment.yaml`, `nexus-ui-service.yaml`, `nexus-ui-http-route.yaml`
- `gitea-pvc.yaml`, `gitea-service.yaml` (and no suite renders `gitea.enabled: true` with default values, which
  is why the `gitea.admin` error is not caught)
- `db-pv.yaml`, `db-service.yaml`
- `gateway.yaml`, `middleware.yaml`
- `keycloak-service.yaml`, `keycloak-headless.yaml`, `keycloak-namespace.yaml`, `keycloak-roles.yaml`,
  `keycloak-realm-configmap.yaml`, `keycloak-start-configmap.yaml`
- `task-namespace.yaml`, `certificates-namespace.yaml`, `tests/test-connection.yaml`

## Not covered

- `templates/_db.tpl`, `_functions.tpl`, most of `_helpers.tpl`, `db-init-jobs.yaml` body,
  `requirements-check.yaml` logic, `keycloak-secrets.yaml`, `keycloak-rotation-*`, `keycloak-realm-controller.yaml`
  body, `dagster-code-server.yaml` (only lines 55-75), `dagster-artifacts-pv.yaml`, `dagster-env-config.yaml`,
  `copy-secrets.yaml`, network policy templates, `certificates/issuer.yaml` and `roles.yaml`, `NOTES.txt`,
  `templates/tests/*`.
- `dagster.enabled` conditionals were only grepped, not traced end to end (e.g. whether `dagster-keycloak-creds`
  and `dagster-env-config` exist for every consumer).
- Schema type check covered only keys present in both files; subchart blocks (`dagster`, `traefik`,
  `cert-manager`) were not checked against the subchart schemas.
- `tests/values/*.yaml` duplicate-key scan, and the content of the existing test suites.
- Nothing was rendered, so the `gitea.admin` nil error and the empty-PV case are from reading, not from a run.
