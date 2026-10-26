# Experiments

Run real experiment images against the dev node. Each one has a real Postgres database with
dummy data, a dataset whose credentials go through the backend's secret, and results
delivered to Gitea.

The databases are their own Helm release in the `experiments` namespace (`chart/`), apart
from the federated-node chart. The node only sees the dataset that fncli registers, at
`db-datasets.experiments.svc`.

## Layout

| Path | Committed | What |
|---|---|---|
| `chart/` | yes | the datasets Postgres, plus a database, role and generated password per project |
| `projects/NAME/project.env` | yes | image, database, and the node project and Gitea repos fncli sets up; wins over `.dev.env` and the shell |
| `projects/NAME/values.yaml` | yes | the project's `dbs.NAME` entry for the chart |
| `projects/NAME/seed.sh` | yes | prints the SQL that seeds the database; must be safe to rerun |
| `sources/NAME/` | no | the image's build context (often its own git repo) |
| `results/NAME/` | no | output of `run-local` |

## Run UC1

Needs the dev cluster up with Tilt (port-forwards for backend 5000, Gitea 4000 and Dagster
3000), `fncli` on PATH, and `.dev.env` at the repo root. UC1's source is the private
`PHDS-centralized-services/MVP-Code` repo, so it is not in this one: clone it into
`sources/uc1`. Dev mode (`UC1_DEV`) needs its R changes for that, which are not merged there yet.

```bash
make experiments setup uc1         # release + uc1-omop database, dummy OMOP data, project "uc1" in the node
make experiments build uc1         # localhost:5001/uc1-fn:latest (slow: renv restore)
make experiments run-local uc1     # optional: image straight against the DB, no node
make experiments run uc1           # trigger PR -> task -> results PR in uc1-results-repo
```

These call `fncli experiment setup|build|run-local|run uc1` (also `teardown NAME` and `down`,
see Clean up). `setup`, `run` and `teardown` can be rerun after a failure. If `make experiments`
says "No such command", reinstall fncli from this checkout:
`pipx install --force --editable './dagster[cli]'`.

`run` and `run-local` pass the project's `DEV_ENV` (JSON, from `project.env`) to the task.
For UC1 that is `UC1_DEV=1`, a quick run with fewer cohorts. `FULL=1 make experiments run
uc1` runs the whole study.

## Add an experiment

1. Put the source in `sources/NAME`. Its image reads the task contract: `CONNECTION_STRING`
   (`server=;database=;port=;uid=;pwd=;`), `CDM_SCHEMA`, `WRITE_SCHEMA`, and writes results
   to `ARTIFACT_PATH`.
2. Copy `projects/uc1` to `projects/NAME`, then change the names and the seed.
3. Run `make experiments setup NAME`, then `build NAME` and `run NAME`. `setup` upgrades the
   release, so this works on a running cluster.

## Clean up

- `make experiments teardown NAME` removes what `setup` registered in the node for NAME. The
  release and its database stay.
- `make experiments down` tears down every experiment's node project, then uninstalls the
  release. The secrets and database files stay, so a later `setup` gets the same data back.
- Start from empty: `kubectl delete ns experiments`, then delete
  `~/.fn/data/experiments` (Postgres owns it, so you need root or the kind node).
