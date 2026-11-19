# 0027. Bootstrap files are split by stage of use, and the context is separate

Status: Accepted, 2026-11-09.

## Context

The first bootstrap files ([0025](0025-fncli-bootstrap-files-diff-apply-delete.md)) were one file per scenario, each with its own `node:` block (nexus-api url, kubectl context, Keycloak namespace, env file). That repeated things and tied them together.
- Pointing at another cluster meant editing every file.
- The second-project file for the e2e suite repeated about 35 lines of globals, and a name that differed between files would rename the entity for the others.
- A file said what to configure and where, but the same content is applied to different nodes by different people.

## Decision

The files are split by who writes them and when, and the node is chosen apart from the content, in a context file.

| Path | Holds | Committed |
|---|---|---|
| `bootstrap/context.yaml` | the `node` (nexus-api `url`, `kube_context`, `keycloak_namespace`, `env_file`, optional `gitea_admin_user`) and `defaults` (`project`, `trigger_type`) | no (gitignored); `bootstrap/examples/context.yaml` is |
| `bootstrap/globals*.yaml` | the global resources: providers, repositories, secrets | yes |
| `bootstrap/projects/<p>.yaml` | one project's assignments of the globals | yes |
| `requests/<p>/*.json` | the request files a researcher commits in a pull request to the trigger repository | yes |

- **The node is per user and cluster, not per file.** A command reads `bootstrap/context.yaml` (`--context FILE` or `FNCLI_CONTEXT` names another); a content file never names a node. fncli looks for the file from the current directory up, so it works from any folder of the repo.
- **Every command refuses to run when kubectl's current context differs from the context file's `node.kube_context`,** because fncli reads cluster secrets from the current context. The context file is the one authority for the target.
- **The context file also holds `defaults`,** what a command uses when not told: `defaults.project` and `defaults.trigger_type` (`pr` or `api`), used by `fncli trigger` and `fncli demo`. The env vars `FNCLI_DEFAULT_PROJECT` and `FNCLI_DEFAULT_TRIGGER_TYPE` override the file, and a CLI flag (`--project`, `--pr`, `--api`) wins over both. A command that takes a default says so on its first line.
- **References across files resolve against the node.** A project may name a repository, dataset or secret that is in another file, as long as it is on the node when `diff` reads it. `diff` shows it as "on the node, not in this file". One that is in neither blocks the row that names it ("not in the file or on the node"), and `apply` leaves that row alone.
- **Datasets sit with their experiment** ([0028](0028-experiments-own-their-database-seed-image-and-dataset-file.md)), not in `globals*.yaml`.
- **The order of use is the order of the files:** `context.yaml`, then globals, then projects; `requests/` is used after the project is applied.

## Consequences

- Switching clusters is one file, and the usual project is set once instead of on every command. The same globals and project files serve the demo, the e2e suites and a person's own node.
- A project file shrinks to the project and its assignments, and the e2e second-project file drops its repeated globals.
- A project file applied before the globals it names does not fail half way: its rows are blocked and apply creates nothing for them.
- `context.yaml` cannot be committed by accident; a stray content file cannot be applied to the wrong node, because it names none.
- One more file to create on a new machine, from the example.

## Alternatives considered

- **A `node:` block in every file (the first version):** switching cluster meant editing every file, and the copies could differ.
- **The first split, a `node.yaml` with the target only:** the defaults then had nowhere to live except env vars or flags on every command; the context file holds both.
- **A folder per node, with the files copied into it:** the files describe content, not a node, so each node's copy would repeat and drift.
- **The node as a key to choose between several in one file:** one file is one node; the target is the machine's environment, not content.
- **Keep one big file per scenario:** repeats the globals in every file that needs them.
