# Pulumi

The `bootstrap` project creates one GitHub deployment repository for one or
more environments. The repository is the GitOps boundary: Pulumi owns the
initial Flux and Helm files, and Flux reconciles each environment's committed
state into its cluster.

## Bootstrap

From `pulumi/bootstrap`:

```bash
python -m venv .venv
.venv/bin/pip install -r requirements.txt
pulumi stack init <stack>
pulumi config set github:owner Aridhia-Open-Source
pulumi config set repository phems-deployment
pulumi config set environments develop,qa
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
environment secrets separately through SOPS or External Secrets before Flux
installs the release. Each environment's files are under
`clusters/<environment>/`.

## GitHub Actions

`.github/workflows/pulumi-bootstrap.yml` runs `pulumi preview` for
same-repository pull requests that change this project. A push to protected
`main`, or a manual dispatch, runs `pulumi up --yes` through the
`pulumi-bootstrap` GitHub environment. Configure required reviewers on that
environment so applying infrastructure is an explicit approval step.

Set `GITHUB_TOKEN` in the repository for previews and in the
`pulumi-bootstrap` environment for applies. It must be a fine-grained GitHub
token with repository administration permission for the deployment repository.
No Pulumi Cloud token or backend configuration is required.

Each job logs into an ephemeral local Pulumi backend. State exists only for the
duration of that job and is discarded afterwards. The workflow is therefore
intended for the one-off bootstrap: rerunning it is not state-aware and may
attempt to recreate or conflict with resources that already exist.

Set repository variables `PULUMI_STACK`, `PULUMI_REPOSITORY`, and
`PULUMI_ENVIRONMENTS` for the protected push path. A manual run can override
all three values from the Actions form, for example:

```bash
gh workflow run pulumi-bootstrap.yml \
  -f stack=production \
  -f repository=phems-deployment \
  -f environments='develop,qa'
```

Environments are trimmed, must use lowercase DNS-style names, and must be
unique. The workflow rejects empty, duplicate, or invalid values before
changing the stack. One Pulumi stack manages the target repository and all
of its `clusters/<environment>/` files; environments are not separate
stacks. Pull-request previews use an isolated `pr-<number>` stack and
repository name; previews from forks are skipped because GitHub does not
expose repository secrets to fork workflows.

The workflow URL is
`https://github.com/Aridhia-Open-Source/PHEMS_federated_node/actions/workflows/pulumi-bootstrap.yml`.
