# 0033. fncli applying node config is temporary, until the operator takes it over

Status: Proposed, 2026-11-13.

## Context

- **fncli sets a node up from bootstrap files today.** `diff`, `apply` and `delete` read the provider, secret, repository, dataset and project files and talk to nexus-api directly ([0025](0025-fncli-bootstrap-files-diff-apply-delete.md), [0026](0026-apply-is-additive-delete-is-a-soft-delete.md), [0027](0027-bootstrap-files-split-by-stage-of-use.md)). They replaced the env-driven `setup-*` and `teardown-*` commands.
- **Several things use it.** `fncli experiment setup` applies the experiment's files, the end-to-end suites apply their own, and `fncli demo` starts from the plan `diff` prints ([0030](0030-fncli-demo-only-walks-the-pull-request-process.md)).
- **The target is different.** Node config is custom resources that an operator syncs to nexus-api, in dev and on a deployed node ([0032](0032-declarative-node-config-through-an-operator.md)). There, fncli no longer applies or diffs it.
- **The operator does not exist yet.** Until it does, dev needs a way to set a node up, and the bootstrap files are it.
- **A tool that works tends to stay and grow.** `apply` is additive and has no ownership tags, state store or prune. Pressure to add them would build a second engine beside the operator, which [0032](0032-declarative-node-config-through-an-operator.md) leaves out on purpose.

## Decision

- **fncli's job of applying node config is temporary.** `diff`, `apply` and `delete` of bootstrap files stay until the operator applies config in dev, and then most of it moves to the operator ([0032](0032-declarative-node-config-through-an-operator.md): `nexus/operator`, Kopf).
- **What moves:** applying and deleting providers, secrets (as references), repositories, datasets and projects, and the preview. In dev that is `kubectl apply`, `kubectl diff` and `kubectl delete` on the custom resource files. On a node it is Helm.
- **What stays in fncli, as a dev and ops tool:** `trigger`, `demo`, the sensor commands, the checks and `project-*` and `*-set` commands, `merge-results-pr`, the `experiment` commands, the QA breakage commands, and the Gitea-only setup (repositories, OAuth apps, tokens), which the operator never does.
- **Until then, `apply` stays small.** Fixes, yes. No ownership tags, state store, prune or drift repair: that is the operator's work.
- **The bootstrap files keep the fields of the custom resources** in [0032](0032-declarative-node-config-through-an-operator.md) (in snake_case), so moving a file is a translation, not a redesign.
- **The commands go in one change, when the operator works in dev.** The callers move with them: `experiment setup`, the end-to-end suites and the demo's check that the node matches.

## Consequences

- **The bootstrap work is not wasted.** It is the way to set a node up now, and its files and the experiment, e2e and demo flows are the shape the custom resource files take later.
- **fncli stays, with a smaller job.** It keeps what the operator does not do: the demo, triggers, sensors, checks, experiments and Gitea setup.
- **The docs change twice:** the wiki, `FRESH_SETUP.md` and the READMEs describe `apply` now, and `kubectl apply` once the operator is there.
- **Nothing here changes what 0032 decides.** This record only says that fncli's `apply` is the stepping stone, and when it goes.

## Alternatives considered

- **Remove `apply` now and wait for the operator:** dev has no way to set a node up in the meantime, and the demo and the end-to-end suites stop working.
- **Keep `apply` for good, beside the operator:** two engines for the same config, and dev no longer runs the path a site runs ([0032](0032-declarative-node-config-through-an-operator.md)).
- **Grow `apply` to cover removal and drift, and drop the operator:** the ownership tags and state store [0032](0032-declarative-node-config-through-an-operator.md) rejects, and nothing for a deployed node.
- **Make `apply` turn the files into custom resources and call kubectl:** a translation layer to keep, when kubectl can read the custom resource files directly once the operator exists.
