# 0004. Generic Secret model and SecretProvider; per-repository tokens

- Status: Accepted (the `GH_TOKEN` leftovers are a known follow-up)

## Context

Dataset credentials and git tokens must not live in the database or in a single environment variable shared by every repository.

## Decision

- `secrets` holds a **reference**: `project_id`, `label` (local to the project, renameable), `provider` (enum, currently `K8S`), `key` (the generated, immutable name in the store, globally unique) and `namespace`. The value lives only in the store.
- `POST /projects/<id>/secrets` takes `values` and sends them to the store; they are never returned.
- Dataset credentials (`secret_id`) and the git repositories ([0003](0003-project-scoped-git-repositories.md)) point at secrets. Git tokens are read under the key `TOKEN`.
- Dagster reads a value through `SecretProvider(provider).get(key, namespace, value_key)`; `K8sSecretProvider` reads the Kubernetes secret. A new store is a new entry in `SecretProvider.PROVIDERS` and the matching backend writer.
- `GitAPIFactory.for_repository` reads the repository's own token each time it builds a client ([0005](0005-git-api-protocol-and-factory.md)); the delivery push reads the results repository's token the same way.

## Consequences

- Each repository authenticates as itself; tokens can be scoped (`read:repository` for trigger, `write:repository` for results in fncli).
- A secret in use cannot be deleted (RESTRICT foreign keys).
- Leftover: `GH_TOKEN`/`GITEA_TOKEN` config classes, the `github-token` chart secret and `GH_*` chart values remain although the sensors no longer use them.
- Reading the token still uses the node's own Kubernetes access; this is marked `TODO(auth)` pending the authorization rework ([0014](0014-dar-rename-and-detached-auth.md)).

## Alternatives considered

- **Global `GH_TOKEN`**: rejected, one token for all projects and repositories.
- **Encrypted values in the database**: rejected, Kubernetes already is the store.
