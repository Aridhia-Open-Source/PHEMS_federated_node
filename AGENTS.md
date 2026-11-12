# AGENTS.md

A short guide for coding agents and new developers. Deeper detail is in the docs listed at the end.

## What this repo is

- The Federated Node (FN): a Kubernetes-deployed service that runs analysis tasks against local datasets and delivers the results back through git.
- `nexus-api` (FastAPI) owns the record and the rules: projects, datasets, repositories, secrets, triggers, tasks, results. Keycloak handles users and tokens. `nexus-ui` is a React admin UI for it.
- Dagster pipelines ingest merged pull requests from GitHub or Gitea, launch a task per pull request, and deliver results as a pushed branch plus a results pull request.
- Shipped as one Helm chart (`k8s/federated-node`) with Traefik (Gateway API), Keycloak, Postgres, and optional Dagster and Gitea (both `enabled: false` by default).

## Repo map

- `nexus/api/` - the backend (FastAPI, SQLAlchemy, Alembic).
  - `app/*_api.py` - routers, one per resource; `app/main.py` builds the app.
  - `app/dtos/` - Pydantic response DTOs (ADR 0016); `app/models/` - SQLAlchemy models.
  - `app/helpers/` - state rules, Keycloak, Kubernetes, git tokens, task config and resources.
  - `migrations/versions/` - a single baseline migration (`001_baseline.py`, see ADR 0023).
  - `tests/` - unit tests; `integration_tests/` - Keycloak integration scripts.
- `nexus/ui/` - React + Vite + TypeScript admin UI; API client and generated types in `src/api/`.
- `dagster/app/` - the Dagster code location.
  - `definitions/sensors/git/` - pull request ingest and evaluate sensors and jobs.
  - `definitions/sensors/task/` - launcher, run status, reconcile, delivery, results PR sync.
  - `definitions/` - `jobs.py`, `ops.py`, `pipes.py`, `resources.py`, `run_config.py`.
  - `delivery/` - results packaging and git push; `github.py`, `gitea.py` - git clients.
  - `backend.py` - the nexus-api client; `models/` - Dagster-side models of API responses.
- `dagster/fncli/` - `fncli`, the dev/ops CLI (ADR 0018); commands in `cmds/`, e2e suites in `tests/e2e/`.
- `k8s/federated-node/` - the Helm chart: `templates/`, `values.yaml`, `values.schema.json`, `dev.example.values.yml`, helm-unittest suites in `tests/`.
- `build/` - images for Keycloak, `kc-init`, an Alpine helper, and the helm-unittest runner.
- `pypipes/` - a small task image (`pypipes-fn`) used by fncli and the e2e suites.
- `experiments/` - real experiment projects and their chart, driven by `fncli experiment` (see `experiments/README.md`).
- `scripts/` - cluster, deploy, build, lint, pip-compile and test helpers (called from the Makefile).
- `Tiltfile`, `tilt/`, `.tilt/` - the Tilt dev loop (ADR 0020); `docker-bake.hcl` - image build targets.
- `project/decisions/` - ADRs; `docs/` - architecture docs (`docs/architecture/`) and JSON schemas (`docs/schemas/`).
- `dev.k8s/` - extra dev database deployments (Postgres, MySQL, MariaDB, MSSQL, Oracle) for dataset testing.

## Dev loop

Run from the repo root. First-time setup (`.dev.env`, `dev.values.yaml`) is in `DEPLOYMENT.md` ("Run it locally").

1. Cluster (human developers only): `make cluster up` / `make cluster down` (`scripts/cluster.sh`) create or delete the kind cluster `fn` and the local registry at `localhost:5001`. Agents never run these, nor `make nuke`; they work against a cluster that already exists. Run `make helm_deps` once first (`charts/` is gitignored).
2. Release:
   - `make deploy` - build all images and `helm install` with dev values (claims the cluster for this worktree).
   - `make upgrade` - helm upgrade after chart changes, then restart the app deployments.
   - `make teardown` - remove the release and its data, keep the cluster; `make nuke` - teardown, new cluster, deploy (human developers only).
   - `make deploy-owner` - which worktree owns the cluster; `make show-db-passwords` - generated DB passwords.
3. Tilt: `make tilt-up` (or `tilt up`), `make tilt-down`.
   - Live reload: edits in `nexus/api/app/` and `dagster/app/` are synced and the process restarts.
   - Rebuild: `requirements.txt`, `alembic.ini` and migrations rebuild the image; chart changes need `make upgrade`.
   - Port-forwards: nexus-api `localhost:5000` (docs at `/docs`), nexus-ui `8088`, Dagster UI `3000`, Gitea `4000`, Keycloak `8080`, Postgres `5432`, Tilt dashboard `10350`.
   - Wait for readiness: `tilt wait --for=condition=Ready uiresource/nexus-api --timeout=180s`.
4. Typical loop: edit code -> Tilt reloads the pod -> run the unit tests for what you changed -> widen to the package suite.

### Worktrees and cluster ownership

- Work in a git worktree per branch: `make worktree NAME=<dir> BRANCH=<branch> [BASE=<ref>]` creates a sibling worktree and copies in the gitignored dev config (`.dev.env`, `dev.values.yaml`).
- One worktree owns the shared dev cluster at a time (`scripts/deploy_owner.sh claim|check|show|release`). `make deploy` and `make upgrade` claim it and refuse if another worktree owns it.
- Before deploy, upgrade or teardown, check `make deploy-owner`. Never take over another worktree's cluster (`FORCE_OWNER=1`) without asking.

Testing rule: first run only the unit tests for the files or package you changed. Widen to the full package suite only when those pass or the change is cross-cutting. Do not run the e2e suites unless explicitly asked: they need a deployed cluster and take a long time.

## Commands

Images:

- `make images` - build every dev image with `docker buildx bake` (`scripts/build_images.sh`), tagged `latest`, pushed to `localhost:5001`.
- `make image NAME=nexus-api-fn` - one bake target; `make image-reload NAME=...` also restarts deployments.
- `make images-release TAG=x.y.z` - build the release images locally.

Dependencies (Python):

- Declare in the component's `pyproject.toml`, then `make pip_compile <dir>` (e.g. `make pip_compile nexus/api`). This runs `scripts/pip_compile.sh`, which writes a hashed, pinned `requirements.txt`. Commit both.
- `make pip_compile nexus/api requirements-dev.txt` writes the dev requirements.

Tests and lint:

- nexus-api: `cd nexus/api && ./run_tests.sh local tests/test_projects_api.py` (docker compose with Postgres; second argument is the pytest path). Faster venv runs: `nexus/api/run_local_tests.sh` (setup in its header).
- Dagster app and fncli: `cd dagster && ./run_tests.sh local fncli/tests/test_cli.py` (docker compose; pytest `testpaths` are `app/tests` and `fncli/tests`). `make tests_dagster` runs all in CI mode.
- UI: `cd nexus/ui && npm ci && npm test` (vitest); `npm run typecheck` for types.
- Chart: `make helm_lint helm_template` (no cluster needed), `make helm_tests` (helm-unittest).
- Lint: `make pylint` (nexus-api), `make pylint_dagster`, `make hadolint` (Dockerfiles).
- End-to-end: `pytest dagster --e2e [success|failure|failure_long] -v` from the repo root. Needs a running dev cluster deployed from the branch under test, and `.dev.env`; see `dagster/fncli/tests/e2e/README.md`. Without `--e2e` these tests are skipped.

## Conventions

- ADRs live in `project/decisions/` as `NNNN-short-title.md`, MADR style (Context, Decision, Consequences, Alternatives considered, Open questions), present tense. Add each new one to the index tables in `project/decisions/README.md` and `docs/README.md`.
- PR titles follow Conventional Commits: `type(scope): description`, e.g. `feat(tasks): default-deny task network egress`.
- PRs use `.github/PULL_REQUEST_TEMPLATE/pull_request_template.md` (summary, tests, `CHANGELOG.md`).
- Python imports go at the top of the module.
- pylint config: `nexus/api/pylintrc`, `dagster/pylintrc`; `max-line-length=120`.
- Python dependencies are pinned with hashes in `requirements.txt`; use `~=` specifiers in `pyproject.toml`.
- Secrets are Kubernetes Secrets referenced by name from values (e.g. `firstUserSecret`); secret values never go in values files, examples or committed `.env` files. `.dev.env` and `dev.values.yaml` are gitignored.
- API responses are built through DTOs; state changes go through the transition tables in `nexus/api/app/helpers/state_rules.py` (ADR 0005, a refused move is a 409).
- nexus-api decides, Dagster carries out decisions (ADR 0021); Dagster and fncli parse API responses into their own models.
- CI (`.github/workflows/build.yml`) runs pylint, hadolint, helm lint/template/unittest, nexus-api tests, Dagster tests and Keycloak integration tests.

## Working tips for agents

- Find code with `git grep -n <symbol>` and read the lines around the hits; avoid reading whole modules.
- Start from the router (`nexus/api/app/<resource>_api.py`), DTO, model, then helper; on the Dagster side, from the sensor in `dagster/app/definitions/sensors/`.
- Follow the testing rule above; pass the test path to `run_tests.sh`.
- Generated files, and how to regenerate them:
  - `requirements.txt` / `requirements-dev.txt` - `make pip_compile <dir>`.
  - `nexus/api/openapi.json` - `cd nexus/api && python dump_openapi.py` (needs the API's dependencies).
  - `nexus/ui/src/api/schema.d.ts` - `cd nexus/ui && npm run gen:api` (from `openapi.json`).
  - Migrations: see `nexus/api/migrations/README` and ADR 0023 before adding one.
- Chart changes: keep `values.yaml` and `values.schema.json` in step, and add or update a suite in `k8s/federated-node/tests/`.

## Read next

- `DEPLOYMENT.md` - local dev cluster and production deploy; `MANAGEMENT.md` - setting up projects, and `fncli`.
- `docs/README.md` - reviewer's guide: every ADR, the docs by topic, a reading order.
- `docs/architecture/entities.md`, `flows.md`, `revoke-and-enabled.md`, `sensors/` - schema, states, flows, one doc per sensor.
- `project/decisions/README.md` - ADR index; `project/TESTING.md` - testing notes.
- `dagster/fncli/README.md`, `k8s/federated-node/README.md`, `.tilt/TILT_QUICKSTART.md`, `SETUP_GIT_APPS.md`.
