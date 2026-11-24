# Plan: fncli into fednode (fednode/3, #766)

Status: not started.
- Move `dagster/fncli` to `fednode/cli` (subpackage). Keep commands and behaviour.
- CLI-only deps (click etc.) as an optional extra: `[project.optional-dependencies] cli = [...]`; entry point
  `fncli = "fednode.cli:main"`. Services install plain `fednode`; dev machines and CI install `fednode[cli]`.
- fncli uses the shared clients (nexus, dagster, kubernetes in kubeconfig mode, gitea). Its config stays its context files.
- Update mise tasks, docs (`dagster/fncli/README.md` moves), e2e suite paths, `mise run doctor`.
