# 0028. Experiments own their database, seed, image and dataset file

Status: Accepted, 2026-11-09.

## Context

An experiment is a real task image run against a real Postgres database with dummy data. Its parts were spread over four places: the database in the experiments chart's values, the dataset and its credentials in the experiment's `project.env` (`DATASET_*`) and in a node file with the project, the image built by a script, and the project's names in `project.env` too. Three problems came of it.
- Renaming the database in one place left the dataset pointing at a secret the chart no longer made, and nothing said so until a task failed.
- `project.env` held `TEST_*` names, and a missing name fell back to `.dev.env` and hit the dev project.
- The demo's dataset had dummy credentials and no database seeded for it, so its dataset healthcheck and task could not run for real.

## Decision

**Everything an experiment needs is in one folder, `experiments/<name>/`.**

| File | Job |
|---|---|
| `values.yaml` | the chart entry: the database, the role and the `db-datasets-<name>` secret (`username` and `password`) |
| `seed.sh`, `seed/` | fills the schemas; safe to rerun |
| `image/` and `docker-bake.hcl` | the task image's source and its `<name>-fn` bake target ([0029](0029-images-are-built-with-docker-buildx-bake.md)) |
| `bootstrap.yaml` | the dataset and its secret only, the secret read from the chart's Kubernetes secret. No project, no repositories, no node block |
| `project.env` | the settings of `run` only: `IMAGE`, `RUN_TIMEOUT` |

- **Projects and repositories stay in the project and globals files** ([0027](0027-bootstrap-files-split-by-stage-of-use.md)), which assign the dataset by name.
- **`fncli experiment setup NAME` checks the names first.** After `up` and `seed`, it checks that the dataset name and the secret name in `bootstrap.yaml` equal `dbs.<name>.name` and `dbs.<name>.secret.name` in `values.yaml`, and only then applies the file.
- **`fncli experiment down` finds its projects without `project.env`,** so a missing name cannot fall back to `.dev.env`.
- **The demo is a tiny experiment, `demo`:** database `demo-db`, role `demo_user`, a `cdm` schema with a small `person` table, an empty `results` schema, and the task image `demo-fn` (it was `pypipes-fn`).

## Consequences

- Adding an experiment is copying a folder and changing its names; nothing outside it needs a dataset edit.
- The demo runs a real task against a real database, with a real dataset healthcheck, and no experiment needs credentials in a file.
- A rename that does not match fails in `setup`, before the node gets a dataset it cannot use.
- The names are checked, not generated: `values.yaml` and `bootstrap.yaml` still each say them.
- Dataset names are unique across the node, so two experiments cannot share one.

## Alternatives considered

- **The dataset in the project's node file (the first version):** the dataset belongs to the experiment, and every file that used it repeated it and could drift from the chart.
- **`DATASET_*` in `project.env`:** a second source for credentials the chart already makes.
- **Generate the dataset password in the bootstrap file (`generate`):** the database already has its own password, so the node's copy must be read from it.
- **Keep the demo on a stand-in dataset:** the healthcheck and the task have nothing to talk to.
