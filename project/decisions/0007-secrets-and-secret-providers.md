# 0007. Generic Secret model and SecretProvider; per-repository tokens

## Context

Dataset credentials and git tokens must not live in the database or in a single environment variable shared by every repository. A credential is shared by every project that uses the resource it belongs to ([0006](0006-global-resources-and-project-links.md)).

## Decision

- `secrets` holds a **reference**, not a value: `label` (unique across the node, addressable in the API), `description`, `provider` (enum, currently `K8S`), `key` (the generated, immutable name in the store, `fn-secret-<label>`, unique) and `namespace`. The value lives only in the store.
- `POST /global/secrets` takes `values` and sends them to the store; they are never returned. Secrets are global and addressed by label; repositories and datasets name theirs with `secret_label`. A project can be linked to a secret (`project_secrets`), but no rule reads that link.
- Dataset credentials (`secret_id`) and the trigger and results repositories point at secrets. Git tokens are read under the key `TOKEN`.
- Dagster reads a value through `SecretProvider(provider).get(key, namespace, value_key)`; `K8sSecretProvider` reads the Kubernetes secret. A secret that is disabled is never read. A new store is a new entry in `SecretProvider.PROVIDERS` and the matching backend writer.
- `GitAPIFactory.for_repository` reads the repository's own token each time it builds a client ([0010](0010-git-api-protocol-and-factory.md)); the delivery push reads the results repository's token the same way.
- Disabling a secret also disables the datasets and repositories that use it, and moves its value to a quarantine namespace; the details are in [revoke-and-enabled.md](../../docs/architecture/revoke-and-enabled.md#secrets). A repository or dataset that references a disabled secret is refused with 400 on create and patch.

## Consequences

- Each repository authenticates as itself; tokens can be scoped (`read:repository` for a trigger repository, `write:repository` for a results repository in fncli).
- A secret in use cannot be deleted (`RESTRICT` foreign keys; `?force=true` disables its users first).
- Credentials are outside the task's pinned configuration, so a rotation reaches running work ([0009](0009-task-pinned-to-its-configuration.md)).
- Reading the token uses the node's own Kubernetes access; this is marked `TODO(auth)` pending the authorization rework ([0017](0017-authorization-detached-from-dar-and-keycloak.md)).

## Alternatives considered

- **One global `GH_TOKEN`:** one token for all projects and repositories.
- **Encrypted values in the database:** Kubernetes already is the store.
- **Derive the secret from the repository uri:** repositories may share a credential.
