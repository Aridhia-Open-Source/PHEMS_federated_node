# Plan: experiments use bootstrap files

Agreed 2026-11-09. Not started. Do after the migration agent's work (apply/delete callers, old commands removed) has been tested.

## Goal

Each experiment folder (`experiments/projects/<name>/`) holds everything for that experiment:

| File | Job |
|---|---|
| `values.yaml` | experiments chart: creates the database, role and `db-datasets-<name>` secret (`username` + `password`) |
| `seed.sh`, `seed/` | fills the schemas (demo: `cdm` with a tiny table, empty `results`) |
| `image/` | the task image (demo: `demo-fn`, built by `scripts/build_all_images.sh`) |
| `bootstrap.yaml` | NEW. Only the dataset and its secret, read from the chart's k8s secret. No project, no repos |
| `project.env` | SHRINKS to the run-only settings: `SOURCE_DIR`, `IMAGE`, `RUN_TIMEOUT` |

Projects and repos stay in the node's own bootstrap file (e.g. `bootstrap/examples/demo-github.yaml`), which assigns the dataset by name: `datasets: [demo-db]`.

## Steps

1. **Cross-file references.** The loader (`nodefile/loader.py` `check`) rejects a project dataset/repository/secret that is not in the same file. Accept it when it already exists on the node: move that check to diff time, where the backend state is read (`nodefile/diff.py`), and report "not in the file or on the node" there.
2. **`experiments/projects/demo/bootstrap.yaml`**: secret `demo-db-dataset-creds` (USERNAME/PASSWORD from `k8s_secret` `db-datasets-demo` in `experiments`), dataset `demo-db` (host `db-datasets.experiments.svc:5432`, read `cdm`, write `results`). Same for uc1 (`uc1-omop`, `db-datasets-uc1`).
3. **Demo node files** (`bootstrap/examples/demo-*.yaml`): drop their own dataset + secret, keep `datasets: [demo-db]` on the project.
4. **`make experiments setup <name>`** (`cmds/experiment.py`): after `up` and `seed`, check that `bootstrap.yaml`'s dataset name and secret name match `values.yaml` (`dbs.<name>.name`, `dbs.<name>.secret.name`), then run the apply code on it.
5. **`project.env`**: remove everything now in a bootstrap file (`DATASET_*`, `TEST_PROJECT_NAME`, `DEFAULT_PROJECT_DATASET`, `TEST_*_REPO*`, token names, `DEV_ENV`), keep `SOURCE_DIR`, `IMAGE`, `RUN_TIMEOUT`. Make `make experiments down` stop depending on `project.env` to find projects, so a missing name can no longer fall back to `.dev.env` and hit the dev project.
6. Docs: `experiments/README.md`, `experiments/UC1_README.md`.

## Flow after

```bash
make experiments up                 # chart: databases, roles, secrets
make experiments seed demo          # schemas and rows
make experiments setup demo         # name check, then apply experiments/projects/demo/bootstrap.yaml
fncli apply -f examples/demo-github.yaml   # project, repos, assigns demo-db
fncli demo -f examples/demo-github.yaml    # guided PR -> task -> results walk, with the dataset healthcheck
```
