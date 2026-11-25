# Continuous integration

The repository's CI is defined in [`.github/workflows/build.yml`](https://github.com/Aridhia-Open-Source/PHEMS_federated_node/blob/main/.github/workflows/build.yml). It validates pull requests, merge queues, release tags and the supported development branches without requiring a local cluster.

## When it runs

- Pull requests always receive a `ci-ok` check. The workflow first detects which areas changed and runs only the relevant checks.
- `merge_group` runs the same required checks against the merge-queue commit.
- Pushes to `main`, `develop`, `dagster-main`, `dagster-develop` and `actions-sandbox` run the trunk workflow. Tags build and publish release images.
- Documentation-only changes are ignored by the image-build workflow. The separate [`Docs`](https://github.com/Aridhia-Open-Source/PHEMS_federated_node/blob/main/.github/workflows/docs.yml) workflow builds strict previews for pull requests and publishes branch previews to GitHub Pages.

The workflow cancels obsolete pull-request runs, but does not cancel a merge-queue run. This keeps the required check for the commit GitHub is about to merge.

## Checks

The changes detector selects these areas:

| Area | Checks |
|---|---|
| `nexus/api` | pylint, image build and the API test suite |
| `dagster` | pylint, image build and Dagster/fncli tests |
| `k8s/federated-node` | Helm lint, template validation and helm-unittest |
| images and shared build files | the affected image builds |
| release branches and tags | promotion and release jobs after the checks pass |

The `stack-gate` job prevents a stacked pull request from running against an unexpected base. A pull request must target the stack branch named by its plan; the final stack PR targets the development branch. The `ci-ok` job is the single required status and succeeds only when the selected checks have completed successfully (or when an area has no applicable changes).

## Local checks

Use the smallest check that covers the files you changed. From the repository root:

```bash
mise run pylint                 # Python linting
mise run helm lint              # chart linting
mise run helm template          # render the chart
mise run helm tests             # helm-unittest
cd nexus/api && ./run_tests.sh local tests/<path>
cd dagster && ./run_tests.sh local <path>
```

The CI workflow runs the pinned commands in its container images. A passing local command does not replace the required GitHub check, especially for a merge-queue build.
