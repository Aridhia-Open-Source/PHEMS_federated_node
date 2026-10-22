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
| `projects/NAME/project.env` | yes | image, database, and the node project and Gitea repos fncli sets up |
| `projects/NAME/values.yaml` | yes | the project's `dbs.NAME` entry for the chart |
| `projects/NAME/seed.sh` | yes | prints the SQL that seeds the database |
| `sources/NAME/` | no | the image's build context (often its own git repo) |
| `results/NAME/` | no | output of `run-local` |

## Run UC1

Needs the dev cluster up with Tilt (port-forwards for backend 5000, Gitea 4000 and Dagster
3000), `fncli` on PATH, and `.dev.env` at the repo root. UC1's source is the private
`PHDS-centralized-services/MVP-Code` repo, so it is not in this one: clone it into
`sources/uc1`. Dev mode (`UC1_DEV`) needs its R changes for that, which are not merged there yet.

```bash
make experiments-up                   # release + uc1-omop database
make experiments-seed EXP=uc1         # dummy OMOP data + fncli setup-project (project "uc1")
make experiments-build EXP=uc1        # localhost:5001/uc1-fn:latest (slow: renv restore)
make experiments-run-local EXP=uc1    # optional: image straight against the DB, no node
make experiments-run EXP=uc1          # trigger PR -> task -> results PR in uc1-results-repo
```

Or call `experiments/experiments.sh` directly with the same arguments.

`run` and `run-local` pass the project's `DEV_ENV` (JSON, from `project.env`) to the task.
For UC1 that is `UC1_DEV=1`, a quick run with fewer cohorts. `FULL=1 make experiments-run
EXP=uc1` runs the whole study.

## Add an experiment

1. Put the source in `sources/NAME`. Its image reads the task contract: `CONNECTION_STRING`
   (`server=;database=;port=;uid=;pwd=;`), `CDM_SCHEMA`, `WRITE_SCHEMA`, and writes results
   to `ARTIFACT_PATH`.
2. Copy `projects/uc1` to `projects/NAME`, then change the names and the seed.
3. Run `make experiments-up`, then `seed`, `build` and `run`. `up` is an upgrade, so this
   works on a running cluster.

## Clean up

- `fncli teardown-project`, with the project's env, removes what `seed` registered in the node.
- `make experiments-down` uninstalls the release. The secrets and database files stay, so a
  later `up` gets the same data back.
- Start from empty: `kubectl delete ns experiments`, then delete
  `~/.fn/data/experiments` (Postgres owns it, so you need root or the kind node).
