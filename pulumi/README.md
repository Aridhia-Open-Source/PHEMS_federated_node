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
variable; use a fine-grained token scoped to the target repository with
contents administration permission. `auto_init` creates `main` before
`RepositoryFile` resources are applied, so a new or imported empty repository
can be initialized safely. `overwrite_on_create` and stable resource names
make subsequent `pulumi up` runs idempotent.

The default chart version follows the chart currently published by the release
workflow (`2.0.0`). Set `chart-version` explicitly when bootstrapping a
different release. The generated repository contains no credentials: provide
site secrets separately through SOPS or External Secrets before Flux installs
the release.

## GitHub Actions

`.github/workflows/pulumi-bootstrap.yml` runs `pulumi preview` for
same-repository pull requests that change this project. A push to protected
`main`, or a manual dispatch, runs `pulumi up --yes` through the
`pulumi-bootstrap` GitHub environment. Configure required reviewers on that
environment so applying infrastructure is an explicit approval step.

Set these secrets in the repository for previews and in the
`pulumi-bootstrap` environment for applies:

* `PULUMI_ACCESS_TOKEN` - a Pulumi Cloud access token. The default backend is
  `https://api.pulumi.com`; set the `PULUMI_BACKEND_URL` repository/environment
  variable when using another Pulumi backend.
* `GITHUB_TOKEN` - a fine-grained GitHub token with repository administration
  permission for the deployment repositories created by this stack.

Set repository variables `PULUMI_STACK` and `PULUMI_SITE` for the protected
push path. A manual run can override both values from the Actions form. Stack
and site values are validated before apply, and each stack has its own
concurrency group. Pull-request previews use an isolated `pr-<number>` stack
and repository name; previews from forks are skipped because GitHub does not
expose repository secrets to fork workflows.

The workflow URL is
`https://github.com/Aridhia-Open-Source/PHEMS_federated_node/actions/workflows/pulumi-bootstrap.yml`.
