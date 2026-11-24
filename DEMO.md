# Demo: from a fresh cluster to a results pull request

How to set up and run the demo once the node is deployed (`mise run deploy` done). For everything before that (tools, config, cluster), see [FRESH_SETUP.md](FRESH_SETUP.md).

The flow: deploy the demo database, apply the node resources in `config/` with `kubectl`, then run the demo as often as you like. The resources are Kubernetes custom resources that the nexus operator syncs to nexus-api (ADR 0032, [`project/decisions/0032-declarative-node-config-through-an-operator.md`](project/decisions/0032-declarative-node-config-through-an-operator.md)). `fncli demo` creates nothing: it reads the Project resource, stops unless it is synced, then walks one pull request through task and results.

## 0. Once per machine

Run from the repo root. `fncli` comes from `mise run setup`; activate mise in your shell to have it on your PATH.

```bash
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
fncli experiment deploy                 # the experiments release: demo-db, its role and secret, and its Dataset resource
fncli experiment seed demo          # cdm.person with three rows, and an empty results schema
fncli experiment setup demo         # waits for the Dataset demo-db to sync to the node
```

## 3a. Gitea demo

Everything lives in the cluster's Gitea, so nothing outside is needed.

```bash
fncli gitea setup -f config/gitea.yaml -f config/demo.yaml    # the two Gitea repos, and a Kubernetes Secret with each one's OAuth app
kubectl apply -f config/                 # the provider (gitea.yaml) and demo.yaml: NodeSecrets, repos, the project (uses demo-db)
kubectl get fn -n fn-operator                     # wait for Synced on every row; the Message says what is missing
fncli demo --project demo-gitea          # the guided pull request walk (or rely on defaults.project)
```

## 3b. GitHub demo

Needs a GitHub App installed on your repo ([SETUP_GIT_APPS.md](SETUP_GIT_APPS.md)): its key at `~/.config/phems/phems-sandbox.private-key.pem`, and `GH_APP_ID` and `GH_INSTALLATION_ID` in `.dev.env`. For your own repo, copy `config/github/demo-github.yaml` and change the repo, the Secret name and the key path.

```bash
kubectl create secret generic phems-sandbox-github-app -n fn-operator \
  --from-literal=APP_ID="$GH_APP_ID" --from-literal=INSTALLATION_ID="$GH_INSTALLATION_ID" \
  --from-file=PRIVATE_KEY=$HOME/.config/phems/phems-sandbox.private-key.pem
kubectl apply -f config/github/demo-github.yaml   # provider, NodeSecret, repos, project demo-github
kubectl get fn -n fn-operator                              # wait for Synced
fncli demo --project demo-github                  # or defaults.project: demo-github
```

- Run `fncli demo --project demo-gitea` again for another pull request; nothing needs resetting.
- `fncli demo --project demo-gitea triggers/examples/demo-failing.json` makes the task fail on purpose, to see the failure path.
- Without the guided checks: `fncli trigger --pr triggers/examples/demo.json` opens the pull request directly.
- A different project or route than the context's defaults: `--project NAME`, `--pr`.

## Clean up

```bash
kubectl delete -f config/demo.yaml     # the project, repos and NodeSecrets (the provider in gitea.yaml stays)
```

The operator deletes them from the node too, and skips anything another project still uses (see the Message in `kubectl get fn -n fn-operator`). The Gitea repos and OAuth apps stay in Gitea.

## When something fails

| Symptom | Fix |
|---|---|
| `No such command 'gitea'` (or `trigger`) | fncli is an old pipx copy or from another checkout: `pipx uninstall phems`, then `mise run setup` here |
| `is for kubectl context X, but the current one is Y` | `kubectl config use-context kind-fn` |
| `demo` says the Project is not synced yet | `kubectl get fn -n fn-operator` shows which resource is stuck and its Message; fix it and `kubectl apply -f config/` again |
| `Dataset demo-db is not on the node` | step 2 was skipped |
| the dataset login check fails | `fncli experiment seed demo`, then check `kubectl get pods -n experiments` |
