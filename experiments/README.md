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
| `results/NAME/` | no | output of `run --local` |

## Run UC1

Needs the dev cluster up with Tilt (port-forwards for backend 5000, Gitea 4000 and Dagster
3000), `fncli` on PATH, and `.dev.env` at the repo root. UC1's source is the private
`PHDS-centralized-services/MVP-Code` repo, so it is not in this one: clone it into
`sources/uc1`. Dev mode (`UC1_DEV`) needs its R changes for that, which are not merged there yet.

```bash
make experiments up                    # the release: Postgres with every project's database
make experiments build uc1             # localhost:5001/uc1-fn:latest (slow: renv restore)
make experiments seed uc1              # dummy OMOP data into uc1-omop
make experiments setup uc1             # project "uc1" in the node, with its global resources
fncli experiment run uc1 --local       # optional: image straight against the DB, no node
make experiments run uc1               # trigger PR -> task -> results PR in uc1-results-repo
```

These call `fncli experiment up|seed|setup|build|run` (also `teardown NAME` and `down`, see Clean
up). `--local` needs fncli directly, since make takes `--` options as its own. `seed` and `setup`
fail and tell you to run `up` if the release isn't installed. `up`, `seed`, `setup`, `run` and
`teardown` can be rerun after a failure. If `make experiments`
says "No such command", reinstall fncli from this checkout:
`pipx install --force --editable './dagster[cli]'`.

`run` and `run --local` pass the project's `DEV_ENV` (JSON, from `project.env`) to the task.
For UC1 that is `UC1_DEV=1`, a quick run with fewer cohorts. `FULL=1 make experiments run
uc1` runs the whole study.

## Add an experiment

1. Put the source in `sources/NAME`. Its image reads the task contract: `CONNECTION_STRING`
   (a full ODBC string, e.g. `driver={PostgreSQL ANSI};Uid=;Pwd=;Server=host,port;Database=;`), `CDM_SCHEMA`, `WRITE_SCHEMA`, and writes results
   to `ARTIFACT_PATH`.
2. Copy `projects/uc1` to `projects/NAME`, then change the names and the seed.
3. Run `make experiments up` (it upgrades the release with the new database, so this works
   on a running cluster), then `build NAME`, `seed NAME`, `setup NAME` and `run NAME`.

## Check task isolation

`projects/attacker` is a hostile task image, not an experiment. It tries to read other runs'
folders, plant symlinks and `../` paths in its output, reach the backend, Gitea and the
Kubernetes API, read a service account token or another task's Secret, and keep privileges. Each
attempt prints `BLOCKED` or `LEAKED`; `PLANTED` lines are judged by what delivery does with them.
Run it like UC1 (`up`, `build attacker`, `seed attacker`, `setup attacker`, `run attacker`), then
read `attack-report.txt` in the delivered `results.zip` in `attacker-results-repo`, and check the zip
holds no symlink or file from outside the run's folder. To plant a Secret to try for, create one
named `task-decoy` in the tasks namespace. `DEV_ENV` can set `OTHER_RUN_ID` (a run's folder
name to try to read) and `SLEEP_SECONDS` (to hang the task and see the pod's deadline end it).

## Clean up

- `make experiments teardown NAME` removes what `setup` registered in the node for NAME. The
  release and its database stay.
- `make experiments down` tears down every experiment's node project, then uninstalls the
  release. The secrets and database files stay, so a later `setup` gets the same data back.
- Start from empty: `kubectl delete ns experiments`, then delete
  `~/.fn/data/experiments` (Postgres owns it, so you need root or the kind node).
