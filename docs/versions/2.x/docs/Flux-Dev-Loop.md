# Flux dev loop

Flux delivering the dev node from a test site repository in the dev cluster's Gitea, to try upgrades, reverts and config changes ([ADR 0031](https://github.com/Aridhia-Open-Source/PHEMS_federated_node/blob/main/project/decisions/0031-gitops-deployment-with-flux.md)). For a real site, see [Deploy with Flux](./Deploy-With-Flux).

Needs a dev node from `mise run deploy` (it includes Gitea) owned by your worktree, and `mise run setup` for the pinned `flux` and `sops` CLIs. Don't run `tilt up` while Flux owns the release: it redeploys the dev images over it.

```bash
mise run flux publish 0.0.1-dev   # this chart, as version 0.0.1-dev, into the kind registry
mise run flux up                  # install Flux, push site-example/ to Gitea as gitea_admin/fn-site, adopt the release
mise run flux status              # Flux objects and the release's helm history
mise run flux down                # remove Flux and fn-site; the release stays
```

- `up` makes the dev age key (`bootstrap/sops/age.agekey`, kept across runs) and loads it into Flux, fills `first-user-secret.yaml` from `.dev.env` and encrypts it before the first push.
- `site-example/helmrelease.yaml` uses the release name and namespace `mise run deploy` used, so Flux adopts that release.
- While Flux owns the release, `mise run deploy` and `mise run teardown` refuse; `mise run flux down` hands it back.
- The dev site values pin the dev images (`latest`), so a version bump changes only the chart.

## The loop

Clone `http://localhost:4000/gitea_admin/fn-site.git` (login `gitea_admin`, password from `kubectl get secret gitea-admin -n fn -o jsonpath='{.data.password}' | base64 -d`), then:

- **Upgrade:** `mise run flux publish 0.0.2-dev`, set `version: "0.0.2-dev"` in `helmrelease.yaml`, push. `helm history fn-dev -n fn` shows the new revision.
- **Revert:** `git revert HEAD`, push.
- **Config:** change a value in `values.yaml`, push.
- **Secret:** `sops encrypt -i` in your clone (its `.sops.yaml` has your key); `SOPS_AGE_KEY_FILE=<repo>/bootstrap/sops/age.agekey sops <file>` edits one.

Flux looks every minute; `flux reconcile kustomization fn-site -n flux-system --with-source` skips the wait.
