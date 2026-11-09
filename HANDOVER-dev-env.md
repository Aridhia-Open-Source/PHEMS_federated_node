# Handover: shrink `.dev.env` to true secrets

For PR #617 (branch `fncli-bootstrap-files`; keep `fncli-declarative-config` the same tree). Delete this file in
the commit that finishes the work.

## Rule

- **Secrets** stay in `.dev.env` (gitignored): `KEYCLOAK_FIRST_USER_EMAIL`, `KEYCLOAK_FIRST_USER_PASSWORD`,
  `RESEARCHER_GIT_TOKEN`.
- **Per-person / per-node settings** go in `bootstrap/context.yaml` (gitignored; committed example in
  `bootstrap/examples/context.yaml`, schema in `dagster/fncli/nodefile/schema.py`).

## What moves

| Variable | New home in context.yaml |
|---|---|
| `DOCKER_TAG`, `NAMESPACE`, `RELEASE_NAME`, `VALUES_FILE`, `FN_DATA_DIR` | `dev:` section (`docker_tag`, `namespace`, `release_name`, `values_file`, `data_dir`) |
| `DAGSTER_URL` | `node.dagster_url` (default `http://localhost:3000`) |
| `GITEA_TOKEN_NAME`, `GITEA_RESULTS_TOKEN_NAME` | `node.gitea_token_name`, `node.gitea_results_token_name` (defaults `fn-sensor`, `fn-results`) |
| `GH_APP_ID`, `GH_INSTALLATION_ID` | `github.app_id`, `github.installation_id` (vary per person, so local file only; example has placeholders) |

## Approach (keep it small)

1. Add the fields to the context schema (`schema.py`) and the example `bootstrap/examples/context.yaml`.
2. Add `fncli context env`: prints `export NAME=value` lines for the moved settings, using the **existing**
   variable names above. Then shell consumers only change their load line:
   `source .dev.env` -> `source .dev.env; eval "$(fncli context env)"`.
   Files with `source .dev.env`: `scripts/cluster.sh`, `deploy.sh`, `upgrade.sh`, `teardown.sh`,
   `reload_app.sh`, `nexus_login.sh`. Also `Makefile:49` (BAKE line) and `Tiltfile:17` (`dotenv('.dev.env')`;
   add `local('fncli context env')` parsing or read the yaml with Tilt's `read_yaml`).
   `scripts/cluster.sh` currently parses `kube_context` with sed: switch it to the same helper.
3. fncli itself reads the new fields from the context directly: `dagster/fncli/cmds/common.py` lines ~59, 83, 161,
   172 (namespace, dagster_url, token names) and wherever `GH_APP_ID`/`GH_INSTALLATION_ID` are read
   (`git grep -n GH_APP_ID`). `bootstrap/examples/globals-github.yaml` header mentions them.
4. Drop `node.env_file` loading only if nothing still needs it (`dagster/fncli/cmds/nodefile.py:136`,
   `nodefile/loader.py:107`); fncli's `cli.py:28` keeps loading `.dev.env` for the secrets.
5. Update `.dev.env.example` (secrets only), `k8s/federated-node/dev.example.values.yml` lines 3, 52, 89,
   `experiments/*/project.env` headers, `tilt/scripts/dagster_reload.sh`, and docs that name the moved vars
   (`git grep -n "DOCKER_TAG\|RELEASE_NAME\|VALUES_FILE\|FN_DATA_DIR\|GH_APP_ID\|DAGSTER_URL" -- '*.md'`).
6. Local files in the user's worktree `wt-fncli-config`: add the moved values to `bootstrap/context.yaml`
   (copy from `.dev.env`; NEVER print secret values), then comment the moved keys out of `.dev.env`.

## How to work

- Use `git grep -n VAR` and `sed -n 'A,Bp'` around hits. Do not read whole files.
- No tests unless asked. `bash -n` changed scripts; `fncli context env` once by hand.
- Commit on `fncli-declarative-config`, push, cherry-pick onto `fncli-bootstrap-files`, push.
  `git diff origin/fncli-declarative-config origin/fncli-bootstrap-files --stat` should stay empty.
- No Co-Authored-By lines.

## Where usages are (grep, 2026-11-09)

`.kind/kind-config.yaml`, `Makefile`, `Tiltfile`, `bootstrap/examples/{context,globals-github}.yaml`,
`build/alpine/scripts/cleanup.sh` (check: may be an unrelated NAMESPACE), `dagster/fncli/cmds/{common,experiment,secret}.py`,
`dagster/fncli/tests/{conftest,test_config,test_experiment,test_secret}.py`, e2e `test_failure_paths*.py`,
`docker-bake.hcl`, `experiments/chart/values.yaml`, `k8s/federated-node/dev.example.values.yml`,
`nexus/ui/scripts/screenshots.mjs` (reads the Keycloak user from `.dev.env`: unchanged),
`scripts/{cluster,deploy,reload_app,teardown,upgrade}.sh`, `tilt/scripts/dagster_reload.sh`.
