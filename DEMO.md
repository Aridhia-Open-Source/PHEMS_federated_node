# Demo: from a fresh cluster to a results pull request

How to set up and run the demo once the node is deployed (`make deploy` done). For everything before that (tools, config, cluster), see [FRESH_SETUP.md](FRESH_SETUP.md).

The flow: register the demo database, apply the shared resources, apply the project, then run the demo as often as you like. `fncli demo` creates nothing: it checks the node matches the files, then walks one pull request through task and results.

## 0. Once per machine

Run from the repo root.

```bash
pipx install --force -e "$PWD/dagster[cli]"                  # fncli from this checkout
cp bootstrap/examples/context.yaml bootstrap/context.yaml    # your node and defaults (gitignored)
```

In `bootstrap/context.yaml`, set `defaults.project` to the demo you run: `demo-gitea` or `demo-github`.

## 1. Start the node's moving parts

```bash
tilt up --stream                    # own terminal: port-forwards, nexus-api on :5000, Gitea on :4000
fncli start-sensor --group all      # the sensors start stopped
```

If `start-sensor` says a sensor is not found, Dagster is still loading its code: wait a minute and run it again.

## 2. The demo database

```bash
make experiments deploy                 # the experiments release: demo-db, its role and secret
fncli experiment seed demo          # cdm.person with three rows, and an empty results schema
fncli apply -f experiments/demo/dataset.yaml      # registers demo-db with the node
```

## 3a. Gitea demo

Everything lives in the cluster's Gitea, so nothing outside is needed.

```bash
fncli diff  -f examples/globals-gitea.yaml          # preview: the provider, the two repos, their OAuth secrets
fncli apply -f examples/globals-gitea.yaml          # creates them, the Gitea repos included
fncli apply -f examples/projects/demo-gitea.yaml    # the project and its assignments (uses demo-db)
fncli demo -f examples/projects/demo-gitea.yaml     # the guided pull request walk
```

## 3b. GitHub demo

Needs a GitHub App installed on your repo ([SETUP_GIT_APPS.md](SETUP_GIT_APPS.md)): its key at the path the globals file names, and `GH_APP_ID` and `GH_INSTALLATION_ID` in the context's `env_file` (`.dev.env`). For your own repo, copy the two example files to `bootstrap/globals.yaml` and `bootstrap/projects/<name>.yaml` and change the repo, the secret label and the key path.

```bash
fncli diff  -f examples/globals-github.yaml
fncli apply -f examples/globals-github.yaml
fncli apply -f examples/projects/demo-github.yaml
fncli demo -f examples/projects/demo-github.yaml    # with defaults.project: demo-github
```

- Run `fncli demo -f examples/projects/demo-gitea.yaml` again for another pull request; nothing needs resetting.
- `fncli demo -f examples/projects/demo-gitea.yaml examples/demo-failing.json` makes the task fail on purpose, to see the failure path.
- Without the guided checks: `fncli trigger --pr examples/demo.json` opens the pull request directly.
- A different project or route than the context's defaults: `--project NAME`, `--pr`.

## Clean up

```bash
fncli delete -f examples/projects/demo-gitea.yaml          # the project only
fncli delete -f examples/globals-gitea.yaml --all          # also the shared repos, secrets and provider
```

Delete is a soft delete, and it skips anything another project still uses. The Gitea repos and OAuth apps stay in Gitea.

## When something fails

| Symptom | Fix |
|---|---|
| `No such command 'diff'` (or `trigger`) | fncli points at another checkout: rerun the `pipx install` above |
| `is for kubectl context X, but the current one is Y` | `kubectl config use-context kind-fn` |
| `demo` lists rows and says run apply first | run the `fncli apply` lines for that demo again |
| `dataset demo-db is not in the file or on the node` | step 2 was skipped |
| the dataset login check fails | `fncli experiment seed demo`, then check `kubectl get pods -n experiments` |
