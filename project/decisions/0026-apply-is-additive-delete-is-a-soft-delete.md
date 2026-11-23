# 0026. Apply is additive; delete is a soft delete through nexus-api

Status: Accepted, 2026-11-09.

## Context

`apply` ([0025](0025-fncli-bootstrap-files-diff-apply-delete.md)) runs against a node that other files, other projects and other people also use. The backend has no owner or label field that says which file made a record, so fncli cannot tell "removed from this file" from "belongs to someone else". Deletes in nexus-api are soft ([0008](0008-enabled-revoked-and-soft-delete.md)): `deleted_at` is set, the row is hidden, and a global resource that a project still uses is refused with a 409 unless `?force=true`, which revokes and deletes every project's resource for it.

## Decision

- **`apply` only creates and updates.** It never deletes. Taking an entry out of a file changes nothing on the node. A later prune would use explicit `state: absent` entries, not "everything the file does not list".
- **`delete` soft-deletes through nexus-api's DELETE routes, never with `?force=true`.** It works in the reverse of apply's order: what uses a thing goes before the thing.
  - By default: the file's projects, which take their assignments with them.
  - With `--all`: then the file's repositories and datasets, its secrets (with their stored values) and its providers, as far as the node has them.
- **A 409 is skipped and reported.** A global resource that a project outside the file still uses is refused by the backend; delete prints the backend's message and the projects it names, goes on with the rest, and exits 1.
- **A provider that repositories outside the file are on is kept** and shown as an unchanged row. That is not an error and does not change the exit code.
- **Gitea repositories and OAuth apps are left alone.** They hold commits and pull requests that a mistake would lose, and fncli never creates or deletes GitHub repositories.

## Consequences

- `delete` is safe to run against a shared node: it cannot take another project's resources with it, and what it cannot remove it names.
- The order of teardown matters when projects share globals: delete the second project's file first, then the first with `--all`, or the shared repositories and dataset are refused.
- Applying a file again after `delete` recreates everything cleanly: the unique names, labels and `(provider_id, repo_path)` pairs are partial indexes on `deleted_at IS NULL` ([0008](0008-enabled-revoked-and-soft-delete.md)), so a deleted name is free again.
- Audit history stays: the soft-deleted rows are still there for the tasks, triggers and results that reference them.
- After `delete --all` the Gitea side is cleaned by hand; apply on a fresh node finds the repositories and reuses them.

## Alternatives considered

- **Hard delete:** it would break the foreign keys from tasks, triggers and results and lose the record of what produced a result.
- **`?force=true` for everything:** it silently revokes and deletes other projects' resources.
- **Prune on apply, deleting what the file no longer lists:** with no owner field it could remove another file's work or a person's hand-made records.
- **Delete the Gitea repositories and OAuth apps too:** a repository with commits would be lost on a mistyped `--all`; removing them is a separate, explicit decision.
