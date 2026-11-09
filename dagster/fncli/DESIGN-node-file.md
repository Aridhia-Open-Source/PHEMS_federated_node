# fncli: a declarative node file instead of env vars

Draft, 2026-11-09. Design only, no code. Read against the `fncli-provider-from-backend` branch, assuming its in-flight work lands: provider type comes from the backend record or the repo uri's host, fncli's git calls use tokens nexus-api mints, trigger and results `base_branch` are explicit, and there is a global `--env-file`.

## 1. Problem

- **One project per env file.** A second project means a second file and `--env-file` juggling. The layers are `.dev.env`, then `.demo*.env` or `project.env` over it, then the shell. Each layer overrides differently.
- **Flat `TEST_*` names carry the model.** About 30 variables. Every config class in `cmds/common.py` requires every field non-empty. Gitea vs GitHub is a pile of properties (`is_github`, `repo_path`, `web_url`, `pulls_page`) worked out from a uri.
- **Global and project things are muddled.** A secret label is `<repo>-creds` or `<DEFAULT_PROJECT_DATASET>-dataset-creds`. The GitHub demo is one repo playing two roles, so two entities share one label by accident of naming.
- **Secrets sit beside addresses.** The GitHub App key is exported from `$(cat key.pem)` in a shell.
- **No preview, and no reconcile.** The `get_or_create_*` and `get_or_assign_*` calls in `fncli/backend.py` return what exists and never update it. Change `TEST_RESULTS_TARGET_DIR` and re-run `setup-project`: the log says "Reusing existing", nothing changes. The only way to know what a run will do is to read the code.

## 2. The file

One YAML file describes a node's desired state. It holds **no secret values**, so it can be committed. Keys are the backend's own unique fields, so there are no ids: provider uri, repository uri, secret label, dataset name, project name.

```yaml
version: 1

providers:
  - name: gitea-local                      # optional, default <type>-<host>
    type: gitea
    uri: http://gitea.fn.svc:4000          # as the node sees it, not the port-forward
    api_uri: http://gitea.fn.svc:4000/api/v1
  - type: github
    uri: https://github.com                # api_uri defaults to https://api.github.com

# Each value says where fncli reads it at apply time. Never inline.
secrets:
  demo-gitea-trigger-creds:
    gitea_oauth: {app: demo-sensor}        # fncli creates and authorises the OAuth app (needs `gitea:` below)
  demo-gitea-results-creds:
    gitea_oauth: {app: demo-results}
  phems-sandbox-creds:                     # shared by the GitHub trigger and results repositories
    values:
      APP_ID:          {env: GH_APP_ID}
      INSTALLATION_ID: {env: GH_INSTALLATION_ID}
      PRIVATE_KEY:     {file: ~/.config/phems/phems-sandbox.private-key.pem}
  shared-dataset-creds:
    values:
      USERNAME: {env: DATASET_USERNAME}
      PASSWORD: {k8s_secret: {name: db-datasets-uc1, namespace: experiments, key: password}}

# Global resources. The provider is found from the uri's host.
trigger_repositories:
  - {uri: "http://gitea.fn.svc:4000/gitea_admin/demo-trigger-repo", secret: demo-gitea-trigger-creds}
  - {uri: "https://github.com/Aridhia-Open-Source/phems-sandbox",   secret: phems-sandbox-creds}
results_repositories:
  - {uri: "http://gitea.fn.svc:4000/gitea_admin/demo-results-repo", secret: demo-gitea-results-creds}
  - {uri: "https://github.com/Aridhia-Open-Source/phems-sandbox",   secret: phems-sandbox-creds}
datasets:
  - name: shared-dataset                   # unique across the node
    type: postgres
    host: db-datasets.experiments.svc
    port: 5432
    read_schema: cdm
    write_schema: results
    secret: shared-dataset-creds

# Projects hold only assignments of the globals above.
projects:
  - name: demo-gitea
    enabled: true                          # default true; apply creates it disabled and enables it last
    datasets: [shared-dataset]             # list order matters: the first becomes the project's default
    triggers:                              # any number
      - repository: http://gitea.fn.svc:4000/gitea_admin/demo-trigger-repo
        watch_dir: specs/
        base_branch: main                  # required, never guessed
    results:                               # exactly one: the backend allows one per project
      repository: http://gitea.fn.svc:4000/gitea_admin/demo-results-repo
      target_dir: results/
      base_branch: main
  - name: demo-github
    datasets: [shared-dataset]             # the same dataset, a second assignment
    triggers:
      - {repository: "https://github.com/Aridhia-Open-Source/phems-sandbox", watch_dir: mgmt/requests/, base_branch: main}
    results:
      repository: https://github.com/Aridhia-Open-Source/phems-sandbox
      target_dir: mgmt/results/
      base_branch: main

# Opt-in Gitea admin bootstrap. Absent means fncli never touches Gitea, as for GitHub.
gitea:
  provider: gitea-local
  create_repositories: true                # the repos above on this provider, under the admin user
```

Notes on the format:

- **Gitea vs GitHub is data.** Provider `type`, the secret's source, and the optional `gitea:` section. The properties in `RepoConfig` are derived from the provider and the uri.
- **Assignments take `enabled`** (default true), per trigger and for `results`. It is always sent, see section 3.
- **Gitea host-side addresses stay in env.** `GITEA_URL`, `GITEA_ADMIN_USER`, `NAMESPACE` and `NEXUS_API_URL` are how this machine reaches the cluster. The file says how the node sees things, and `to_host_url` still translates.
- **Secret sources:** `env`, `file` (`~` and paths relative to the node file), `k8s_secret`, `gitea_oauth` (bootstrap only), and `generate` (proposed: a random value, for stand-in dataset credentials only, replacing today's `dummy/dummy` defaults).
- **Checked before any API call:**
  - every repository has a provider for its host;
  - exactly one `results` per project;
  - `base_branch` is set and `watch_dir` is not empty;
  - `api_uri` is on the provider's host (`validate_api_uri`);
  - a Gitea repo's owner is the admin user (what `load_repo_config` enforces today);
  - Gitea OAuth app names are unique (Gitea tells them apart by name);
  - within the file, a trigger `watch_dir` does not overlap a results `target_dir` on the same repo.

  The backend's overlap check covers every project on the node, so it stays the final judge.
- **References may point outside the file.** A project's datasets and repositories, and a repository's or dataset's secret, can be listed in the file or already be on the node (a dataset made by another file, say an experiment's `bootstrap.yaml`). The diff resolves them against the backend: one on the node shows as an unchanged row "on the node, not in this file", one in neither blocks the row that names it (the project, repository or dataset), and apply leaves a blocked row alone. `delete` still only deletes what the file lists.

## 3. Commands, and what they reuse

| Command | What it does | Reused | New |
|---|---|---|---|
| `fncli diff -f node.yaml [--project P]` | Read-only. Resolves references (reports "env GH_APP_ID: set", never a value), reads the backend, prints the difference. | `build_backend_api`, the `find_*` and `get_*` calls of `FncliBackendAPI` | File schema and loader, the diff (a pure module like `simulation.py`), the printer |
| `fncli apply -f node.yaml [--project P] [-y] [--only PHASE] [--rotate LABEL]` | Prints the plan, asks, executes, then verifies. | `create_*`, `upsert_secret`, `GiteaAdminAPI.get_or_create_repo` and `authorize_oauth_app`, `verify_git_secret`, project healthcheck | `update_*` calls on `FncliBackendAPI`, the executor, the disable and enable step |
| `fncli delete -f node.yaml [--all] [-y]` | Soft-deletes the file's projects (their assignments go with them) through the DELETE routes, never with `?force=true`. With `--all`, then the global repositories and datasets, secrets and providers, in that order. What a project outside the file still uses is a 409: skipped with the backend's message, exit 1. Gitea repositories and OAuth apps are left. | `delete_project`, `delete_secret`, `delete_git_provider` | `force=False` on the repository and dataset deletes, the reverse-order executor |
| `fncli open-pr`, `merge-gitea-pr`, `merge-results-pr`, `verify-*`, ... `--project P [--repository URI]` | Read the repo, branch and directories from the project's assignments in the backend. No file. `--repository` is needed only when the project has more than one trigger assignment; otherwise the only one is used. | `load_repo_config(from_backend=True)`, `get_pr_base_branch`, `build_researcher_git_api` | `--project` means "from the backend" everywhere; `PrConfig` stops requiring `TEST_TRIGGER_*` |
| `fncli demo -f demo.yaml --project P` | The same guided walk. | The `Step` table, `wait_for_state`, the `show_*` helpers | Setup steps become `apply --only <phase>`; step text is filled from the file |
| `fncli node-file --from-env` | Prints the current env as a node file. | The config classes | Small renderer, also the migration check |

**Where the code pushes back on the proposal:**

- **The `init-*` steps are not the engine.** They are click commands bound to the env config classes, and the `get_or_*` helpers only reuse. Apply reuses the layer below them (`FncliBackendAPI`, `GiteaAdminAPI`) and adds create-or-update with a diff in front.
- **Identity decides create vs update.** A repository's `uri` can't be patched (its PATCH takes provider, secret, enabled, revoked). A changed uri is a new repository, not an update.
- **Compare normalised forms** (`normalise_repo_uri`, `normalise_provider_uri`, lowercase dataset names), or the plan shows false differences.
- **Phases** run in dependency order: `gitea` (repos), `secrets`, `providers`, `repositories`, `datasets`, `projects` (created disabled, assignments in), `enable`, then verify. `--only` runs one, which is what the demo's steps call.

**Reach of `--project`.** `apply --project P` covers the project plus the globals it references. Datasets, repositories and secrets are shared, so a change to one can fail another project's earlier tasks (for example `shared-dataset` for `demo-gitea` when applying `demo-github`). The plan lists every project assigned to a changed global, taken from the backend's assignments, not from the file, because projects outside the file may use it too.

**Assignments, and a gotcha.** The backend's assignment PUT is an upsert, but it resets what the body omits: `enabled` goes back to true, and on the results repository `owned_by_federated_node` too. So a naive re-apply would re-enable something switched off with `resource-set`. Apply creates an assignment with PUT, always sending `enabled` from the file, and updates an existing one with PATCH of only the fields the plan shows as changed. Unchanged assignments are not touched.

**Disruptive changes, marked in the plan:**

- A dataset's host, port, type or schemas, and a results repository's `target_dir` or `base_branch`, are pinned into every task when it is created (`nexus/api/app/helpers/task_config.py`). Tasks created earlier fail instead of running against the new setup. A trigger `watch_dir` or `base_branch` applies at once and leaves work in flight alone.
- A project has one results repository, and creating its assignment needs the project disabled. On a live project, apply disables it, assigns, and enables it again. Enabling skips the gap: pull requests merged meanwhile get no trigger. The plan says so and apply asks first.
- Swapping a project's results repository for another is a 409 in the backend. Plan reports it as blocked with the manual steps. Apply does not automate it.

Plan output, roughly:

```
Node http://localhost:5000, kubectl context kind-fn

  + provider        gitea-local
  + gitea repo      gitea_admin/demo-trigger-repo
  + secret          demo-gitea-trigger-creds    gitea OAuth app demo-sensor
  = secret          phems-sandbox-creds         exists, values not compared
  ~ results repo    .../phems-sandbox           secret: a-creds -> phems-sandbox-creds
  ~ project         demo-github                 results.target_dir: results/ -> mgmt/results/   (earlier tasks will fail)
  ! project         demo-live                   disable and enable needed to assign its results repository

Plan (excerpt): 3 to create, 2 to change, 1 needs a confirmation, 1 unchanged. Nothing is deleted.
```

`apply` shows the node URL and kubectl context first, because fncli reads cluster secrets from whatever context is current.

## 4. Secrets

- **A reference is where fncli reads a value at apply time, not a pointer the backend follows.** nexus-api keeps its own copy (provider `K8S` only, stored as `fn-secret-<label>`), a create needs the values, and no read returns values or even key names. That includes a `k8s_secret` reference: fncli reads it with the kubeconfig and writes it to nexus-api.
- **So secrets can't be diffed.** The plan can say "exists" and "enabled", never "changed".
- **Create-only by default.** Apply creates a missing secret and leaves an existing one alone. `--rotate LABEL` rewrites it. A rewrite replaces all keys, so cached git tokens are dropped, which is intended.
- **Gitea OAuth must never run on every apply.** Re-authorising rotates the application's client secret and refresh token. It runs only for a missing secret or `--rotate`.
- **Never printed.** Logs and plan show the source (`env GH_APP_ID`) and the key names, never values. The schema rejects a bare string where a reference is expected.
- **Env files still hold secrets.** `--env-file` keeps loading before the file is read, so `GH_*` can live in an ignored env file and the node file is safe to commit. `RESEARCHER_GIT_TOKEN` stays env: it is a person's credential, not node state.
- **Login is unchanged.** Apply uses the Dagster system user, as setup does today. Revoking stays in `resource-set` and `global-set`, which need the first Keycloak admin. The file never sets `revoked`.

## 5. Migration

Keep the env vars working, frozen: no new `TEST_*` variables, no new features on that path. Reasons, all in the repo today:

- The e2e suite imports `SETUP_STEPS` and `TEARDOWN_STEPS`.
- `scripts/e2e_check.py` builds `ProjectConfig`.
- `fncli experiment` reads `experiments/projects/*/project.env` (it now holds only the settings of `build` and `run`; the dataset is in `bootstrap.yaml` next to it).
- Teardown (`teardown-project`, the demo's last step) has a file-based form in `fncli delete` only once the demo and the e2e suite move to files.

Then:

1. `.dev.env` shrinks to cluster addresses and auth: `NEXUS_API_URL`, `KEYCLOAK_NAMESPACE`, `NAMESPACE`, `GITEA_URL`, `GITEA_ADMIN_USER`, `DAGSTER_URL`, plus `GH_*` and `RESEARCHER_GIT_TOKEN` when a file references them. All `TEST_*`, `GITEA_API_URI`, the token names, `DEFAULT_PROJECT_DATASET` and `DATASET_*` move into the file. `TEST_PR_IMAGE`, `TEST_PR_ENV`, `TEST_PR_TAGS` and `TEST_PR_CONFIG` are per-pull-request inputs, not node state, so they stay as options with env defaults.
2. `.demo.env.example` and `.demo-github.env.example` become `bootstrap/examples/demo-gitea.yaml` and `bootstrap/examples/demo-github.yaml`.
3. `fncli node-file --from-env` renders a current env as a file.
4. The e2e fixtures and the experiments move to files later, and only then is the env path deleted.

`SETUP_GIT_APPS.md` and the fncli README get the file as the documented path, and the env path is described once as legacy.

ADR 0018 says fncli is not a product interface. Scope `diff`, `apply` and `delete` the same way: dev and demo clusters, with the confirmation above. Using it on a beta node would need an amendment to the ADR, as a separate decision.

## 6. Out of scope, later

- **Prune and destroy.** Deleting what the file no longer lists needs an ownership rule, and the backend has no owner or label field. Later, prefer explicit `state: absent` entries over "everything not in the file". `fncli delete -f` (with `--all` for the globals) is the first version of that, replacing `teardown-project`; it leaves Gitea alone and still takes only what the file lists.
- **Multi-node.** One file is one node. The target is the env and kubectl context, not a key in the file.
- **Results branch in the task snapshot.** `base_branch` is going into the snapshot in `task_config.py`. Later: plan previews which in-flight tasks a change would fail (the snapshot diff already exists), and an e2e for a `base_branch` change.
- **Secret value drift, project secret assignments** (`/projects/<id>/secrets`, which fncli never sets), `revoked` and the global `enabled` flags. `secret-set`, `global-set` and `resource-set` stay as the imperative tools.
- **Creating GitHub repos or Apps, a JSON schema for editors, the Gitea mirror.** Not fncli's job, or separate.

## 7. Rough effort

About 11 working days with agent help. The first useful slice is the first three rows, about 5.5 days, and it sets up a GitHub project with no Gitea.

| Piece | Days |
|---|---|
| Schema (pydantic, no extra keys), loader, reference resolution, `pyyaml` added to the `cli` extra in `dagster/pyproject.toml`, the pre-API checks | 1.5 |
| Backend read model, the pure diff, the plan printer | 2 |
| Apply: `update_*` calls, executor and phase order, PUT-create and PATCH-update, disable and enable step, confirmation, verify and healthcheck, `--only`, `--rotate` | 2 |
| Tests for those: diff unit tests, loader, apply against a fake backend | (in the above) |
| Gitea `gitea:` section wrapping `get_or_create_repo` and `authorize_oauth_app` | 0.5 |
| `--project` from the backend for the PR, merge and verify commands | 1 |
| Demo on files, example files | 1 |
| `node-file --from-env`, README, `SETUP_GIT_APPS.md`, slimmer `.dev.env.example` | 1 |
| One e2e through `apply` on the kind cluster, and a rerun that changes nothing | 2 |

## 8. Open questions

1. Commit `demo-gitea.yaml` and `demo-github.yaml` in `bootstrap/examples/` (they hold no secrets), replacing the two `.demo*.env.example` files? Recommend yes.
2. Always an explicit `-f` (or `FNCLI_NODE_FILE`), no upward search like `.dev.env`? Recommend explicit, so a stray file can't be applied to the wrong node.
3. New results repository on a live project: disable and enable automatically after a confirmation, or refuse? Recommend the confirmation.
4. `fncli delete -f` (built) replaces `teardown-project` in the demo and the e2e suite once they run from files. Recommend yes.
5. Add the `generate` secret source for stand-in dataset credentials? Recommend yes, noted as dev only.
