# Pulumi

The `bootstrap` project creates the GitHub deployment repository for a site.
The repository is the GitOps boundary: Pulumi owns its initial Flux and Helm
files, and Flux reconciles the committed state into the site's cluster.

## Bootstrap

From `pulumi/bootstrap`:

```bash
python -m venv .venv
.venv/bin/pip install -r requirements.txt
pulumi stack init <site>
pulumi config set github:owner Aridhia-Open-Source
pulumi config set repository phems-<site>-deployment
pulumi config set site <site>
pulumi config set namespace fn
pulumi config set chart-version <version>
pulumi up
```

The GitHub provider token is read from its normal `GITHUB_TOKEN` environment
variable. `auto_init` creates `main` before `RepositoryFile` resources are
applied, so a new or imported empty repository can be initialized safely.
`overwrite_on_create` and stable resource names make subsequent `pulumi up`
runs idempotent.
