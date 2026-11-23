# Flux site repository mirror

When the site repository lives outside the cluster (GitHub, the site's own git), the node's Gitea keeps a pull mirror of it and Flux pulls from the mirror ([ADR 0031](https://github.com/Aridhia-Open-Source/PHEMS_federated_node/blob/main/project/decisions/0031-gitops-deployment-with-flux.md)). Commits land in the site repository; Gitea picks them up within 10 minutes.

```bash
SITE_REPO_TOKEN=<read token> mise run mirror-to-gitea https://github.com/<org>/<site-repo>.git
mise run mirror-to-gitea      # sync now instead of waiting
```

- The script uses the current `kubectl` context and reads `NAMESPACE` (the node's namespace) from `.dev.env`.
- The token is only needed for a private repository.
- The mirror is `gitea_admin/fn-site`. Point Flux at `http://gitea.<namespace>.svc:4000/gitea_admin/fn-site.git` with `--branch=main`: the site repository's default branch must be `main`.
- The Gitea pod must reach the site repository's host directly: Gitea does not use the chart's `proxy` or `customCA` yet.
- Charts and images still come from `ghcr.io`.

On the dev cluster, run `mise run mirror-to-gitea URL` before `mise run flux up`: `up` finds the mirror and points Flux at it.
