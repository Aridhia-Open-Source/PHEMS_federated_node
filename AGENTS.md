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
- `scripts/` - cluster, deploy, build, lint, pip-compile and test helpers (wrapped by the mise tasks in `mise.toml`).
- `Tiltfile`, `tilt/`, `.tilt/` - the Tilt dev loop (ADR 0020); `docker-bake.hcl` - image build targets.
- `project/decisions/` - ADRs; `docs/` - architecture docs (`docs/architecture/`) and JSON schemas (`docs/schemas/`).
- `dev.k8s/` - extra dev database deployments (Postgres, MySQL, MariaDB, MSSQL, Oracle) for dataset testing.

## Dev loop

Run from the repo root. `mise tasks` lists the tasks. First-time setup: `mise run init-conf` creates `.dev.env` and `dev.values.yaml` from the examples and asks for the first Keycloak user; the rest is in `DEPLOYMENT.md` ("Run it locally").
Run `mise run setup` once per checkout (installs the pinned tools and the per-package venvs), and `mise trust` if mise asks.

1. Cluster (human developers only): `mise run cluster-up` / `mise run cluster-down` (`scripts/cluster.sh`) create or delete the kind cluster `fn` and the local registry at `localhost:5001`. Agents never run these; they work against a cluster that already exists. Run `mise run helm-deps` once first (`charts/` is gitignored).
2. Release:
   - `mise run deploy` - build all images and `helm upgrade --install` with dev values, then restart the app pods. Safe to rerun, so it is also how chart changes go out (claims the cluster for this worktree).
   - `mise run teardown` - remove the release and its data, keep the cluster. To start clean, `mise run teardown` then `mise run deploy`.
   - `mise run reload-app` - rebuild only the Dagster and nexus-api images and restart their pods.
   - `mise run deploy-owner` - which worktree owns the cluster; `mise run show-db-passwords` - generated DB passwords.
3. Tilt: `tilt up` and `tilt down` (no mise task). `mise run portfwd` port-forwards the services when Tilt is not running.
   - Live reload: edits in `nexus/api/app/` and `dagster/app/` are synced and the process restarts.
   - Rebuild: `requirements.txt`, `alembic.ini` and migrations rebuild the image; chart changes need `mise run deploy`.
   - Port-forwards: nexus-api `localhost:5000` (docs at `/docs`), nexus-ui `8088`, Dagster UI `3000`, Gitea `4000`, Keycloak `8080`, Postgres `5432`, Tilt dashboard `10350`.
   - Wait for readiness: `tilt wait --for=condition=Ready uiresource/nexus-api --timeout=180s`.
4. Typical loop: edit code -> Tilt reloads the pod -> run the unit tests for what you changed -> widen to the package suite.

### Worktrees and cluster ownership

- Work in a git worktree per branch: `mise run worktree --name <dir> --branch <branch> [--base <ref>]` creates a sibling worktree and copies in the gitignored dev config (`.dev.env`, `dev.values.yaml`).
- One worktree owns the shared dev cluster at a time (`scripts/deploy_owner.sh claim|check|show|release`). `mise run deploy` claims it and refuses if another worktree owns it.
- Before deploy or teardown, check `mise run deploy-owner`. Never take over another worktree's cluster (`mise run deploy --force-owner`) without asking.
- A dev container (`.devcontainer/`) can be used instead of local tools; it shares the host's Docker, kind cluster and network, so the ownership rules above apply inside it too. It mounts the checkout's parent folder at its host path, so git and the cluster owner work there only for the main repo and worktrees beside it (`mise run worktree`).
- Clean up behind you: remove a worktree you made for temporary work as soon as it is no longer needed, and remove a branch's worktree once the branch is merged or its PR closed (`git worktree remove <dir>`, then `git worktree prune`). Only remove worktrees with no uncommitted changes; release the cluster first if the worktree owns it.

Testing rule: first run only the unit tests for the files or package you changed. Widen to the full package suite only when those pass or the change is cross-cutting. Do not run the e2e suites unless explicitly asked: they need a deployed cluster and take a long time.

## Commands

Images:

- `mise run images` - build every dev image with `docker buildx bake` (`scripts/build_images.sh`), tagged `latest`, pushed to `localhost:5001`.
- `mise run image --target nexus-api-fn` - one bake target; `mise run image-reload --target <target>` also restarts deployments.
- `mise run images-release --tag x.y.z` - build the release images locally.

Dependencies (Python):

- Declare in the component's `pyproject.toml`, then `mise run pip-compile --dir <dir>` (e.g. `mise run pip-compile --dir nexus/api`). This runs `scripts/pip_compile.sh`, which writes a hashed, pinned `requirements.txt`. Commit both.
- `mise run pip-compile --dir nexus/api --out requirements-dev.txt` writes the dev requirements; extra flags after `--` (for example `-- --upgrade`) go to pip-compile.

Tests and lint:

- nexus-api: `cd nexus/api && ./run_tests.sh local tests/test_projects_api.py` (docker compose with Postgres; second argument is the pytest path). Faster venv runs: `nexus/api/run_local_tests.sh` (setup in its header).
- Dagster app and fncli: `cd dagster && ./run_tests.sh local fncli/tests/test_cli.py` (docker compose; pytest `testpaths` are `app/tests` and `fncli/tests`). `mise run tests-dagster` runs all in CI mode.
- UI: `cd nexus/ui && npm ci && npm test` (vitest); `npm run typecheck` for types.
- Chart: `mise run helm-lint`, `mise run helm-template` (no cluster needed), `mise run helm-tests` (helm-unittest).
- Lint: `mise run pylint` (nexus-api), `mise run pylint-dagster`, `mise run hadolint` (Dockerfiles).
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
  - `requirements.txt` / `requirements-dev.txt` - `mise run pip-compile --dir <dir>`.
  - `nexus/api/openapi.json` - `cd nexus/api && python dump_openapi.py` (needs the API's dependencies).
  - `nexus/ui/src/api/schema.d.ts` - `cd nexus/ui && npm run gen:api` (from `openapi.json`).
  - Migrations: see `nexus/api/migrations/README` and ADR 0023 before adding one.
- Chart changes: keep `values.yaml` and `values.schema.json` in step, and add or update a suite in `k8s/federated-node/tests/`.

## Read next

- `DEPLOYMENT.md` - local dev cluster and production deploy; `MANAGEMENT.md` - setting up projects, and `fncli`.
- `docs/versions/2.x/docs/` - the 2.x user and operator wiki (published to the GitHub wiki and the docs site): `Deploy-Core` plus one deploy page per platform, `Prerequisites`, `Datasets`, `Researcher-Guide`, `Operations`, `Architecture`, `Using-The-API`. Edit the page here, not in the wiki: a workflow syncs `docs/versions/2.x/docs` on push.
- `docs/README.md` - reviewer's guide: every ADR, the docs by topic, a reading order.
- `docs/architecture/entities.md`, `flows.md`, `revoke-and-enabled.md`, `sensors/` - schema, states, flows, one doc per sensor.
- `project/decisions/README.md` - ADR index; `project/TESTING.md` - testing notes.
- `dagster/fncli/README.md`, `k8s/federated-node/README.md`, `.tilt/TILT_QUICKSTART.md`, `SETUP_GIT_APPS.md`.
