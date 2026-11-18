# 0033. Configure a node with fncli config files

Status: Proposed, 2026-11-13. Revised 2026-11-17.

## Context

- **fncli is the dev and ops CLI** ([0018](0018-fncli-dev-ops-tool.md)). It sets a node up, drives the pull request process, and breaks things on purpose for QA.
- **Node config today comes from bootstrap files.** `diff`, `apply` and `delete` read the provider, secret, repository, dataset and project files and call nexus-api directly ([0025](0025-fncli-bootstrap-files-diff-apply-delete.md), [0026](0026-apply-is-additive-delete-is-a-soft-delete.md), [0027](0027-bootstrap-files-split-by-stage-of-use.md)). They replaced the env-driven `setup-*` and `teardown-*` commands.
- **Several flows depend on it.** `fncli experiment setup` applies the experiment's files, the end-to-end suites apply their own, and `fncli demo` starts from the plan `diff` prints ([0030](0030-fncli-demo-only-walks-the-pull-request-process.md)).
- **The target is an operator.** Node config becomes custom resources that an operator syncs to nexus-api, in dev and on a deployed node ([0032](0032-declarative-node-config-through-an-operator.md)). It is not on this branch yet.

## Decision

### What fncli does now

- **Node config:** `diff`, `apply` and `delete` of bootstrap files. `apply` is additive; `delete` is a soft delete through nexus-api.
- **Records:** the `project-*` and `*-set` commands read and change single records, and the checks verify a node.
- **The pull request process:** `trigger`, `demo`, the sensor commands and `merge-results-pr`.
- **Experiments:** the `experiment` commands (`up`, `build`, `seed`, `setup`, `run`, `teardown`, `down`, [0028](0028-experiments-own-their-database-seed-image-and-dataset-file.md)).
- **QA:** the breakage commands (`simulate`).
- **Gitea setup:** repositories, OAuth apps and tokens, in dev only.

### What the operator replaces

- **Applying node config moves to the operator** once it runs in dev ([0032](0032-declarative-node-config-through-an-operator.md)). `diff`, `apply` and `delete` become `kubectl diff`, `kubectl apply` and `kubectl delete` on the custom resource files in dev, and Helm on a node.
- **Records the operator owns are changed through their custom resource,** not `*-set`.
- **Everything else stays in fncli:** the pull request process, experiments, the QA commands, checks, and Gitea setup, which the operator never does.
- **Until then, `apply` stays small.** Fixes, yes. No ownership tags, state store, prune or drift repair: that is the operator's work.
- **The bootstrap files keep the fields of the custom resources** (in snake_case), so moving a file is a translation, not a redesign.
- **The commands go in one change,** with their callers: `experiment setup`, the end-to-end suites and the demo's check that the node matches.

## Consequences

- **fncli is how a node is set up today,** and its files, experiments, e2e and demo flows are the shape the custom resource files take later.
- **fncli stays, with a smaller job,** once the operator lands.
- **The docs change twice:** the wiki, `FRESH_SETUP.md` and the READMEs describe `apply` now, and `kubectl apply` after.

## Alternatives considered

- **Remove `apply` now and wait for the operator:** dev has no way to set a node up meanwhile, and the demo and e2e suites stop working.
- **Keep `apply` for good, beside the operator:** two engines for the same config, and dev no longer runs the path a site runs.
- **Grow `apply` to cover removal and drift, and drop the operator:** the ownership tags and state store [0032](0032-declarative-node-config-through-an-operator.md) rejects, and nothing for a deployed node.
