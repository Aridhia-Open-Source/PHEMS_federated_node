# Docs drift report (docs vs code), branch dagster-develop

Format: `doc-file:line` -> what it says -> what is true -> the fix.

## Confirmed mismatches

- `AGENTS.md:35` -> `dev.k8s/` holds extra dev database deployments (Postgres, MySQL, MariaDB, MSSQL, Oracle) -> no `dev.k8s/` directory exists and no tracked file matches it; the only mention in the repo is this line -> delete the line (or point at wherever those deployments now live).
- `DEPLOYMENT.md:353` -> local-path storage is set with `storage.local.path`, `.dbpath`, `.artifacts` -> no template reads `storage.local.path`; the chart reads `storage.local.artifacts`, `storage.local.dbpath` and `storage.local.gitea` (`templates/_functions.tpl:56`, `db-pv.yaml:15`, `gitea-pvc.yaml:15`); the wiki (`Deploy-Core.md:151`) already says `artifacts` + `dbpath` -> drop `storage.local.path` from the row.
- `dagster/fncli/README.md:102` -> `init-backend-*` commands assign the global record to the project with `POST /projects/<id>/...` -> assignment is `PUT /projects/{project_id}/datasets/{dataset_id}`, `.../secrets/{label}`, `.../repositories/triggers/{repo_id}`, `.../repositories/results/{repository_id}` (openapi.json; `dagster/fncli/backend.py:67,209,265` use `session.put`); there is no POST on those paths -> change `POST` to `PUT`.
- `.tilt/TILT_QUICKSTART.md:113` -> "Edit nexus/api/app/routes.py" -> no such file; routers are `nexus/api/app/*_api.py` (e.g. `projects_api.py`) -> name a real file.
- `k8s/federated-node/README.md:92` -> Gateway API CRD update: `wget ... -O k8s/federated-node/scripts/gateway-api-crds-<version>.yaml` -> no `gateway-api-crds-*` file is tracked and nothing in the chart or scripts reads one; `scripts/gateway-api-installer.sh:7` applies `experimental-install.yaml` straight from the release URL (the README downloads `standard-install.yaml`). The wget line is also mis-quoted: `-O ...` sits inside the URL's double quotes -> replace the section with the installer script, or remove it.
- `docs/README.md` (ADR table, after the 0023 row; 0021 row is line 31) -> lists ADRs 0001-0023 -> `project/decisions/0024-github-app-tokens-minted-by-the-backend.md` exists and is in `project/decisions/README.md:40` but is missing from `docs/README.md` -> add the 0024 row (and to the reading order at line 70 if wanted).
- `project/decisions/0024-github-app-tokens-minted-by-the-backend.md:37` -> links `0021-webserver-owns-the-record-and-the-rules.md` -> file is `0021-nexus-api-owns-the-record-and-the-rules.md` -> fix the link target.
- `docs/README.md:46` -> links `../project/auth-mvp-plan.md` -> file does not exist (`project/` holds only `QA`, `TESTING.md`, `decisions`) -> remove the entry or restore the file.
- `project/decisions/0017-authorization-detached-from-dar-and-keycloak.md:32` -> links `../auth-mvp-plan.md` -> same missing file -> remove the link or restore the file.
- `AGENTS.md:39` and `AGENTS.md:57` (minor) -> init-conf creates `.dev.env` and `dev.values.yaml` -> `scripts/init_conf.sh:39` writes `k8s/federated-node/dev.values.yaml` (from `dev.example.values.yml`); there is no root `dev.values.yaml` -> give the full path once.

## Checked and found correct

- AGENTS.md: every other path in the repo map and "Read next" exists; every `mise run` task and flag named (`pip-compile --dir/--out/-- extra`, `image --target`, `image-reload --target`, `images-release --tag`, `deploy --force-owner`, `worktree --name/--branch/--base`, `cluster-up/down`, `teardown`, `reload-app`, `deploy-owner`, `show-db-passwords`, `portfwd`, `helm-*`, `pylint*`, `hadolint`, `tests-dagster`, `init-conf`, `setup`) is defined in `mise.toml`; `scripts/deploy_owner.sh claim|check|show|release` exist; `nexus/api/run_tests.sh`, `run_local_tests.sh`, `dump_openapi.py`, `dagster/run_tests.sh` exist and take the arguments shown; `npm test` (vitest), `npm run typecheck`, `npm run gen:api` exist in `nexus/ui/package.json`; pytest `testpaths` are `app/tests` and `fncli/tests`; `--e2e` choices include success, failure, failure_long; ports 5000/8088/3000/4000/8080/5432 match the Tiltfile and `scripts/portfwd.sh`; `max-line-length=120` in both pylintrc files; bake target `nexus-api-fn` exists; CI runs the jobs listed.
- No doc (outside the 1.x pages) names a `mise run` task that is not defined. `make` appears only in the DEPLOYMENT.md make-to-mise translation table (lines 138-170), which is intentional.
- Every `fncli <command>` and `fncli experiment <sub>` named in the docs exists in `dagster/fncli/cmds/`.
- Every API route (path, and method where stated) named in DEPLOYMENT.md, MANAGEMENT.md, the fncli and chart READMEs and the 2.x wiki pages exists in `nexus/api/openapi.json`, apart from the fncli README line above.
- ADR numbers 0001-0024 are unique; all 24 are in `project/decisions/README.md`; neither index names a file that is missing.
- Other values keys flagged by the script (`storage.azure/aws/nfs.*`, `db.host`, `fnDagster.artifacts.mountOptions`, `global.postgresqlSecretName`) are read by templates; `fnDagster.db` is correctly documented as removed.

## Not covered

- `openapi.json` was used as the route source; it was not checked against the routers for staleness.
- Request/response body fields, env var names, secret names and key names in the docs (e.g. `tls.crt`/`tls.key` secret keys, `.dev.env` variables) were not checked.
- Subchart values in the wiki (`traefik.service.*`, `dagster.*`) were not checked against the subcharts.
- fncli command options/flags (only command names were checked); `dagster/fncli/README.md` prose in detail.
- `docs/architecture/*`, `docs/schemas/*`, `project/TESTING.md`, `experiments/README.md`, `SETUP_GIT_APPS.md`, `README.md` beyond links, paths and fncli/route names.
- The 1.x wiki pages and `docs/versions/2.x/docs/api/`.
- Anchor (`#section`) targets in markdown links; external URLs.
- ADR index titles/summaries vs ADR content; ADR numbers cited in prose (e.g. AGENTS.md "ADR 0023" for migrations) were only checked to exist.
