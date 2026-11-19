# 0025. fncli configures a node from bootstrap files: diff, apply, delete

Status: Accepted, 2026-11-09.

## Context

Setting up a dev node meant about 22 fncli commands (6 group commands such as `setup-project` and `teardown-project`, 16 step commands such as `init-backend-trigger-repo` and `delete-secret`), all driven by about 30 `TEST_*` variables in an env file. That has four problems.
- One env file describes one project. A second project needs a second file and `--env-file` juggling, and the layers (`.dev.env`, a `.demo*.env`, the shell) each override differently.
- The names carry the model. A secret's label is derived from a repository name, so two entities share one label by accident of naming.
- Secret values sit beside addresses, and the GitHub App key is exported from `$(cat key.pem)` in a shell.
- There is no preview and no update. The `get_or_create_*` calls return what exists and never change it: edit `TEST_RESULTS_TARGET_DIR`, re-run, and the log says "Reusing existing" while nothing changes.

## Decision

fncli reads **bootstrap files** (YAML) that describe the desired state of a node, and offers three commands in the style of kubectl. The commands replace the setup and teardown group and step commands ([0018](0018-fncli-dev-ops-tool.md)). `delete-gitea-token` stays, for the QA failure scenarios.

| Command | What it does |
|---|---|
| `fncli diff -f FILE` | Reads the file and the node and prints one row per entity: create, change, unchanged, needs a confirmation, blocked. Changes nothing. |
| `fncli apply -f FILE [--rotate LABEL] [-y]` | Prints that plan, asks, then does it in dependency order (secrets, providers, repositories, datasets, projects) and verifies. A project is created disabled and enabled last. |
| `fncli delete -f FILE [--all] [-y]` | Removes what the file lists ([0026](0026-apply-is-additive-delete-is-a-soft-delete.md)). |

- **The keys are the backend's own unique fields,** so a file holds no ids: provider uri, repository uri, secret label, dataset name, project name. Values are compared in their normalised form, or the plan would show false differences.
- **No secret value is ever in a file.** Each value names where fncli reads it at apply time: `env`, `file`, `k8s_secret`, `gitea_oauth` (fncli makes and authorises an OAuth app in Gitea) or `generate` (a random value, for stand-in dataset credentials only). A bare string where a reference is expected is rejected. A file is safe to commit; plan and logs show the source and the key names, never a value.
- **A reference is where fncli reads a value, not a pointer nexus-api follows.** nexus-api keeps its own copy of a secret ([0007](0007-secrets-and-secret-providers.md)) and no read returns values or key names. So a secret can show as "exists", never as "changed".
- **Secrets are create-only.** An existing secret is left alone; `--rotate LABEL` rewrites all its keys, which drops the cached git tokens ([0024](0024-github-app-tokens-minted-by-the-backend.md)). A Gitea OAuth app is authorised only for a missing secret or with `--rotate`, because authorising again replaces the app's client secret and refresh token.
- **An assignment is PUT once, then PATCHed with only the fields that differ.** The backend's PUT is an upsert that resets what the body omits: `enabled` goes back to true, and on a results assignment so does `owned_by_federated_node`. A repeated apply must not re-enable what was switched off with `resource-set`, so it always sends `enabled` on a PUT and never PUTs an assignment that exists.
- **The plan marks disruptive changes.** A dataset's host, port, type or schemas, and a results repository's `target_dir` or `base_branch`, are pinned into every task when it is created ([0009](0009-task-pinned-to-its-configuration.md)), so earlier tasks fail. Assigning a project's results repository needs the project disabled, so apply asks first.
- **Login and flags are unchanged.** Apply acts as the Dagster system user. `revoked`, a global `enabled` and a secret's `enabled` stay with `resource-set`, `global-set` and `secret-set`; a file never sets `revoked`.
- **Still dev and demo tooling** ([0018](0018-fncli-dev-ops-tool.md)). Using these commands on a beta node would need a separate decision.

## Consequences

- One file can describe several projects and be applied again after an edit: a changed `target_dir` or `watch_dir` now reaches the node.
- `diff` shows what a run will do before it runs, and a second `apply` of an unchanged file changes nothing.
- Setup is data, not code: Gitea or GitHub is a provider `type` and a secret source, not a pile of derived properties.
- A secret that was edited elsewhere (a changed env value, a rotated key) is not noticed until `--rotate`.
- The pull request and verify commands still read their repository and project from `TEST_*` names until they take `--project` and read the node.
- `pyyaml` joins the `cli` extra.

## Alternatives considered

- **Keep the env-driven commands and add features:** the `init-*` steps are click commands bound to the env config classes and only reuse what exists, so an update path and a preview would still be a second engine beside them.
- **Secret values in the file, encrypted:** the file could not be committed and read as is, and fncli would need a key to manage.
- **A reference the backend follows:** nexus-api stores its own copy and a create needs the values, so fncli would read them anyway.
- **Rewrite assignments with PUT every time:** simpler, but it re-enables whatever a person switched off.
- **Authorise the Gitea OAuth app on every apply:** each run would replace the client secret and refresh token, and drop the cached git tokens.
