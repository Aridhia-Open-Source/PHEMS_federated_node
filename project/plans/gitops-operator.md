# Plan: GitOps operator, then Flux

Goal: every change to a node, version or config, goes in as a git commit that can be reviewed and reverted.
Decisions: [ADR 0032](../decisions/0032-declarative-node-config-through-an-operator.md) (operator),
[ADR 0031](../decisions/0031-gitops-delivery-with-helm-and-flux.md) (delivery).
Step numbers match `.claude/handover/gitops-operator.md`. Step 1 is done.

Rules for every step: unit tests for changed files only, helm-unittest for chart changes, no e2e, no cluster
teardown or takeover. One commit per step.

## What reading the code found

- **The admin calls the operator needs are in fncli, not in the client.** `dagster/app/backend.py` (`BackendAPI`) has
  what Dagster uses. Providers, secrets, repositories, projects and assignments are in
  `dagster/fncli/backend.py` (`FncliBackendAPI`). Both move.
- **nexus-api takes secret values, it does not adopt a Kubernetes Secret.** `POST /global/secrets` gets `values` and
  writes them to its own store as `fn-secret-<label>` (`nexus/api/app/secrets_api.py`). So the operator reads the
  source Secret and sends the values, as `fncli apply` does today.
- **Source Secrets use other key names and namespaces.** `experiments/demo/dataset.yaml` maps `username` in namespace
  `experiments` to `USERNAME`. `fromSecret: {name}` alone is not enough.
- **There is no audit record in nexus-api.** Nothing stores who changed a record.
- **Login is a Keycloak user and password.** `POST /login` is a password grant; Dagster is a user with the `System`
  role, made by `build/kc-init/common.py` (`create_system_user`). `System` skips permission checks and may mint git
  tokens. There is no client-credentials path.
- **Deleted names are free again.** Unique indexes are `WHERE deleted_at IS NULL`, so delete then re-add makes a new
  row with a new id.
- **Gitea is the chart's own templates** (`k8s/federated-node/templates/gitea-*.yaml`), not a subchart. Settings are
  `GITEA__section__KEY` env vars.
- **`fncli apply` also does Gitea work:** creates repositories and OAuth apps, then stores the OAuth credentials.
  `fncli demo`, `fncli experiment setup` and the e2e fixtures all call it.
- **Tilt's `docker_build` has no named build context.** The Dagster image needs one once the client moves.

## Part 1: operator

### Step 2. Move the client to `nexus/client/`

What and why: one client package for Dagster, fncli and the operator, so the operator does not depend on Dagster.

Layout (import name `nexus_client`):

| New | From |
|---|---|
| `nexus/client/pyproject.toml` | new: `requests`, `pydantic`, `pydantic-settings` |
| `nexus/client/nexus_client/http.py` | `dagster/app/utils.py` (all of it) |
| `nexus/client/nexus_client/api.py` | `dagster/app/backend.py` `BackendAPI` + `dagster/fncli/backend.py` `FncliBackendAPI`, merged into one class |
| `nexus/client/nexus_client/models/` | `dagster/app/models/` |
| `nexus/client/nexus_client/git_uri.py` | `dagster/app/git_uri.py` |
| `nexus/client/tests/` | `dagster/app/tests/test_utils.py`, `test_backend.py`, `test_models.py`, `test_git_uri.py`, `dagster/fncli/tests/test_backend.py` |

Stays in Dagster: `app/config.py` (imports dagster), `app/secrets.py` (Kubernetes), `app/github.py`, `app/gitea.py`
(they import `HttpClient` from `nexus_client.http`).

Other files:
- `scripts/pip_compile.sh`: for `dagster` and `nexus/operator`, add `nexus/client/pyproject.toml` as a second source.
- `docker-bake.hcl`: `contexts = { nexus-client = "nexus/client" }` on `dagster-fn` (release target inherits it).
- `dagster/Dockerfile`: the four install steps from ADR 0032. Install the client with `-e` so Tilt can sync into it.
- `dagster/docker-compose-tests.yaml` and `-ci.yaml`: `build.additional_contexts`, mount `../nexus/client`.
- `dagster/pyproject.toml`: add `../nexus/client/tests` to `testpaths`; drop nothing else.
- `mise.toml` `setup`: `pip install --no-deps -e nexus/client` into the Dagster venv.
- `Tiltfile`: Dagster build becomes `custom_build_with_restart` running
  `docker buildx build --build-context nexus-client=nexus/client`, with a `sync` for `nexus/client/nexus_client`.
- `dagster/pylintrc`, `.github/workflows/build.yml`: add the client path.

Design decisions:
- `FncliBackendAPI`'s `force=True` deletes stay in fncli as a thin subclass. The client never forces.
- No compatibility shims in `app/`. Imports are repointed in one go (about 60 files).

Risks:
- The Tilt build change is the only non-mechanical part. Do it first, on its own.
- `FncliBackendAPI` overrides `get_datasets` and the deletes; merge by hand, not by script.

Done: no `app.backend`, `app.utils`, `app.models`, `app.git_uri` left (`git grep`); `dagster/requirements.txt`
regenerated; `mise run image --target dagster-fn` builds.

Test: `cd dagster && ./run_tests.sh local ../nexus/client/tests`, then `app/tests/test_resources.py`,
`fncli/tests/test_cli.py`.

### Step 3. CRDs and `nodeConfig` in the chart

What and why: the kinds the operator watches, and the values-to-resources templates a deployed node uses.

Files:
- `k8s/federated-node/crds/`: one static file per kind (Helm installs them before the templates). Group `fn.aridhia.com`, version `v1alpha1`, namespaced.
  Kinds: `GitProvider`, `NodeSecret`, `Repository`, `Dataset`, `Project`. Each has the `status` subresource,
  printer columns `Synced`, `Message`, and category `fn` (`kubectl get fn` lists all five).
- `k8s/federated-node/templates/node-config.yaml`: loops over `.Values.nodeConfig`.
- `values.yaml`, `values.schema.json`: `nodeConfig` (empty by default) and `operator.enabled` (false by default).
- `k8s/federated-node/tests/node_config_test.yaml`.

Design decisions:
- **`NodeSecret`, not `Secret`.** `kubectl get secrets` would always show core Secrets.
- **`NodeSecret` spec:** `fromSecret: {name}` (every key, same names) or
  `values: {KEY: {secretKeyRef: {name, key}}}`. The source Secret is in the resource's own namespace.
- **Names.** `metadata.name` is the nexus-api name (project, dataset, provider) or label (secret). A `Repository` is
  keyed by `spec.uri`; a `Project` refers to repositories by uri and datasets by name, as in the ADR examples.
- **Templated resource names** for values entries with no name (repositories): `trigger-` or `results-` plus the slug of the uri, so one uri can be both.
- **CRDs carry `helm.sh/resource-policy: keep`.** Uninstall never deletes the CRDs, so it cannot wipe config by
  cascade.
- The CRD schema carries the same checks as `dagster/fncli/nodefile/schema.py` where OpenAPI can express them
  (required fields, enums, patterns). The rest is the operator's job and nexus-api's.

Risks:
- CRDs and the resources that use them in one release failed a first install (kinds not yet known), so the CRDs
  moved to `crds/`. Helm never upgrades those: Flux does (step 8), `scripts/deploy.sh` applies them with kubectl.
- OpenShift already has a `Project` kind in another group. The group-qualified name works; the category `fn` is the
  short way round it.

Done: `mise run helm template` with a `nodeConfig` sample renders the five kinds; an empty `nodeConfig` renders none.

Test: `mise run helm lint`, `mise run helm tests` (the two new suites).

### Step 4. The operator

What and why: maps each custom resource to its nexus-api record.

Files:
- `nexus/operator/pyproject.toml`, `requirements.txt` (compiled with the client), `Dockerfile`, `pylintrc`.
- `nexus/operator/operator/main.py` (Kopf handlers), `sync.py` (one function per kind: desired spec + current record
  -> API calls), `settings.py` (pydantic-settings), `tests/`.
- `docker-bake.hcl`: `nexus-operator-fn`, `release-nexus-operator`.
- Chart: `templates/nexus-operator-deployment.yaml`, `nexus-operator-roles.yaml`; values `operator.*`.
- `build/kc-init/`: the operator's Keycloak user; `templates/keycloak-rotation-*.yaml` rotate it like Dagster's.
- `Tiltfile`, `scripts/tilt_manifests.py`: add the operator.

Design decisions:
- **Handlers.** `create`/`update`/`resume` call one `sync_<kind>`; a timer (default 60s) calls the same function,
  which is how UI edits are put back and source Secret rotation is seen.
- **Lookup by natural key, then adopt.** A record that already exists with the same name or uri is taken over and
  updated. `status.nexusId` is a cache, not the identity.
- **Dependencies by retry.** A `Project` whose dataset or repository is not there yet raises `kopf.TemporaryError`;
  status says what it waits for. No ordering in Helm or kubectl.
- **Status:** `synced`, `nexusId`, `message`, `observedGeneration`. `NodeSecret` also keeps the source Secret's
  `resourceVersion`; a change sends the values again. No value or hash of a value is stored.
- **Finalizer `fn.aridhia.com/nexus-sync`** (Kopf's `settings.persistence.finalizer`). Delete calls the API without
  `force`. A 409 keeps the resource in `Terminating` with the message in status and retries with backoff.
- **Uninstall.** A pre-delete hook Job stops the operator and strips the finalizers, so `helm uninstall` and
  `mise run teardown` do not hang and do not soft-delete records.
- **Namespaces.** The operator watches the release namespace plus `operator.watchNamespaces` (dev adds
  `experiments`). It reads a source Secret only in the resource's own namespace.
- **RBAC.** Role per watched namespace: the five kinds and their `status` (get, list, watch, patch), `secrets` (get),
  `events` (create). Kopf's peering is off (one replica, `Recreate` strategy).
- **Identity.** A Keycloak user `fn-operator` with the Administrator role, not `System`: it passes `can_do_admin`
  and cannot call the `system_only` routes. Password login, as Dagster does. Credentials in a Secret made by kc-init.
- **Field comparison** (`same_dir`, `same_uri`, `normalise_dir`) is lifted from `dagster/fncli/nodefile/diff.py` and
  `schema.py` into `sync.py`. The whole-file planner (`diff.py`, `apply.py`, `state.py`) is not reused.
- **Attribution.** The operator logs the Flux annotations and puts them in a Kubernetes Event. nexus-api stores
  nothing yet (see ADR 0032).

Risks:
- A stuck `Terminating` resource blocks re-adding the same entry until the delete goes through. Status says why.
- Delete then re-add makes a new record with a new id; history stays on the old one.
- The timer makes API calls per resource per minute. Fine at node scale (tens of resources).
- Administrator is wider than "node config only". A narrower Keycloak role is a follow-up.

Done: in dev, `kubectl apply -f` a provider, secret, repository, dataset and project; `kubectl get fn` shows all
synced; an edit in the UI is put back within the timer; `kubectl delete` soft-deletes.

Test: `nexus/operator/tests/test_sync.py` (API client mocked, one test file per kind if it grows),
`mise run helm tests` for `nexus_operator_test.yaml`. Kopf handlers stay thin and are not unit tested.

### Step 5. Move dev onto `kubectl apply`, drop fncli `diff`/`apply`/`delete`

What and why: dev runs the production path; one engine.

Files:
- `config/` (new): the resources that replace `bootstrap/examples/globals-*.yaml` and `projects/*.yaml`.
  `bootstrap/context.yaml` stays (which node fncli talks to).
- `experiments/chart/`: each experiment's `Dataset` and `NodeSecret` become chart templates in namespace
  `experiments`; `experiments/*/dataset.yaml` go.
- `dagster/fncli/cmds/experiment.py`: `setup`/`teardown` stop calling `apply_node_file`/`delete_node_file`.
- `dagster/fncli/cmds/demo.py`: reads the `Project` resource and its status instead of diffing a node file.
- `dagster/fncli/gitea.py` + a `fncli gitea setup -f config/...` command: creates the Gitea repositories and OAuth
  apps for the `Repository` resources on a Gitea provider, and writes the OAuth credentials to a Kubernetes Secret
  that a `NodeSecret` names. `--rotate` moves here.
- `dagster/fncli/tests/e2e/conftest.py`: `apply_node`, `apply_second_project` and the rotate fixture use
  `fncli gitea setup` and `kubectl apply`, then wait for `synced`.
- Delete: `dagster/fncli/nodefile/`, `cmds/nodefile.py`, `tests/test_nodefile_*.py`, `DESIGN-node-file.md`.
- Docs: `DEMO.md`, `FRESH_SETUP.md`, `MANAGEMENT.md`, `SETUP_GIT_APPS.md`, `DEPLOYMENT.md`, `experiments/README.md`,
  `dagster/fncli/README.md`, `AGENTS.md`, `.dev.env.example`.

Design decisions:
- `generate` secret references (random dev credentials) are not carried over; the experiments chart already makes
  the Secret.
- `env` and `file` references become `kubectl create secret` lines in the docs, as in ADR 0032.

Risks:
- Largest step by file count; the e2e fixtures cannot be proved without an e2e run. Ask before running one.
- `fncli demo` loses its "rows that differ" check; `status.message` replaces it.

Done: `git grep -n "fncli apply\|fncli diff\|fncli delete"` is empty; `fncli experiment setup demo` then
`kubectl apply -f config/` gives a working demo project.

Test: `cd dagster && ./run_tests.sh local fncli/tests/test_experiment.py`, `test_demo.py`, `test_gitea.py`,
`test_cli.py`.

## Part 2: Flux, local with Gitea first

### Step 6. Gitea Actions and `act_runner` (dev only)

What and why: a CI that runs inside kind, so the release workflow can be proved with no GitHub.

Files:
- `templates/gitea-deployment.yaml`: `GITEA__actions__ENABLED` from `gitea.actions.enabled`.
- `templates/gitea-runner-deployment.yaml` (new): `gitea/act_runner` with a Docker-in-Docker sidecar (privileged).
- `templates/gitea-runner-secret.yaml`: a chart-generated runner registration token (kept across upgrades with
  `lookup`), given to Gitea as `GITEA_RUNNER_REGISTRATION_TOKEN` and to the runner, so nothing waits on a hook.
- `values.yaml`, `values.schema.json`: `gitea.actions.enabled`, `gitea.actions.runner.*`, default false;
  `dev.example.values.yml` turns them on.
- `tests/gitea_actions_test.yaml`.

Risks: the privileged sidecar is dev only; the schema refuses `gitea.actions.runner` unless `local_development`.

Done: a hello-world workflow pushed to a Gitea repository runs green.

Test: `mise run helm tests` (the new suite).

### Step 7. Release workflow in Gitea Actions

What and why: a tag builds the images and the chart and publishes both as OCI artifacts.

Files:
- `.gitea/workflows/release.yml`: on tag `v*`: `docker buildx bake release` with the registry overridden, then
  `helm package --version $TAG --app-version $TAG` and `helm push`.
- `docker-bake.hcl`: the `release` group gains nexus-api, nexus-ui and the operator; release tags take a
  `RELEASE_REGISTRY` variable (default `ghcr.io/aridhia-open-source`).
- `scripts/mirror_to_gitea.sh` + mise task: push the working tree to a Gitea repository so the workflow has source.

Design decisions:
- **Publish to the kind registry** (`kind-registry:5000`, `localhost:5001` from the host). kind's nodes already pull
  from it. Gitea's package registry would need containerd changes on the nodes.
- The workflow uses only `run:` steps and bake, so the GitHub Actions port (step 10) is a copy.

Risks: the runner must reach `kind-registry` (join the `kind` Docker network) and push over plain HTTP.

TODO: add `release-nexus-operator` (inherits `nexus-operator-fn`) to the `release` group once PR #656 brings that target.

Done: pushing tag `v0.0.1-dev` to Gitea leaves `charts/federated-node:0.0.1-dev` and the images in the registry.

Test: none in unit tests; `helm show chart oci://localhost:5001/charts/federated-node --version 0.0.1-dev`.

### Step 8. Flux in kind and a test site repository

What and why: the site's side of delivery, scripted so it repeats.

Files:
- `scripts/flux.sh` + mise task `flux` (`up`, `down`, `status`): `flux install`, create the site repository in
  Gitea, push its content, apply the `GitRepository` and `Kustomization`.
- `site-example/`: `helmrepository.yaml` (OCI, `insecure: true`), `helmrelease.yaml` (pinned version, rollback on
  failure), `values.yaml` (dev values plus `nodeConfig`).
- `mise.toml`: add the `flux` CLI to the pinned tools.

Design decisions:
- **Flux adopts the release `mise run deploy` made** (same name and namespace). Gitea lives inside that release, so
  it must exist before Flux can read the site repository.
- `flux.sh up` claims the cluster (`scripts/deploy_owner.sh`); `mise run deploy` refuses while Flux owns the
  release, so the two do not fight.
- Site values hold no secret values; the dev Secrets already exist in the cluster.
- **The HelmRelease sets `install.crds: CreateReplace` and `upgrade.crds: CreateReplace`.** The node config CRDs are
  in the chart's `crds/`, which Helm installs once and never upgrades; Flux applies them on every upgrade.

Risks: an upgrade restarts Gitea, the source Flux reads from. Flux retries on its interval; expect one failed
reconcile per upgrade in this local setup only.

Done: `mise run flux up` on a deployed dev cluster ends with `flux get hr` Ready at the pinned version.

Test: `mise run helm template -f site-example/values.yaml`; shellcheck on `scripts/flux.sh`.

### Step 9. Prove the loop and write it down

Three runs, each a commit to the site repository:
1. Bump the chart version -> Flux upgrades (`helm history` shows the revision).
2. `git revert` -> Flux upgrades back.
3. Add a project to `nodeConfig` -> the operator syncs it; revert -> it is soft-deleted.

Files: `docs/versions/2.x/docs/GitOps-Delivery.md` (the steps and what to expect), linked from `DEPLOYMENT.md` and
`docs/README.md`.

Risks: run 2 only passes if the two versions' migrations are compatible (ADR 0031). Use two builds of one commit.

Done: the doc's commands, run in order on a fresh `mise run deploy`, give the three results.

### Step 10. Later, separate PR

GitHub Actions port of the release workflow, the release bundle with `upgrade.sh`, SOPS, Pulumi (not started yet).
