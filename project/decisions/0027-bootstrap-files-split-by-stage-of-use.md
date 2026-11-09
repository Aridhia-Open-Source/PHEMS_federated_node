# 0027. Bootstrap files are split by stage of use, and the node target is separate

Status: Accepted, 2026-11-09.

## Context

The first bootstrap files ([0025](0025-fncli-bootstrap-files-diff-apply-delete.md)) were one file per scenario, each with its own `node:` block (nexus-api url, kubectl context, Keycloak namespace, env file). That repeated things and tied them together.
- Pointing at another cluster meant editing every file.
- The second-project file for the e2e suite repeated about 35 lines of globals, and a name that differed between files would rename the entity for the others.
- A file said what to configure and where, but the same content is applied to different nodes by different people.

## Decision

The files are split by who writes them and when, and the node is chosen apart from the content.

| Path | Holds | Committed |
|---|---|---|
| `bootstrap/node.yaml` | the target: nexus-api `url`, `kube_context`, `keycloak_namespace`, `env_file` | no (gitignored); examples are |
| `bootstrap/globals*.yaml` | the global resources: providers, repositories, secrets | yes |
| `bootstrap/projects/<p>.yaml` | one project's assignments of the globals | yes |
| `requests/<p>/*.json` | the request files a researcher commits in a pull request to the trigger repository | yes |

- **The node is per user and cluster, not per file.** A command reads `node.yaml`; a content file never names a node.
- **Every command refuses to run when kubectl's current context differs from `node.yaml`'s `kube_context`,** because fncli reads cluster secrets from the current context. The node file is the one authority for the target.
- **References across files resolve against the node.** A project may name a repository, dataset or secret that is in another file, as long as it is on the node when `diff` reads it. `diff` shows it as "on the node, not in this file". One that is in neither blocks the row that names it ("not in the file or on the node"), and `apply` leaves that row alone.
- **Datasets sit with their experiment** ([0028](0028-experiments-own-their-database-seed-image-and-dataset-file.md)), not in `globals*.yaml`.
- **The order of use is the order of the files:** `node.yaml`, then globals, then projects; `requests/` is used after the project is applied.

## Consequences

- Switching clusters is one file. The same globals and project files serve the demo, the e2e suites and a person's own node.
- A project file shrinks to the project and its assignments, and the e2e second-project file drops its repeated globals.
- A project file applied before the globals it names does not fail half way: its rows are blocked and apply creates nothing for them.
- `node.yaml` cannot be committed by accident; a stray content file cannot be applied to the wrong node, because it names none.
- One more file to create on a new machine, from the example.

## Alternatives considered

- **A `node:` block in every file (the first version):** switching cluster meant editing every file, and the copies could differ.
- **A folder per node, with the files copied into it:** the files describe content, not a node, so each node's copy would repeat and drift.
- **The node as a key to choose between several in one file:** one file is one node; the target is the machine's environment, not content.
- **Keep one big file per scenario:** repeats the globals in every file that needs them.
